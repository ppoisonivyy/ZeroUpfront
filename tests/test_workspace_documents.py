"""End-to-end checks against the actual synthetic exhibits and exported forms."""
import copy
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from pypdf import PdfReader

from app.document_text import Transcript, contains_quote, read_document
from app.workspace_documents import evaluate_estimate, packet_bytes, seed_cases


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def exhibit(case_id, filename):
    return (FIXTURES / "cases" / case_id / filename).read_bytes()


def original_files(case_id, estimate_name="estimate.pdf"):
    policy = "mango.pdf" if case_id == "Z003" else "alder.pdf"
    return {"policy": (FIXTURES / "policies" / policy).read_bytes(),
            "plan": exhibit(case_id, "plan.pdf"), "estimate": exhibit(case_id, estimate_name)}


def review(snapshot, revision=1, older=()):
    return {**snapshot, "revision": revision, "reviewed_revision": revision, "reviewer": "Nok S.",
            "insurer_status": "not_sent", "status": "staff_reviewed",
            "history": [*older, {"revision": revision, "status": "staff_reviewed", "total": snapshot["total"]}]}


class WorkspaceDocumentTests(unittest.TestCase):
    def test_seed_and_revision_match_independent_expected_and_actual_source_pages(self):
        initial = {snapshot["id"]: snapshot for snapshot in seed_cases()}
        expected = json.loads((FIXTURES / "expected.json").read_text())
        statuses = {"missing_evidence": "needs_itemization"}
        for case in expected:
            case_id = case["case"]
            estimate_name = case["estimate"]
            with self.subTest(case=case_id, file=estimate_name):
                result = evaluate_estimate(case_id, exhibit(case_id, estimate_name))
                self.assertEqual(result["status"], statuses.get(case["result"], case["result"]))
                self.assertEqual((result["total"], result["clause"]), (case["total_thb"], case["flag_clause"]))
                if estimate_name == "estimate.pdf":
                    self.assertEqual(initial[case_id], result)
                for source in result["sources"]:
                    folder = FIXTURES / ("policies" if source["role"] == "policy" else "cases/" + case_id)
                    document = read_document(folder / source["label"])
                    self.assertEqual(source["sha256"], document.sha256)
                    for anchor in source["anchors"]:
                        wording = ((anchor["clause"] + " ") if anchor["clause"] else "") + anchor["quote"]
                        self.assertTrue(contains_quote(document.pages[anchor["page"]-1].text, wording))
                        self.assertEqual(anchor["method"], "digital")
        excluded = {s["role"]: s for s in initial["Z003"]["sources"]}
        self.assertIn("excluded", excluded["policy"]["quote"])
        self.assertIn("Solely cosmetic", excluded["plan"]["quote"])
        self.assertEqual(excluded["estimate"]["quote"], "Total estimated charges THB 95,000")

    def test_same_total_replacement_and_actual_rows(self):
        original = evaluate_estimate("Z002", exhibit("Z002", "estimate.pdf"))
        revised = evaluate_estimate("Z002", exhibit("Z002", "revised-estimate.pdf"), "Replacement (final).pdf")
        self.assertEqual(original["total"], revised["total"])
        self.assertEqual(original["lines"], [])
        self.assertEqual(revised["lines"], [{"label": "Hospital services", "amount": 52000},
                                            {"label": "Operating team", "amount": 30000}])
        self.assertEqual(revised["total"], sum(row["amount"] for row in revised["lines"]))
        estimate = next(s for s in revised["sources"] if s["role"] == "estimate")
        self.assertEqual(estimate["label"], "Replacement (final).pdf")
        self.assertEqual(estimate["sha256"], hashlib.sha256(exhibit("Z002", "revised-estimate.pdf")).hexdigest())
        self.assertEqual(estimate["anchors"][2]["quote"], "Operating team THB 30,000")

    def test_unknown_wrong_case_and_non_estimates_are_rejected_before_ocr(self):
        for wrong in (b"unknown", exhibit("Z001", "estimate.pdf"), exhibit("Z003", "estimate.pdf"),
                      exhibit("Z002", "plan.pdf"), exhibit("Z002", "revised-estimate.pdf") + b"other"):
            with self.subTest(digest=hashlib.sha256(wrong).hexdigest()):
                client = Mock()
                with self.assertRaisesRegex(ValueError, "encounter binding"):
                    evaluate_estimate("Z002", wrong, "revised-estimate.pdf", ocr_client=client)
                client.responses.parse.assert_not_called()
        for name in ("../danger.pdf", "nested\\danger.pdf", "bad\nname.pdf", "image.jpg"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "filename"):
                evaluate_estimate("Z002", exhibit("Z002", "revised-estimate.pdf"), name)

    def test_ocr_only_with_explicit_client_and_independent_financial_agreement(self):
        scanned = exhibit("Z002", "scanned-estimate.pdf")
        with self.assertRaisesRegex(ValueError, "needs OCR"):
            evaluate_estimate("Z002", scanned)
        transcript = read_document(FIXTURES / "cases/Z002/estimate.pdf").text
        for wording, message in ((transcript, None), (transcript.replace("82,000", "28,000"), "disagrees"),
                                 (transcript + " DEMO-Z003", "conflicting"),
                                 (transcript.replace("AT-2026.1", "AT-2026.2"), "does not match"),
                                 (transcript + " AT-2026.2", "conflicting"),
                                 (transcript + " Supplies THB 5", "reconciled")):
            with self.subTest(message=message):
                client = Mock()
                client.responses.parse.return_value = SimpleNamespace(status="completed",
                    output_parsed=Transcript(legibility="complete", text=wording))
                if message:
                    with self.assertRaisesRegex(ValueError, message):
                        evaluate_estimate("Z002", scanned, ocr_client=client)
                    continue
                result = evaluate_estimate("Z002", scanned, ocr_client=client)
                self.assertEqual(result["status"], "needs_itemization")
                estimate = next(s for s in result["sources"] if s["role"] == "estimate")
                self.assertEqual((estimate["method"], estimate["page"]), ("ocr", 1))

    def test_unreviewed_stale_excluded_or_unverified_fields_cannot_export(self):
        initial = {snapshot["id"]: snapshot for snapshot in seed_cases()}
        originals = original_files("Z001")
        with self.assertRaises(ValueError):
            packet_bytes(initial["Z001"], originals)
        for case_id in ("Z002", "Z003"):
            with self.subTest(case=case_id), self.assertRaises(ValueError):
                packet_bytes(review(initial[case_id]), original_files(case_id))
        good = review(initial["Z001"])
        for changes in ({"status": "needs_review"}, {"reviewer": "   "}, {"reviewed_revision": 0},
                        {"insurer_status": "approved"}, {"history": []}, {"total": None}, {"lines": []},
                        {"history": good["history"] + [{"revision": 2, "total": 120000, "status": "needs_review"}]}):
            with self.subTest(field=list(changes)), self.assertRaises(ValueError):
                packet_bytes({**good, **changes}, originals)
        for field, value in (("sha256", "a"*64), ("quote", "Outside this policy"), ("page", 16)):
            bad = copy.deepcopy(good)
            bad["sources"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                packet_bytes(bad, originals)

    def test_two_page_reviewed_pdf_maps_insurer_fields_and_cites_current_exhibits(self):
        case = evaluate_estimate("Z002", exhibit("Z002", "revised-estimate.pdf"), "Current itemization.pdf")
        reviewed = review(case, 2, [{"revision": 1, "total": 82000, "status": "needs_itemization"}])
        originals = original_files("Z002", "revised-estimate.pdf")
        pdf = packet_bytes(reviewed, originals)
        self.assertEqual(pdf, packet_bytes(reviewed, dict(reversed(originals.items()))))
        reader = PdfReader(io.BytesIO(pdf))
        self.assertEqual(len(reader.pages), 2)
        request, report = [page.extract_text() for page in reader.pages]
        for value in ("Preauthorization / GOP request", "Revision 2", "Nok S.", "Insurer decision pending.",
                      "THB 82,000", "THB 52,000", "THB 30,000", "Alder Transit Cover", "DEMO-Z002"):
            self.assertIn(value, request)
        positions = [request.index(label) for label in ("Member reference", "Admission date", "Planned procedure",
                                                        "Estimated treatment cost")]
        self.assertEqual(positions, sorted(positions))
        for value in ("Gap report", "Current itemization.pdf, p. 1", "alder.pdf, p. 1", "plan.pdf, p. 1",
                      "AT-1", "AT-2", "AT-3", "Hospital services THB 52,000", "Operating team THB 30,000",
                      "The insurer must decide", "The three original PDFs are embedded in this packet"):
            self.assertIn(value, report)
        self.assertNotIn("estimate.pdf", report)

    def test_embeds_only_the_three_revision_originals_even_when_estimate_renamed(self):
        for case_id, actual, label, attachment_name in (
                ("Z001", "estimate.pdf", "estimate.pdf", "estimate.pdf"),
                ("Z002", "revised-estimate.pdf", "revised-estimate.pdf", "revised-estimate.pdf"),
                ("Z002", "revised-estimate.pdf", "plan.pdf", "estimate-plan.pdf"),
                ("Z002", "revised-estimate.pdf", "ALDER.pdf", "estimate-ALDER.pdf")):
            with self.subTest(case=case_id, filename=label):
                originals = original_files(case_id, actual)
                case = evaluate_estimate(case_id, originals["estimate"], label)
                pdf = PdfReader(io.BytesIO(packet_bytes(review(case), originals)))
                names = {"policy": "alder.pdf", "plan": "plan.pdf", "estimate": attachment_name}
                self.assertEqual(len(pdf.pages), 2)
                self.assertEqual(set(pdf.attachments), set(names.values()))
                for source in case["sources"]:
                    name = names[source["role"]]
                    self.assertEqual(list(pdf.attachments[name]), [originals[source["role"]]])
                    self.assertEqual(hashlib.sha256(pdf.attachments[name][0]).hexdigest(), source["sha256"])
                if case_id == "Z002":
                    self.assertNotEqual(pdf.attachments[attachment_name][0], exhibit(case_id, "estimate.pdf"))
                if label != attachment_name:
                    self.assertIn("Embedded as " + attachment_name, pdf.pages[1].extract_text())

    def test_rejects_missing_unrelated_and_mismatched_source_bytes(self):
        originals = original_files("Z002", "revised-estimate.pdf")
        case = review(evaluate_estimate("Z002", originals["estimate"]))
        for replacement in (
                {"plan": originals["plan"], "estimate": originals["estimate"]},
                {**originals, "other": exhibit("Z003", "plan.pdf")},
                {**originals, "policy": (FIXTURES / "policies/mango.pdf").read_bytes()},
                {**originals, "plan": exhibit("Z001", "plan.pdf")},
                {**originals, "estimate": exhibit("Z002", "estimate.pdf")}):
            with self.subTest(roles=list(replacement)), self.assertRaisesRegex(ValueError, "saved"):
                packet_bytes(case, replacement)


if __name__ == "__main__":
    unittest.main()
