"""Fully local, independently labeled discharge billing and letter-comparison checks."""
import copy
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import httpx
from openai import APIConnectionError, AuthenticationError, RateLimitError
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from app.discharge_claim import (ROOT, confirm_discharge_ocr, discharge_ocr_review_pages, discharge_packet_bytes,
                                 evaluate_discharge, load_discharge_fixture)
from app.document_text import Transcript, contains_quote
from fixtures.discharge import build


def reviewed(result):
    return {**result, "status": "staff_reviewed", "revision": 2, "reviewer": "Billing coordinator",
            "reviewed_revision": 2, "history": [{"revision": 1, "status": "needs_review"},
                                                 {"revision": 2, "status": "staff_reviewed"}]}


def revised_pdf(raw, change):
    original = PdfReader(io.BytesIO(raw))
    stream = io.BytesIO()
    c = Canvas(stream, invariant=1)
    for i, page in enumerate(original.pages, 1):
        t = c.beginText(30, 795)
        t.setFont("Helvetica", 9)
        for line in change(i, page.extract_text().splitlines()):
            t.textLine(line)
        c.drawText(t)
        c.showPage()
    c.save()
    return stream.getvalue()


def mock_transcribed_packet(scenario="aligned"):
    meta, raw, names = load_discharge_fixture(scenario)
    responses = []
    originals = dict(raw)
    for role in ("bill", "summary"):
        buf = io.BytesIO()
        canvas = Canvas(buf, invariant=1)
        for page in PdfReader(io.BytesIO(raw[role])).pages:
            text = page.extract_text()
            image = Image.new("L", (1000, 1300), 255)
            ImageDraw.Draw(image).multiline_text((20, 30), text, fill=0, spacing=4)
            canvas.drawImage(ImageReader(image), 0, 0, width=590, height=800)
            canvas.showPage()
            responses.append(SimpleNamespace(status="completed", output_parsed=Transcript(legibility="complete", text=text)))
        canvas.save()
        originals[role] = buf.getvalue()
    client = Mock()
    client.responses.parse.side_effect = responses
    held = evaluate_discharge(meta, originals, names, ocr_client=client)
    assert client.responses.parse.call_count == 4
    return {**held, "revision": 1}, originals


