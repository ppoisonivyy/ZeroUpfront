"""Read positional text from this case's original PDFs for edition-specific screening."""
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from math import isfinite

from pypdf import PageObject, PdfReader
from pypdf.errors import PdfReadError

from .document_text import normalized


@dataclass(frozen=True)
class TextRun:
    text: str
    x: float
    y: float
    size: float


@dataclass(frozen=True)
class FormPage:
    number: int
    width: float
    height: float
    rotation: int
    text: str
    runs: tuple[TextRun, ...]
    annotations: bool
    page: PageObject

    def within(self, left: float, bottom: float, right: float, top: float) -> tuple[TextRun, ...]:
        return tuple(run for run in self.runs if left <= run.x <= right and bottom <= run.y <= top)

    def ref(self, role: str, quote: str) -> dict:
        snippet = normalized(quote)
        if snippet and snippet not in normalized(self.text):
            snippet = ""
        return {"role": role, "page": self.number, "quote": snippet, "method": "digital"}


def _positioned_pages(raw: bytes) -> tuple[FormPage, ...]:
    try:
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted or not 0 < len(reader.pages) <= 200:
            return ()
        result = []
        for number, page in enumerate(reader.pages, 1):
            runs = []

            def visit(text, cm, tm, _font, size):
                clean = text.strip()
                if not clean:
                    return
                # Transform the text origin through the current user-space matrix.
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                if isfinite(x) and isfinite(y) and isfinite(size):
                    runs.append(TextRun(clean, x, y, size))

            text = page.extract_text(visitor_text=visit) or ""
            result.append(FormPage(number, float(page.mediabox.width), float(page.mediabox.height),
                                   page.rotation, text, tuple(runs), bool(page.get("/Annots")), page))
        return tuple(result)
    except (PdfReadError, ValueError, KeyError, TypeError, IndexError, ArithmeticError, RecursionError):
        # The existing intake checks retain the original and its manual-review findings.
        return ()


class CaseOriginals(dict):
    """Share parsed geometry between readers within a single revision evaluation."""
    def __init__(self, originals: Mapping[str, bytes]):
        super().__init__(originals)
        self.pages_by_role: dict[str, tuple[FormPage, ...]] = {}


def form_pages(originals: Mapping[str, bytes], role: str) -> tuple[FormPage, ...]:
    raw = originals.get(role)
    if not raw:
        return ()
    if isinstance(originals, CaseOriginals):
        if role not in originals.pages_by_role:
            originals.pages_by_role[role] = _positioned_pages(raw)
        return originals.pages_by_role[role]
    return _positioned_pages(raw)
