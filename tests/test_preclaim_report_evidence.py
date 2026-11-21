from io import BytesIO
import unittest

from PIL import Image
from pypdf import PdfReader

from app import preclaim_fixture as fixture
from app.preclaim_report_evidence import MAX_PAGES, inspect_report


class ReportEvidenceTests(unittest.TestCase):
    def inspect(self, raw):
        return inspect_report(raw, case_id=fixture.CASE, values=fixture.case_values("Canal Bridge"))

    def test_checks_all_labeled_identity_fields_and_all_pages(self):
        original = fixture.exhibits("Canal Bridge")
        raw = original["report"]
        found = self.inspect(raw)
        self.assertEqual((found["identity_status"], found["pdf_bytes"]), ("matched", raw))
        conflict = fixture.pdf("report", [("p1", ["Member: " + fixture.MEMBER]), ("p2", ["Member: SOMEONE-ELSE"])])
        found = self.inspect(conflict)
        self.assertEqual((found["identity_status"], found["conflict_fields"], found["page_count"]),
                         ("mismatch", ["member"], 2))

    def test_raster_preserves_orientation_and_requires_visual_review(self):
        for fmt in ("JPEG", "PNG"):
            with self.subTest(fmt=fmt):
                raw = BytesIO()
                image = Image.new("RGB", (75, 120), "white")
                exif = Image.Exif()
                exif[274] = 6  # Orient a portrait camera sensor capture for landscape display.
                image.save(raw, format=fmt, exif=exif)
                found = self.inspect(raw.getvalue())
                self.assertEqual((found["identity_status"], found["page_count"]), ("manual_review", 1))
                page = PdfReader(BytesIO(found["pdf_bytes"])).pages[0]
                self.assertGreater(page.mediabox.width, page.mediabox.height)

    def test_refuses_unusable_files_and_oversized_page_counts(self):
        for raw in (b"", b"broken", fixture.pdf("report", [("extra", [])] * (MAX_PAGES + 1))):
            with self.assertRaises(ValueError):
                self.inspect(raw)
