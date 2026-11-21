"""Fully local, independently labeled discharge billing and letter-comparison checks."""
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from app.discharge_claim import ROOT, discharge_packet_bytes, evaluate_discharge, load_discharge_fixture
from app.document_text import contains_quote
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


if __name__ == "__main__":
    unittest.main()
