"""Field checks for the Thai and English AIA Thailand IPD forms printed May 2023."""

import re
from dataclasses import dataclass
from hashlib import sha256

from pypdf.errors import PdfReadError
from pypdf.generic import ContentStream

from .finance import AMOUNT, ReviewRequired, money
from .payer_pages import form_pages


@dataclass(frozen=True)
class Template:
    operations: int
    artwork: str
    signature: tuple[float, float, float, float]
    field: tuple[float, float, float, float]


# Fingerprints of the published blank PDF drawing instructions, never of a completed case.
# Rectangles are printed field boundaries in PDF points relative to the bottom left.
# The two editions have distinct Part A layouts and slightly shifted Part B baselines.
PART_A = {
    "en": Template(
        9325,
        "d53cb418117081d7f7e269cadaeed9f7f2fcbc4eb4e12ac3c9ed27c49747e045",
        (70, 384, 168, 399),
        (368, 564, 511, 578),
    ),
    "th": Template(
        7548,
        "e882c6493dcf35d93879926c8a2e6a368fda0a843950352cde3b01741d752037",
        (90, 404, 187, 419),
        (237, 563, 374, 576),
    ),
}
PART_B = {
    "en": Template(
        8423,
        "569932664c2097f123ad5caabd10ba9d0e8e4530008e66436c499c62a053c1f2",
        (110, 87, 230, 102),
        (376, 768, 433, 782),
    ),
    "th": Template(
        6906,
        "0b04e12810cd19296ab8960179dbd77e8e5be68d782d6aef92ca0d29c4c0ea1d",
        (110, 83, 230, 98),
        (376, 764, 433, 778),
    ),
}
SIGNATURE_OWNER = "Hospital claim coordinator"
# XObjects, path painting, inline images, shading, altered rendering modes, and unknown
# operations cannot establish a blank pen or stamp field from text alone.
TEXT_OVERLAY = set(b"q Q cm re W W* n BT ET Tf TL Tm Td TD T* Tj TJ Tc Tw Tz Ts rg RG g G k K".split())


def _template_overlay(page, template):
    try:
        if (
            page.rotation
            or abs(page.width - 595.32) > 0.2
            or abs(page.height - 841.92) > 0.2
            or tuple(map(float, page.page.cropbox)) != tuple(map(float, page.page.mediabox))
            or tuple(map(float, page.page.mediabox.lower_left)) != (0.0, 0.0)
            or float(page.page.get("/UserUnit", 1)) != 1
        ):
            return None
        content = page.page.get_contents()
        if content is None:
            return None
        ops = content.operations
        # An editor may wrap the original graphics state when appending another PDF.
        start = 0
        while start < len(ops) and ops[start][1] == b"q":
            start += 1
        end = start + template.operations
        if end > len(ops):
            return None
        base = ContentStream(None, None)
        base.operations = ops[start:end]
        if sha256(base.get_data()).hexdigest() != template.artwork:
            return None
        return ops[end:]
    except (PdfReadError, ValueError, TypeError, KeyError, IndexError, ArithmeticError, RecursionError):
        return None


def _values(page, bounds):
    # Some original field rules consist of dots plus the Thai printed currency unit.
    # Ignore only printed leaders/punctuation and the terminal unit within the amount box.
    values = []
    for run in page.within(*bounds):
        value = run.text.strip()
        if value and any(ch.isalnum() for ch in value) and not re.fullmatch(r"[. …:]*บาท", value):
            values.append(value)
    return values


def _text_only(page, overlay):
    return not page.annotations and all(op in TEXT_OVERLAY for _, op in overlay)


def _signature(page, template, overlay, part):
    field = "patient consent" if part == "A" else "physician certification"
    anchor = (
        "Physician’s signature"
        if part == "B"
        else ("Insured:" if "Insured:" in page.text else "พยานลงนามรับรอง")
    )
    values = _values(page, template.signature)
    # Any extra graphic/annotation anywhere on the page makes an empty text region
    # inconclusive. Typed signatures still require a person to verify execution.
    cite = page.ref("records", values[0] if len(values) == 1 else anchor)
    if not values and _text_only(page, overlay):
        return (
            "aia_missing_" + ("consent" if part == "A" else "certification"),
            f"The {field} field on AIA Part {part} has no readable mark. Inspect the original and obtain the missing signature if blank.",
            cite,
        )
    return None, None, cite