class DischargeClaimTests(unittest.TestCase):
    def test_public_scenarios_match_labels_and_every_finding_anchor(self):
        expected = json.loads((ROOT / "expected.json").read_text())
        self.assertGreaterEqual(len(expected), 19)
        for scenario, gold in expected.items():
            with self.subTest(scenario=scenario):
                meta, originals, names = load_discharge_fixture(scenario)
                case = evaluate_discharge(meta, originals, names)
                self.assertEqual(case["status"], gold["status"])
                codes = {f["code"] for f in case["findings"]}
                self.assertTrue(set(gold["required_findings"]) <= codes)
                self.assertIsNone(case["payable_minor"])
                self.assertEqual(case["insurer_decision"], "unrecorded")
                pages = {role: PdfReader(io.BytesIO(data)).pages for role, data in originals.items()}
                for row in case["findings"]:
                    for ref in row["sources"]:
                        page = pages[ref["role"]][ref["page"]-1]
                        if ref["method"] == "unreadable":
                            self.assertFalse(page.extract_text().strip())
                        else:
                            self.assertTrue(contains_quote(page.extract_text(), ref["quote"]))
                if codes & {"member_mismatch", "encounter_mismatch", "mixed_currency"}:
                    self.assertIsNone(case["bill_total_minor"])
                    self.assertIsNone(case["currency"])

    def test_all_pdf_exhibits_reproducible_and_originals_embedded_exactly(self):
        with TemporaryDirectory() as temp:
            build.build(Path(temp))
            expected = {p.name: p.read_bytes() for p in ROOT.glob("*.pdf")}
            self.assertEqual(expected, {p.name: p.read_bytes() for p in Path(temp).glob("*.pdf")})
        meta, originals, names = load_discharge_fixture("aligned")
        case = evaluate_discharge(meta, originals, names)
        self.assertEqual((case["currency"], case["bill_total_minor"], case["source_reported_cap_minor"],
                          case["source_reported_patient_share_minor"]), ("THB", 8750000, 9000000, 500000))
        self.assertTrue(all(len(PdfReader(io.BytesIO(raw)).pages) == 2 for raw in originals.values()))
        approved = reviewed(case)
        blob = discharge_packet_bytes(approved, originals)
        self.assertEqual(blob, discharge_packet_bytes(approved, originals))
        packet = PdfReader(io.BytesIO(blob))
        self.assertEqual(len(packet.pages), 1)
        self.assertIn("requests a final payer decision", packet.pages[0].extract_text())
        self.assertEqual(set(packet.attachments), set(names.values()))
        for source in case["sources"]:
            contents = packet.attachments[source["label"]]
            self.assertEqual(list(contents), [originals[source["role"]]])
            self.assertEqual(hashlib.sha256(contents[0]).hexdigest(), source["sha256"])

    def test_unsupported_free_text_compound_letter_and_final_payer_decision_are_not_automated(self):
        meta, originals, names = load_discharge_fixture()
        for role, original, next_wording, code in (
                ("letter", "Letter status: Preauthorization", "Letter status: Final settlement decision", "unsupported_terms"),
                ("letter", "Authorized billed-charge ceiling: THB 90,000.00", "Maximum payer payment: THB 90,000.00", "unrecognized_layout"),
                ("summary", "Disposition: Discharged home", "Disposition: Transferred for a different scheduled operation", "clinical_review")):
            with self.subTest(replacement=next_wording):
                change = lambda i, lines: [line.replace(original, next_wording) for line in lines]
                updated = {**originals, role: revised_pdf(originals[role], change)}
                result = evaluate_discharge(meta, updated, names)
                self.assertEqual(result["status"], "needs_review")
                finding = next(f for f in result["findings"] if f["code"] == code)
                self.assertIn(next_wording, [a["quote"] for a in finding["sources"]])
                self.assertIsNone(result["payable_minor"])
        letter = revised_pdf(originals["letter"], lambda i, lines: [*lines, "Special condition: Surgeon fee requires a second letter."] if i == 2 else lines)
        result = evaluate_discharge(meta, {**originals, "letter": letter}, names)
        self.assertTrue(any(a["role"] == "letter" and a["page"] == 2 and "second letter" in a["quote"]
                            for f in result["findings"] for a in f["sources"]))
        text_only = revised_pdf(originals["bill"], lambda i, lines: ["New accounting layout", "The estimated balance is about 90k."])
        result = evaluate_discharge(meta, {**originals, "bill": text_only}, names)
        self.assertEqual((result["status"], result["bill_total_minor"]), ("needs_review", None))
        self.assertTrue(any(a["role"] == "bill" and a["page"] == 1 for f in result["findings"] for a in f["sources"]))

    def test_missing_physical_page_hidden_rider_duplicate_service_different_id_require_staff(self):
        meta, originals, names = load_discharge_fixture()
        partial = PdfWriter()
        partial.add_page(PdfReader(io.BytesIO(originals["summary"])).pages[0])
        partial_stream = io.BytesIO()
        partial.write(partial_stream)
        result = evaluate_discharge(meta, {**originals, "summary": partial_stream.getvalue()}, names)
        self.assertIn("page_order", [f["code"] for f in result["findings"]])
        attached = PdfWriter(clone_from=io.BytesIO(originals["letter"]))
        attached.add_attachment("rider.pdf", originals["records"])
        stream = io.BytesIO()
        attached.write(stream)
        result = evaluate_discharge(meta, {**originals, "letter": stream.getvalue()}, names)
        self.assertIn("unexamined_content", [f["code"] for f in result["findings"]])
        def duplicate(i, lines):
            extra = [line.replace("OR01", "OR03") for line in lines if line.startswith("Charge: OR01")]
            return lines + extra
        result = evaluate_discharge(meta, {**originals, "bill": revised_pdf(originals["bill"], duplicate)}, names)
        self.assertIn("possible_duplicate", [f["code"] for f in result["findings"]])

    def test_no_export_on_history_revision_open_financial_issue_or_changed_original(self):
        meta, originals, names = load_discharge_fixture("aligned")
        case = evaluate_discharge(meta, originals, names)
        with self.assertRaises(ValueError):
            discharge_packet_bytes(case, originals)
        approved = reviewed(case)
        for stale in ({**approved, "reviewed_revision": 1},
                      {**approved, "history": [*approved["history"], {"revision": 3}]},
                      {**approved, "bill_total_minor": 1}):
            with self.assertRaises(ValueError):
                discharge_packet_bytes(stale, originals)
        with self.assertRaisesRegex(ValueError, "revision"):
            discharge_packet_bytes(approved, {**originals, "summary": originals["bill"]})
        meta, wrong, names = load_discharge_fixture("over_cap")
        with self.assertRaisesRegex(ValueError, "support"):
            discharge_packet_bytes(reviewed(evaluate_discharge(meta, wrong, names)), wrong)

    def test_late_receipt_uses_record_and_letter_has_no_automatic_financial_result(self):
        result = evaluate_discharge(*load_discharge_fixture("late_reply"))
        finding = next(f for f in result["findings"] if f["code"] == "late_reply")
        self.assertEqual(finding["severity"], "review")
        self.assertEqual({r["role"] for r in finding["sources"]}, {"records", "letter"})
        self.assertIsNone(result["payable_minor"])
        result = evaluate_discharge(*load_discharge_fixture("share_mismatch"))
        finding = next(f for f in result["findings"] if f["code"] == "share_mismatch")
        self.assertEqual({a["role"] for a in finding["sources"]}, {"bill", "letter"})

    def test_partial_transcription_keeps_other_pages_but_provider_errors_propagate(self):
        meta, originals, names = load_discharge_fixture()
        summary = PdfWriter()
        summary.add_page(PdfReader(io.BytesIO(originals["summary"])).pages[0])
        raster = io.BytesIO()
        c = Canvas(raster, invariant=1)
        c.drawImage(ImageReader(Image.new("L", (60, 40), 100)), 30, 20)
        c.showPage()
        c.save()
        summary.add_page(PdfReader(io.BytesIO(raster.getvalue())).pages[0])
        stream = io.BytesIO()
        summary.write(stream)
        raw = {**originals, "summary": stream.getvalue()}
        client = Mock()
        for grade in ("partial", "unreadable"):
            client.responses.parse.return_value = SimpleNamespace(status="completed",
                output_parsed=Transcript(legibility=grade, text="Uncertain amount or date"))
            result = evaluate_discharge(meta, raw, names, ocr_client=client)
            finding = next(f for f in result["findings"] if f["code"] == "unreadable_summary")
            self.assertEqual([(r["page"], r["method"]) for r in finding["sources"]], [(2, "unreadable")])
            self.assertEqual(result["status"], "needs_review")
            source = next(s for s in result["sources"] if s["role"] == "summary")
            self.assertTrue(any(a["page"] == 1 and a["quote"].startswith("Performed procedure:") for a in source["anchors"]))
            self.assertFalse(any("Uncertain" in a["quote"] for a in source["anchors"]))
        req = httpx.Request("POST", "https://api.openai.com/v1/responses")
        for error in (AuthenticationError("auth", response=httpx.Response(401, request=req), body=None),
                      RateLimitError("rate", response=httpx.Response(429, request=req), body=None),
                      APIConnectionError(request=req)):
            client.responses.parse.side_effect = error
            with self.assertRaises(type(error)):
                evaluate_discharge(meta, raw, names, ocr_client=client)

    def test_all_ocr_pages_rechecked_as_one_new_review_and_audited_in_export(self):
        held, originals = mock_transcribed_packet()
        candidate = discharge_ocr_review_pages(held)
        self.assertEqual({(p["role"], p["page"]) for p in candidate},
                         {("bill", 1), ("bill", 2), ("summary", 1), ("summary", 2)})
        for item in candidate:
            self.assertEqual(item["transcript_sha256"], hashlib.sha256(item["text"].encode()).hexdigest())
            self.assertEqual(item["sha256"], hashlib.sha256(originals[item["role"]]).hexdigest())
        confirmation = held["ocr_review_pages"]
        cleared = confirm_discharge_ocr(held, originals, "Scan reviewer", list(reversed(confirmation)))
        self.assertEqual((cleared["status"], cleared["findings"], cleared["payable_minor"]), ("ready_for_review", [], None))
        self.assertEqual(cleared["ocr_attestation"]["source_revision"], 1)
        self.assertEqual(held["status"], "needs_review")
        with self.assertRaises(ValueError):
            discharge_packet_bytes({**cleared, "revision": 2}, originals)
        approved = reviewed(cleared)
        pdf = PdfReader(io.BytesIO(discharge_packet_bytes(approved, originals)))
        audit = " ".join(page.extract_text() for page in pdf.pages[1:])
        self.assertIn("Scan reviewer", audit)
        self.assertIn("source revision 1", audit)
        for item in confirmation:
            self.assertIn(item["transcript_sha256"], "".join(audit.split()))
        for name in ("summary", "bill"):
            self.assertEqual(list(pdf.attachments[name + ".pdf"]), [originals[name]])

    def test_ocr_attestation_cannot_cover_missing_repeated_stale_tampered_or_unresolved_pages(self):
        held, originals = mock_transcribed_packet()
        expected = held["ocr_review_pages"]
        for submitted in (expected[:-1], [*expected[:-1], expected[0]],
                          [{**expected[0], "sha256": "a"*64}, *expected[1:]],
                          [{**expected[0], "transcript_sha256": "b"*64}, *expected[1:]],
                          [{**expected[0], "page": True}, *expected[1:]]):
            with self.subTest(sample=submitted[0]["page"]), self.assertRaises(ValueError):
                confirm_discharge_ocr(held, originals, "Reviewer", submitted)
        with self.assertRaisesRegex(ValueError, "named"):
            confirm_discharge_ocr(held, originals, " ", expected)
        tampered = copy.deepcopy(held)
        tampered["ocr_pages"]["summary"]["pages"]["1"] += " revised wording"
        with self.assertRaisesRegex(ValueError, "transcript"):
            confirm_discharge_ocr(tampered, originals, "Reviewer", expected)
        with self.assertRaisesRegex(ValueError, "original"):
            confirm_discharge_ocr(held, {**originals, "summary": originals["bill"]}, "Reviewer", expected)
        complex_case, files = mock_transcribed_packet("over_cap")
        with self.assertRaisesRegex(ValueError, "beyond OCR"):
            confirm_discharge_ocr(complex_case, files, "Reviewer", complex_case["ocr_review_pages"])
        # Replay of the actual originals catches a financially material issue even if
        # a stale stored view omitted it from its displayed finding list.
        complex_case["findings"] = [f for f in complex_case["findings"] if f["code"] == "verify_ocr"]
        with self.assertRaisesRegex(ValueError, "sole open finding"):
            confirm_discharge_ocr(complex_case, files, "Reviewer", complex_case["ocr_review_pages"])
        approved = reviewed(confirm_discharge_ocr(held, originals, "Reviewer", expected))
        wrong_attestation = {**approved["ocr_attestation"], "source_revision": 2}
        with self.assertRaisesRegex(ValueError, "revision"):
            discharge_packet_bytes({**approved, "ocr_attestation": wrong_attestation}, originals)


if __name__ == "__main__":
    unittest.main()
