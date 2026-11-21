"""AIA field reconciliation with independent values and unsupported marks/layout variants."""

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from unittest import TestCase
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream
from reportlab.pdfgen.canvas import Canvas

from app import payer_aia
from app.discharge_claim import Review
from app.payer_pages import CaseOriginals


def pdf(lines, stroke=False):
    buf = BytesIO()
    page = Canvas(buf, pagesize=(595.32, 841.92), invariant=1)
    for x, y, text in lines:
        page.drawString(x, y, text)
    if stroke:
        page.line(72, 388, 109, 395)
    page.showPage()
    page.save()
    return buf.getvalue()


def join_parts(*parts):
    writer = PdfWriter()
    for part in parts:
        writer.append(BytesIO(part))
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def merged(blank, added):
    writer = PdfWriter()
    writer.add_page(PdfReader(BytesIO(blank)).pages[0]).merge_page(PdfReader(BytesIO(added)).pages[0])
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def template(raw, rectangle):
    ops = PdfReader(BytesIO(raw)).pages[0].get_contents().operations
    stream = ContentStream(None, None)
    stream.operations = ops
    return replace(rectangle, operations=len(ops), artwork=sha256(stream.get_data()).hexdigest())


class AIAClaimFields(TestCase):
    def setUp(self):
        # Use original tiny, locally authored canvases to exercise the fixed-region/edition
        # contract in CI. The companion benchmark exercises both actual pinned AIA originals.
        self.a = pdf(
            [
                (30, 810, "AIA Company Limited"),
                (30, 790, "Inpatient (IPD) Claim Form"),
                (30, 760, "Part A"),
                (30, 568, "advanced the expenses"),
                (39, 387, "Insured:"),
            ]
        )
        self.b = pdf(
            [
                (30, 810, "Part B"),
                (30, 790, "Medical certification"),
                (335, 770, "AN:"),
                (28, 90, "Physician’s signature"),
            ]
        )
        self.enterContext(patch.dict(payer_aia.PART_A, en=template(self.a, payer_aia.PART_A["en"])))
        self.enterContext(patch.dict(payer_aia.PART_B, en=template(self.b, payer_aia.PART_B["en"])))
        self.meta = {"member": "M202A", "encounter": "BKK-5800", "facility": "Hospital 8"}
        self.lines = [
            (20, 680, "Member: M202A"),
            (20, 660, "Encounter: BKK-5800"),
            (20, 640, "Final bill total: THB 8,142.75"),
        ]
        self.patient = [(372, 571, "8142.75"), (77, 389, "Patient example")]
        self.physician = [(380, 774, "BKK-5800"), (115, 93, "Dr Sample")]

    def evaluate(self, a=None, b=None, bill=None, graphics=False, extra=None):
        part_a = merged(self.a, pdf(self.patient if a is None else a, graphics))
        part_b = merged(self.b, pdf(self.physician if b is None else b))
        files = CaseOriginals(
            {
                "records": join_parts(
                    pdf([(30, 700, "Hospital file")]), part_a, part_b, *([extra] if extra else [])
                ),
                "bill": pdf(
                    [
                        (20, 740, "Final itemized hospital bill"),
                        (20, 720, "Facility: Hospital 8"),
                        *(self.lines if bill is None else bill),
                    ]
                ),
            }
        )
        review = Review()
        payer_aia.screen_aia(self.meta, files, review)
        for finding in review.findings.values():
            for source in finding["sources"]:
                self.assertTrue(source["quote"], (finding["code"], source))
        return review

    def test_different_identifiers_and_cent_amounts_with_independent_physical_sources(self):
        review = self.evaluate(
            a=[(372, 571, "8,142.74"), (77, 389, "Parent mark")],
            b=[(380, 774, "BKK-5800A"), (115, 93, "Clinician mark")],
        )
        for code, ref in [
            ("aia_admission_mismatch", ("records", 3, "BKK-5800A")),
            ("aia_amount_mismatch", ("records", 2, "8,142.74")),
        ]:
            locations = [(s["role"], s["page"], s["quote"]) for s in review.findings[code]["sources"]]
            self.assertEqual(locations[0], ref)
            self.assertEqual(locations[1][:2], ("bill", 1))
        self.assertIn("aia_signature_review", review.findings)

    def test_aligned_values_still_require_human_signature_verification(self):
        result = self.evaluate()
        self.assertEqual(set(result.findings), {"aia_signature_review"})
        self.assertEqual({c["code"] for c in result.checks}, {"aia_admission_matches", "aia_amount_matches"})

    def test_adjacent_date_or_license_does_not_supply_a_signature(self):
        result = self.evaluate(
            a=[self.patient[0], (195, 389, "2026-05-02")], b=[self.physician[0], (530, 93, "987654")]
        )
        self.assertIn("aia_missing_consent", result.findings)
        self.assertIn("aia_missing_certification", result.findings)

    def test_vector_mark_is_indeterminate_instead_of_declared_missing(self):
        result = self.evaluate(a=[self.patient[0]], graphics=True)
        self.assertNotIn("aia_missing_consent", result.findings)
        self.assertIn("aia_signature_review", result.findings)
        self.assertIn("aia_amount_review", result.findings)

    def test_wrong_member_foreign_currency_duplicate_totals_or_duplicate_field_values(self):
        for lines in [
            self.lines[1:],
            self.lines + [self.lines[-1]],
            self.lines[:2] + [(20, 640, "Final bill total: USD 999.25")],
        ]:
            with self.subTest(lines=lines):
                review = self.evaluate(bill=lines)
                self.assertIn("aia_amount_review", review.findings)
                self.assertNotIn("aia_amount_mismatch", review.findings)
        competing = self.evaluate(
            b=self.physician + [(381, 775, "AN-NEW")], a=self.patient + [(463, 570, "999")]
        )
        self.assertIn("aia_amount_review", competing.findings)
        self.assertIn("aia_admission_review", competing.findings)
        self.assertNotIn("aia_admission_mismatch", competing.findings)

    def test_duplicate_certificate_or_changed_edition_suspends_field_matching(self):
        self.assertEqual(set(self.evaluate(extra=self.b).findings), {"aia_form_parts"})
        self.a = pdf(
            [
                (30, 810, "AIA Company Limited"),
                (30, 790, "Inpatient (IPD) Claim Form"),
                (30, 760, "Part A"),
                (30, 610, "Revision with differently positioned fields"),
            ]
        )
        self.assertEqual(set(self.evaluate().findings), {"aia_layout_review"})