def _independent_bill(meta, originals):
    """Require an unambiguous encounter-bound bill before comparing its stated THB total."""
    pages = form_pages(originals, "bill")
    if not pages:
        return None, None
    encounter_ref = None
    totals = []
    for page in pages:
        # Blank or conflicting identifiers on any contributing page make this comparison unsafe.
        lines = [line.strip() for line in page.text.splitlines()]
        identity = {"Encounter": meta["encounter"], "Member": meta["member"], "Facility": meta["facility"]}
        if "Final itemized hospital bill" not in lines or any(
            [line for line in lines if line.startswith(key + ":")] != [f"{key}: {value}"]
            for key, value in identity.items()
        ):
            return None, None
        if encounter_ref is None:
            encounter_ref = page.ref("bill", "Encounter: " + meta["encounter"])
        for line in lines:
            if line.startswith("Final bill total:"):
                totals.append((line, page))
    if len(totals) != 1:
        return encounter_ref, None
    line, page = totals[0]
    match = re.fullmatch(rf"Final bill total: THB ({AMOUNT})", line)
    if not match:
        return encounter_ref, None
    try:
        return encounter_ref, (money(match[1]), page.ref("bill", line))
    except ReviewRequired:
        return encounter_ref, None


def screen_aia(meta, originals, review):
    records = form_pages(originals, "records")
    possible = [
        page
        for page in records
        if "Inpatient (IPD) Claim Form" in page.text
        and "Part A" in page.text
        and ("AIA Company Limited" in page.text or "บริษัท เอไอเอ" in page.text)
    ]
    certs = [page for page in records if "Part B" in page.text and "Medical certification" in page.text]
    if not possible:
        for page in certs:
            if any(_template_overlay(page, template) is not None for template in PART_B.values()):
                review.flag(
                    "aia_form_parts",
                    "Medical records",
                    "Locate the AIA Part A paired with this medical certification.",
                    page.ref("records", "Medical certification"),
                )
        return
    first = possible[0]
    header = first.ref("records", "Inpatient (IPD) Claim Form")
    if len(possible) != 1 or len(certs) != 1 or certs[0].number != first.number + 1:
        review.flag(
            "aia_form_parts",
            "Medical records",
            "Identify one complete AIA inpatient form with its matching Part B.",
            header,
        )
        return
    second = certs[0]
    edition = "en" if "AIA Company Limited" in first.text else "th"
    part_a, part_b = PART_A[edition], PART_B[edition]
    a, b = _template_overlay(first, part_a), _template_overlay(second, part_b)
    if a is None or b is None:
        review.flag(
            "aia_layout_review",
            "Medical records",
            "Inspect the AIA inpatient form edition and its filled fields against the original pages. The printed layout could not be verified.",
            header,
            second.ref("records", "Medical certification"),
        )
        return

    sig_refs = []
    for page, template, overlay, part in [(first, part_a, a, "A"), (second, part_b, b, "B")]:
        code, msg, ref = _signature(page, template, overlay, part)
        if code:
            review.flag(code, SIGNATURE_OWNER, msg, ref)
        sig_refs.append(ref)
    review.flag(
        "aia_signature_review",
        SIGNATURE_OWNER,
        "Compare both signature fields with the original AIA pages. A staff reviewer must verify any handwriting, stamp, typed mark or authorized signer.",
        *sig_refs,
        severity="review",
    )

    encounter_ref, bill = _independent_bill(meta, originals)
    ids = _values(second, part_b.field)
    if (
        _text_only(second, b)
        and len(ids) == 1
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./_-]{0,49}", ids[0])
        and encounter_ref
    ):
        if ids[0] != meta["encounter"]:
            review.flag(
                "aia_admission_mismatch",
                "Medical records",
                f"AIA Part B gives admission number {ids[0]}. The bill and case give {meta['encounter']}. Confirm the encounter or obtain a corrected form.",
                second.ref("records", ids[0]),
                encounter_ref,
            )
        else:
            review.checked(
                "aia_admission_matches",
                "The typed AIA admission number agrees with the case and its itemized bill.",
                second.ref("records", ids[0]),
                encounter_ref,
            )
    else:
        review.flag(
            "aia_admission_review",
            "Medical records",
            "Verify the admission number on AIA Part B against an independent bill for this encounter.",
            second.ref("records", "AN:"),
            encounter_ref,
            severity="review",
        )

    amounts = _values(first, part_a.field)
    label = "advanced the expenses" if edition == "en" else "ผ่านโรงพยาบาล"
    try:
        value = money(amounts[0]) if len(amounts) == 1 else None
    except ReviewRequired:
        value = None
    if not _text_only(first, a) or value is None or bill is None:
        review.flag(
            "aia_amount_review",
            "Hospital billing",
            "Verify the THB amount claimed or advanced on AIA Part A against a single final THB bill for the same encounter.",
            first.ref("records", label),
            severity="review",
        )
    elif bill[0] != value:
        review.flag(
            "aia_amount_mismatch",
            "Hospital billing",
            f"The amount claimed or advanced on AIA Part A is THB {value:,.2f}. The final bill states THB {bill[0]:,.2f}. Reconcile the difference or document a partial claim.",
            first.ref("records", amounts[0]),
            bill[1],
        )
    else:
        review.checked(
            "aia_amount_matches",
            "The typed THB amount claimed or advanced agrees with the stated final bill total.",
            first.ref("records", amounts[0]),
            bill[1],
        )
