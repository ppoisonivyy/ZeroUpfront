"""Conservative administrative checks on the US institutional and FEP overseas paper forms."""

import re
from decimal import Decimal
from hashlib import sha256

from pypdf import Transformation
from pypdf.errors import PdfReadError

from .document_text import contains_identifier, normalized
from .payer_pages import form_pages

# Fingerprints of the PAINTED paths and image placements of the publisher front pages.
# Editable values and printing-tool wrappers are deliberately outside these fingerprints.
# Coordinates below are measured in PDF points against the blank form editions.
ARTWORK = {
    "cms": "91421aca568625cd715855f41938a549351398d6da3f5d6fa3a0474613ead509",
    "fep": "7af90d3d3311376b34853165b877a024ba3be309b8a27ed98be1d0a966185117",
}
LABELS = {
    "cms": (
        (43, 734, "TYPE OF BILL"),
        (44, 560, "47 TOTAL CHARGES"),
        (243, 217, "64 DOCUMENT CONTROL NUMBER"),
        (42, 58, "UB-04 CMS-1450"),
    ),
    "fep": (
        (325, 747, "OVERSEAS MEDICAL CLAIM FORM"),
        (16, 159, "5D. AUTHORIZATION FOR ASSIGNMENT"),
        (16, 269, "5C. COMPLETE FOR ELECTRONIC FUND TRANSFER"),
        (431, 23, "CUT0159-1S"),
    ),
}
PATH = {b"m", b"l", b"c", b"v", b"y", b"re", b"h"}
PAINT = {b"S", b"s", b"B", b"B*", b"b", b"b*", b"f", b"F", b"f*"}
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d{1,12})(?:\.\d{2})?"
MONEY = re.compile(rf"(USD|THB|EUR)\s+({NUMBER})", re.IGNORECASE)
INVOICE_TOTAL = re.compile(
    rf"^\s*(?:grand total|final bill total|invoice total|total charges)\s*[:=]?\s*(USD|THB|EUR)\s+({NUMBER})(?=\s*\.?\s*$|\.\s+(?:closed|signed|prepared) by\b)",
    re.IGNORECASE,
)
DISPOSITION = re.compile(
    r"^(?:discharge\s+)?disposition\s*[:=]\s*(?:discharged\s+)?(home(?:/self[- ]care)?|(?:transferred|transfer)\s+to\s+(?:an?\s+)?(?:short[- ]term|acute[- ]care)\s+(?:general\s+)?hospital)(?=\s*[.;]|\s*$)",
    re.IGNORECASE,
)


def _original_artwork(page, family):
    """Abstain on additional graphic marks, widgets, text clipping or unfamiliar placements."""
    if (
        page.rotation
        or page.width != 612
        or page.height != 792
        or page.annotations
        or tuple(page.page.cropbox) != (0, 0, 612, 792)
        or page.page.user_unit != 1
    ):
        return False
    for x, y, needle in LABELS[family]:
        if not any(
            needle in normalized(run.text)
            for run in page.within(x - 2, y - 2, x + 2, y + 2)
        ):
            return False
    digest = sha256()
    cm, stack, path = Transformation(), [], []
    try:
        for args, op in page.page.get_contents().operations:
            if op == b"q":
                stack.append(cm)
            elif op == b"Q":
                cm = stack.pop()
            elif op == b"cm":
                cm = Transformation(tuple(float(v) for v in args)).transform(cm)
            elif op in PATH:
                path.append(
                    (
                        op,
                        tuple(round(float(v), 3) for v in args),
                        tuple(round(float(v), 3) for v in cm.ctm),
                    )
                )
            elif op in PAINT:
                digest.update(repr((path, op)).encode())
                path = []
            elif op == b"n":
                path = []
            elif op == b"Do":
                image = page.page["/Resources"]["/XObject"][args[0]]
                if (
                    family != "fep"
                    or image.get("/Subtype") != "/Image"
                    or (image.get("/Width"), image.get("/Height")) != (273, 67)
                    or sha256(image.get_data()).hexdigest()
                    != "1b46e46ca4398516c91dff073761365e716cd49f3c7cf3c9221142351f8656d1"
                ):
                    return False
                digest.update(
                    repr(
                        (
                            op,
                            tuple(map(str, args)),
                            tuple(round(float(v), 3) for v in cm.ctm),
                        )
                    ).encode()
                )
            elif op in {b"sh", b"INLINE IMAGE"} or (
                op == b"Tr" and float(args[0]) != 0
            ):
                return False
    except (ArithmeticError, ValueError, IndexError, KeyError, TypeError, PdfReadError):
        return False
    return not stack and digest.hexdigest() == ARTWORK[family]


