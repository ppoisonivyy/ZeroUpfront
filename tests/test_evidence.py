"""Regression checks for quote provenance, page selection and conservative draft amounts."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from check_fixtures import Evidence, estimate_fields, precheck, read_live
from document_text import Document, Page, Transcript, contains_identifier, contains_quote, ocr_page, read_document
from policy_rag import Draft, Finding, Passage, Quote, verify


def doc(*pages):
    return Document(Path("sample.pdf"), "hash", list(pages))


class DocumentEvidenceTests(unittest.TestCase):
    def test_quote_matches_whitespace_and_thai_substring(self):
        self.assertTrue(contains_quote("AT-2 per\nnight\tlimit", "AT-2 per night"))
        self.assertTrue(contains_quote("ค่าห้องคืนแรก", "ค่าห้อง"))

    def test_partial_identifiers_and_amounts_cannot_be_cited(self):
        for source, quote in (("DEMO-Z0012", "DEMO-Z001"), ("THB 120,000", "THB 120"),
                              ("120,000", "000"), ("THB 22.50", "THB 22"), ("KM-4.10", "KM-4.1")):
            with self.subTest(quote=quote):
                self.assertFalse(contains_quote(source, quote))

    def test_expired_suffix_and_extended_edition_are_not_selected(self):
        self.assertFalse(contains_identifier("Edition KM-26C-OLD", "KM-26C"))
        self.assertFalse(contains_identifier("AT-2026.12", "AT-2026.1"))
        self.assertTrue(contains_identifier("AT-2026.1. Next section", "AT-2026.1"))

    def test_uses_authoritative_transcription_after_ocr(self):
        sample = doc(Page(2, "old charge 6,000", "new charge 3,000"))
        self.assertEqual(sample.locate("3,000")["method"], "ocr")
        with self.assertRaisesRegex(ValueError, "unverified"):
            sample.locate("6,000")

    def test_duplicate_physical_pages_require_disambiguation(self):
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            doc(Page(1, "Limit: THB 100", None), Page(2, "Limit: THB 100", None)).locate("THB 100")

    def test_unreadable_or_incomplete_ocr_stops_before_quote_verification(self):
        source = PdfWriter().add_blank_page(100, 100)
        for status, grade, text in (("incomplete", "complete", "100"), ("completed", "partial", "100"),
                                    ("completed", "unreadable", ""), ("completed", "complete", "  ")):
            with self.subTest(status=status, grade=grade):
                client = Mock()
                client.responses.parse.return_value = SimpleNamespace(
                    status=status, output_parsed=Transcript(legibility=grade, text=text))
                with self.assertRaisesRegex(ValueError, "incomplete Astra"):
                    ocr_page(source, 3, client)

    def test_selected_page_requires_valid_source_index(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/"source.pdf"
            writer = PdfWriter()
            writer.add_blank_page(150, 100)
            writer.write(path)
            with self.assertRaisesRegex(ValueError, "Physical page"):
                read_document(path, page_number=2)
            with self.assertRaisesRegex(ValueError, "needs Astra"):
                read_document(path)

    def test_encrypted_or_empty_pdf_yields_review_error(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/"source.pdf"
            writer = PdfWriter()
            writer.add_blank_page(100,100)
            writer.encrypt("synthetic")
            writer.write(path)
            with self.assertRaisesRegex(ValueError,"Encrypted PDF"):
                read_document(path)
            path.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "Cannot read PDF"):
                read_document(path)


class OriginalFormTests(unittest.TestCase):
    def test_revised_estimate_is_deterministically_itemized(self):
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "cases" / "Z002"
        plan = read_document(fixture/"plan.pdf")
        estimate = read_document(fixture/"revised-estimate.pdf")
        purpose = SimpleNamespace(purpose="other", supporting_quote="Repair of an accidental fracture.")
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=purpose)
        facts = read_live(client, plan, estimate)
        self.assertEqual((facts.total_thb, facts.itemized), (82000, True))

    def test_malformed_or_conflicting_evidence_is_unknown(self):
        cases = [
            ("Total estimated charges THB 7,000.50", (None, None)),
            ("Total estimated charges THB 12,34", (None, None)),
            ("Total estimated charges THB 100 Total estimated charges THB 110", (None,None)),
            ("Hospital services THB 80 Total estimated charges THB 100", (100, None)),
            ("Unknown service THB 100 Total estimated charges THB 100", (100,None)),
            ("Supplies THB 50 Supplies THB 50 Total estimated charges THB 100", (100,None)),
            ("Total estimated charges THB 100", (100,False)),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(estimate_fields(source), expected)
        facts = Evidence(total_thb=60_000, itemized=None, purpose="other")
        self.assertEqual(precheck({"version":"AT-2026.1", "limit_thb":180_000, "itemization_from_thb":50_000},
                                  facts), ("staff_review", None))

    def test_conflicting_documented_purpose_goes_to_staff(self):
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "cases" / "Z003"
        plan, estimate = (read_document(fixture/name) for name in ("plan.pdf", "estimate.pdf"))
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=SimpleNamespace(
            purpose="other", supporting_quote="Solely cosmetic appearance; no reconstructive indication."))
        facts = read_live(client,plan,estimate)
        self.assertEqual(facts.purpose, "unclear")
        self.assertEqual(precheck({"version":"MM-2026.1","limit_thb":220_000},facts), ("staff_review",None))


class DraftVerificationTests(unittest.TestCase):
    def setUp(self):
        self.evidence = [
            Passage("P1.1","policy.pdf","policyhash",1,"digital","KM-4.1 Room eligibility is per night."),
            Passage("C4.1","case.pdf","casehash",4,"astra_ocr","Night one room charge THB 7,000."),
        ]

    def draft(self, statement="Room overage requires review under KM-4.1.", amount=1000):
        return Draft(status="draft_for_staff", draft_request_thb=amount, findings=[
            Finding(statement=statement, quotes=[
                Quote(ref="P1.1",text="Room eligibility is per night."),
                Quote(ref="C4.1",text="room charge THB 7,000.")])])

    def test_supported_claim_with_both_roles(self):
        verify(self.draft(), self.evidence, {"draft_request_thb":1000})

    def test_unknown_clause_wrong_amount_or_unverified_financial_prose_stops_draft(self):
        for draft in (self.draft(statement="Paid under KM-4.9."), self.draft(amount=9000),
                      self.draft(statement="The draft request is 9999.")):
            with self.subTest(draft=draft):
                with self.assertRaises(ValueError):
                    verify(draft, self.evidence, {"draft_request_thb":1000})

    def test_unresolved_money_cannot_be_labeled_staff_ready(self):
        with self.assertRaisesRegex(ValueError, "unresolved"):
            verify(self.draft(amount=None), self.evidence, {"draft_request_thb":None})

    def test_partial_quote_duplicate_ref_or_wrong_role_stops_draft(self):
        draft = self.draft()
        duplicate = [*self.evidence, self.evidence[0]]
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            verify(draft, duplicate)
        draft.findings[0].quotes[-1].text = "room charge THB 7"
        with self.assertRaisesRegex(ValueError,"Unverified"):
            verify(draft,self.evidence)
        draft.findings[0].quotes.pop()
        with self.assertRaisesRegex(ValueError,"policy and case"):
            verify(draft,self.evidence)


if __name__ == "__main__":
    unittest.main()
