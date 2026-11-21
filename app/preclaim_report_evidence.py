"""Inspect uploaded physician reports locally without inferring who signed them."""

import re
import unicodedata
import warnings
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

MAX_BYTES = 12 * 1024 * 1024
MAX_PAGES = 24
MAX_PIXELS = 16_000_000

# Only compare explicit labels. An unrecognized layout requires visual review.
LABELS = {
    "patient": "patient", "patient name": "patient", "member": "member", "member id": "member",
    "case": "case", "case id": "case", "hospital": "hospital", "planned procedure": "procedure",
    "admission date": "admission_date",
}
FIELD_LINE = re.compile(r"^\s*([^:\n]{1,32})\s*:\s*(.+?)\s*$")


def _normal(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _image_pdf(raw):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(raw), formats=("PNG", "JPEG")) as original:
            width, height = original.size
            if width * height > MAX_PIXELS or getattr(original, "n_frames", 1) != 1:
                raise ValueError("Use one JPEG or PNG photo of up to 16 megapixels.")
            media_type = Image.MIME[original.format]
            oriented = ImageOps.exif_transpose(original).convert("RGBA")
            background = Image.new("RGB", oriented.size, "white")
            background.paste(oriented, mask=oriented.getchannel("A"))
            scale = min(1.0, 842 / max(background.size))
            size = tuple(n * scale for n in background.size)
            out = BytesIO()
            doc = Canvas(out, pagesize=size, invariant=True)
            doc.drawImage(ImageReader(background), 0, 0, width=size[0], height=size[1])
            doc.showPage()
            doc.save()
            return out.getvalue(), media_type


def inspect_report(raw, *, case_id, values):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("Choose a PDF, PNG or JPEG report up to 12 MiB.")
    pdf_bytes, media_type = raw, "application/pdf"
    observed = set()
    conflicts = set()
    expected = {**values, "case": case_id}
    try:
        if not raw.lstrip().startswith(b"%PDF-"):
            pdf_bytes, media_type = _image_pdf(raw)
        reader = PdfReader(BytesIO(pdf_bytes))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PAGES:
            raise ValueError("Choose an unlocked PDF with 1 to 24 physical pages.")
        for page in reader.pages:
            text = page.extract_text() or ""
            if len(text) > 200_000:
                raise ValueError("A report page exceeds the text limit for review.")
            for line in text.splitlines():
                match = FIELD_LINE.fullmatch(line)
                if not match:
                    continue
                field = LABELS.get(_normal(match[1]))
                if field:
                    observed.add(field)
                    if _normal(match[2]) != _normal(expected[field]):
                        conflicts.add(field)
        count = len(reader.pages)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning,
            PyPdfError, RecursionError, UnicodeError, KeyError, IndexError, SyntaxError, OverflowError) as exc:
        raise ValueError("The report could not be opened reliably. Choose a readable PDF, PNG or JPEG.") from exc

    status = "manual_review"
    if conflicts:
        status = "mismatch"
    elif observed == set(LABELS.values()):
        status = "matched"
    return dict(pdf_bytes=pdf_bytes, media_type=media_type, page_count=count,
                identity_status=status, conflict_fields=sorted(conflicts))