def _registered_family(page):
    text = normalized(page.text)
    if "UB-04 CMS-1450" in text and "DOCUMENT CONTROL NUMBER" in text:
        return "cms"
    if (
        "OVERSEAS MEDICAL CLAIM FORM" in text
        and "5D. AUTHORIZATION FOR ASSIGNMENT" in text
    ):
        return "fep"
    return None


def _single(page, bounds):
    runs = page.within(*bounds)
    return normalized(runs[0].text) if len(runs) == 1 else ""


def _money(text):
    match = MONEY.fullmatch(text)
    return (match[1].upper(), Decimal(match[2].replace(",", ""))) if match else None


def _linked(page, meta):
    return all(
        contains_identifier(normalized(page.text), meta[key])
        for key in ("member", "encounter")
    )


def _compare_total(family, meta, originals, page, role, actual, quotes, review):
    """Compare stated amounts only when the second physical page identifies the same case and currency."""
    form_refs = [page.ref(role, q) for q in quotes]
    totals = []
    for invoice in form_pages(originals, "bill"):
        if (role == "bill" and invoice.number == page.number) or not _linked(
            invoice, meta
        ):
            continue
        if not re.search(r"\bitemi[sz]ed\b", invoice.text, re.IGNORECASE):
            continue
        for line in invoice.text.splitlines():
            for match in INVOICE_TOTAL.finditer(line):
                totals.append(
                    (
                        (match[1].upper(), Decimal(match[2].replace(",", ""))),
                        invoice.ref("bill", match[0]),
                    )
                )
    result = {entry for entry, _ in totals}
    if not actual or len(result) != 1:
        review.flag(
            family + "_amount_review",
            "Hospital billing",
            "Compare the currency and total on the form with a single identifiable itemized invoice.",
            *form_refs,
            *(ref for _, ref in totals[:2]),
            severity="review",
        )
        return
    expected = next(iter(result))
    if actual[0] != expected[0]:
        review.flag(
            family + "_currency_review",
            "Hospital billing",
            "The form and itemized invoice use different currencies. Verify the documented conversion before comparing amounts.",
            *form_refs,
            totals[0][1],
        )
    elif actual[1] != expected[1]:
        section = "CMS-1450 FL 47" if family == "cms" else "FEP section 4"
        review.flag(
            family + "_total_mismatch",
            "Hospital billing",
            f"{section} shows {actual[0]} {actual[1]:,.2f}. The linked itemized invoice shows {expected[0]} {expected[1]:,.2f}. Reconcile the difference.",
            *form_refs,
            totals[0][1],
        )


def _cms(meta, originals, page, role, review):
    # FL 50 A, 60 A and 64 A follow the primary payer row. Secondary rows are distinct.
    payer = _single(page, (42, 286, 190, 299))
    if not payer or normalized(meta["insurer"]).casefold() != payer.casefold():
        review.flag(
            "cms_payer_row_review",
            "Payer liaison",
            "Match the encounter payer to the applicable CMS-1450 payer row before checking its identifiers.",
            page.ref(role, "50 PAYER NAME"),
            severity="review",
        )
        return
    member = _single(page, (230, 242, 355, 254))
    if (
        member
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{2,47}", member)
        and member.casefold() != meta["member"].casefold()
    ):
        review.flag(
            "cms_member_mismatch",
            "Hospital registration",
            f"CMS-1450 FL 60A shows {member}. The encounter lists {meta['member']}. Verify the insured identifier for the primary payer.",
            page.ref(role, member),
        )
        return
    if not member or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{2,47}", member):
        review.flag(
            "cms_member_review",
            "Hospital registration",
            "Confirm the primary insured identifier in FL 60A before comparing this claim with the encounter.",
            page.ref(role, "UNIQUE ID"),
            severity="review",
        )
        return
    bill_type = _single(page, (537, 715, 570, 728))
    dcn = page.within(242, 199, 406, 211)
    if (
        re.fullmatch(r"0?\d{2}[78]", bill_type)
        and "medicare" in payer.casefold()
        and not dcn
    ):
        review.flag(
            "cms_original_claim_reference",
            "Hospital billing",
            f"CMS-1450 FL 4 gives bill type {bill_type}. Supply or confirm the prior Medicare document control number in FL 64A before submitting the adjustment.",
            page.ref(role, bill_type),
            page.ref(role, "64 DOCUMENT CONTROL NUMBER"),
        )
    status = _single(page, (234.5, 651, 253, 663))
    narratives = []
    for summary in form_pages(originals, "summary"):
        if not _linked(summary, meta):
            continue
        for line in summary.text.splitlines():
            match = DISPOSITION.search(line.strip())
            if match:
                narratives.append(
                    (
                        "01" if match[1].lower().startswith("home") else "02",
                        summary.ref("summary", match[0]),
                    )
                )
    if (
        status in {"01", "02"}
        and narratives
        and all(code != status for code, _ in narratives)
    ):
        meaning = (
            "home or self-care"
            if status == "01"
            else "transfer to a short-term hospital"
        )
        review.flag(
            "cms_disposition_mismatch",
            "Clinical team",
            f"CMS-1450 FL 17 shows {status} ({meaning}). The linked discharge disposition differs. Confirm where the patient went.",
            page.ref(role, "17 STAT"),
            page.ref(role, status),
            narratives[0][1],
        )
    dollars = _single(page, (425, 307, 473, 318))
    cents = _single(page, (474, 307, 490, 318))
    amount = None
    if re.fullmatch(r"\d{1,10}", dollars) and re.fullmatch(r"\d{2}", cents):
        amount = _money("USD " + dollars + "." + cents)
    elif not cents and re.fullmatch(rf"{NUMBER}", dollars) and "." in dollars:
        amount = _money("USD " + dollars)
    if re.fullmatch(r"0*1", _single(page, (42, 307, 70, 318))):
        _compare_total(
            "cms",
            meta,
            originals,
            page,
            role,
            amount,
            [q for q in (dollars, cents) if q] or ["47 TOTAL CHARGES"],
            review,
        )


def _fep_member(page, member):
    cells = sorted(page.within(454, 705, 602, 726), key=lambda r: r.x)
    if len(cells) == 8 and all(re.fullmatch(r"\d", r.text) for r in cells):
        # The printed R prefix occupies the preceding box. Each digit must occupy a distinct cell.
        if any(
            not (454 + i * 18.4 <= r.x <= 454 + (i + 1) * 18.4)
            for i, r in enumerate(cells)
        ):
            return False
        value = "".join(r.text for r in cells)
    elif len(cells) == 1 and re.fullmatch(r"\d{8}", cells[0].text):
        value = cells[0].text
    else:
        return False
    return ("R" + value).casefold() == member.casefold()


def _facility_source(meta, originals):
    expected = normalized(meta["facility"]).casefold()
    for role in ("summary", "bill"):
        for source in form_pages(originals, role):
            if not _linked(source, meta):
                continue
            for raw in source.text.splitlines():
                line = normalized(raw)
                if line.casefold() == expected or re.search(
                    r"(?:^|[,|]\s*)facility(?:\s*:\s*|\s+)"
                    + re.escape(expected)
                    + r"(?:[.,|]|$)",
                    line.casefold(),
                ):
                    return source.ref(role, line)
    return None


def _fep(meta, originals, page, role, review):
    payer = normalized(meta["insurer"]).casefold()
    if not (
        "fep" in payer.split() or "federal employee program" in payer
    ) or not _fep_member(page, meta["member"]):
        review.flag(
            "fep_member_payer_review",
            "Hospital registration",
            "Match the Federal Employee Program payer and printed member identifier to the encounter before comparing or routing this form.",
            page.ref(role, "IDENTIFICATION NUMBER"),
            severity="review",
        )
        return
    general = _single(page, (23, 27, 274, 40))
    if not general or general.casefold() in {
        "n/a",
        "pending",
        "unsigned",
        "none",
        "x",
        "-",
    }:
        review.flag(
            "fep_general_signature",
            "Payer liaison",
            "Verify the separate general signature on this paper claim. An assignment entry in section 5D cannot supply the general claim attestation.",
            page.ref(role, "Signature of Contract Holder or Patient"),
            severity="review",
        )
    printed = _single(page, (369, 346, 447, 362))
    _compare_total(
        "fep",
        meta,
        originals,
        page,
        role,
        _money(printed),
        [printed or "TOTAL CHARGES"],
        review,
    )
    # Publisher widget rectangles on the printed 08/23 form, in PDF points.
    currency_boxes = [(359, 306, 374, 321), (438, 306, 454, 321)]
    method_boxes = [(359, 278, 374, 294), (438, 278, 454, 294)]

    def marked(boxes):
        selected = []
        for i, box in enumerate(boxes):
            marks = page.within(*box)
            if marks and (
                len(marks) != 1 or marks[0].text.strip().upper() not in {"X", "✓", "✔"}
            ):
                return None
            if marks:
                selected.append(i)
        return selected

    currency, method = marked(currency_boxes), marked(method_boxes)
    provider = _single(page, (79, 133, 316, 147))
    sig = _single(page, (160, 86, 361, 99))
    date = _single(page, (394, 86, 464, 99))
    ref = page.ref(role, "5D. AUTHORIZATION FOR ASSIGNMENT OF BENEFITS")
    # Detect evidence of any 5D field, including an address without a named provider.
    assignment_boxes = [
        (79, 133, 316, 147),
        (118, 116, 529, 131),
        (42, 102, 213, 114.5),
        (243, 102, 315, 114.5),
        (360, 102, 423, 114.5),
        (474, 101, 595, 114),
        (160, 86, 361, 99),
        (394, 86, 464, 99),
    ]
    assignment = any(page.within(*box) for box in assignment_boxes)
    different_provider = bool(
        provider and provider.casefold() != normalized(meta["facility"]).casefold()
    )
    if different_provider:
        hospital = _facility_source(meta, originals)
        if hospital:
            review.flag(
                "fep_assignment_provider",
                "Payer liaison",
                f"Section 5D names {provider} as the payment recipient. The treating facility on this encounter is {meta['facility']}. Verify the intended payee and any documented alternative payment arrangement.",
                page.ref(role, provider),
                hospital,
                severity="review",
            )
        else:
            review.flag(
                "fep_assignment_provider_review",
                "Payer liaison",
                f"Section 5D names {provider}. The intake lists {meta['facility']}. Corroborate the treating facility from the original encounter documents and confirm the intended payee.",
                page.ref(role, provider),
                severity="review",
            )
    if (
        currency is None
        or method is None
        or len(currency) > 1
        or len(method) > 1
        or (assignment and (currency or method))
    ):
        review.flag(
            "fep_payee_review",
            "Payer liaison",
            "Confirm the FEP member identifier and a single payment route. Compare the member elections with the assignment to provider in section 5D.",
            ref,
            page.ref(role, "5B. SELECT TYPE OF REIMBURSEMENT"),
            severity="review",
        )
    elif provider and not page.within(160, 86, 361, 99):
        review.flag(
            "fep_assignment_signature",
            "Payer liaison",
            f"Section 5D names {provider} but has no readable assignment signature in its own field. Check the original mark or obtain a completed assignment. The separate general claim signature serves a different purpose.",
            ref,
            page.ref(role, provider),
            page.ref(role, "Signature of Contract Holder or Spouse"),
        )
    elif len(currency) == 1 and len(method) == 1 and not assignment:
        choice = ("check", "electronic transfer")[method[0]]
        review.checked(
            "fep_member_reimbursement",
            f"FEP sections 5A and 5B select member reimbursement by {choice}. Route the packet for member reimbursement and confirm the payment details.",
            page.ref(role, "5A. CONTRACT HOLDER REIMBURSEMENT INFORMATION"),
            page.ref(role, "5B. SELECT TYPE OF REIMBURSEMENT"),
        )
    elif (
        provider
        and sig
        and sig.casefold() not in {"n/a", "pending", "unsigned", "none", "x", "-"}
        and date
        and provider.casefold() == meta["facility"].casefold()
    ):
        review.checked(
            "fep_provider_assignment",
            "FEP section 5D names the hospital and contains text in its signature and date boxes. Staff must verify the assignment and signer before routing.",
            ref,
            page.ref(role, provider),
        )
    elif not different_provider:
        review.flag(
            "fep_payee_review",
            "Payer liaison",
            "Confirm the FEP payee designation, provider identity and assignment details against the original form.",
            ref,
            severity="review",
        )


def screen_us(meta, originals, review):
    candidates = [
        (family, role, page)
        for role in ("bill", "records")
        for page in form_pages(originals, role)
        if (family := _registered_family(page))
    ]
    if len(candidates) > 1:
        family = candidates[0][0]
        review.flag(
            family + "_form_version_review",
            "Hospital billing",
            "Several institutional or overseas claim forms are present. Identify the active form and payment route.",
            *(
                page.ref(role, LABELS[kind][0][2])
                for kind, role, page in candidates[:6]
            ),
            severity="review",
        )
        return
    for family, role, page in candidates:
        if not _original_artwork(page, family):
            review.flag(
                family + "_form_visual_review",
                "Hospital billing",
                "Verify the populated fields on the original. This form has different geometry, artwork or interactive fields.",
                page.ref(role, LABELS[family][0][2]),
                severity="review",
            )
            continue
        if family == "cms":
            _cms(meta, originals, page, role, review)
        else:
            _fep(meta, originals, page, role, review)
