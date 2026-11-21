"""Independently vary synthetic evidence on the pinned publisher specimens."""
from dataclasses import replace
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.generic import TextStringObject
from reportlab.pdfgen.canvas import Canvas

from payer_forms_th import packet as aia
from payer_forms_us import specimens as us


def output(writer):
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def overlay(page, draw):
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(float(page.mediabox.width), float(page.mediabox.height)), invariant=1)
    canvas.setFont("Helvetica", 8)
    draw(canvas)
    canvas.save()
    page.merge_page(PdfReader(BytesIO(stream.getvalue())).pages[0])


def edit_text(page, change):
    """Replace printed text operators, removing previous field values from the text layer."""
    content = page.get_contents()
    position = None
    for operands, op in content.operations:
        if op == b"Tm":
            position = tuple(float(value) for value in operands[-2:])
        if op == b"Tj" and position is not None:
            new = change(*position, str(operands[0]))
            if new is not None:
                operands[0] = TextStringObject(new)
    page.replace_contents(content)


def thai(spec):
    language = spec["family"].split("-")[1]
    name = spec["id"]
    meta = {**aia.META, "member": spec["member"], "encounter": spec["encounter"]}
    with patch.dict(aia.META, meta):
        hospital = aia.exhibits()
        patient = aia.patient(language, "clean")
        doctor = aia.certificate(language, "certification" if name == "aia-th-clinician" else "clean")
    pages = []
    if language == "th":
        cover = [mark for mark in aia.cover() if mark[1] != 158]
        cover.extend((175 + i * 20.7, 158, digit) for i, digit in enumerate(meta["member"].removeprefix("T-")))
        pages.append(cover)
    pages.extend([patient, doctor])
    writer = PdfWriter()
    originals = PdfReader(BytesIO(aia.verified_form_bytes(language)))
    for original, marks in zip(originals.pages, pages, strict=True):
        page = writer.add_page(original)
        scale = float(page.mediabox.height) / 1024

        def draw(c):
            height = float(page.mediabox.height)
            c.setFont("Helvetica-Bold", 7)
            c.drawCentredString(float(page.mediabox.width) / 2, height - 8, "SYNTHETIC TEST / NOT FOR FILING")
            for x, y, text in marks:
                if text == "TEST PATIENT MARK" and name == "aia-en-ink":
                    # An arbitrary looping pen stroke. The adjacent date stays printed.
                    x, y = x * scale, height - y * scale
                    c.setLineWidth(1.2)
                    c.bezier(x, y, x + 10, y + 9, x + 3, y - 4, x + 15, y + 3)
                    c.bezier(x + 15, y + 3, x + 11, y + 8, x + 19, y - 3, x + 28, y + 4)
                    continue
                if text == "TEST PATIENT MARK":
                    text = "N. Sample"
                elif text == "TEST CLINICIAN MARK":
                    text = "Dr P. Example"
                elif text == "87,500.00" and name == "aia-th-cents":
                    text = "87,513.42"
                elif marks is doctor and text == spec["encounter"] and name == "aia-en-id-decoy":
                    text = "AN-HO825"
                is_thai = any("\u0e00" <= char <= "\u0e7f" for char in text)
                c.setFont("NotoThaiQA" if is_thai else "Helvetica", 7)
                c.drawString(x * scale, height - y * scale, text, shaping=is_thai)
        overlay(page, draw)
    hospital["records"] = aia.joined(output(writer), hospital["records"])
    return meta, hospital


def cms(spec, blanks):
    name = spec["id"]
    meta = {**us.US, "member": spec["member"], "encounter": spec["encounter"]}
    rows = [*us.US_ROWS[:-1], replace(us.US_ROWS[-1], price=Decimal("2385.67"))]
    assert sum(row.amount for row in rows) == Decimal("12345.67")
    documents = us.supporting(meta, rows, False)
    writer = PdfWriter()
    writer.append(BytesIO(us.institutional(*blanks[:2], "aligned")))
    scale = 792 / 950

    def change(x, y, old):
        if old == us.US["encounter"]:
            return meta["encounter"]
        if old == us.US["member"]:
            return "" if name == "cms-member-missing" else "HM0130891" if name == "cms-member" else meta["member"]
        if old == "0111" and name == "cms-reference-present":
            return "0117"
        if old == "1325":
            return "2385"
        if old == "11285":
            return "12345"
        if old == "00" and abs(x - 570 * scale) < .01:
            if abs(y - (792 - 576 * scale)) < .01:
                return "78" if name == "cms-cents" else "67"
            if abs(y - (792 - (293 + 4 * 12.88) * scale)) < .01:
                return "67"
        return None

    edit_text(writer.pages[0], change)
    if name == "cms-reference-present":
        # FL64 row A below the printed "Document Control Number" label on the pinned sheet.
        overlay(writer.pages[0], lambda c: c.drawString(248, 204, "83944167021"))
    documents["bill"] = us.joined(output(writer), documents["bill"])
    return meta, documents


def fep(spec, blanks):
    name = spec["id"]
    meta = {**us.TH, "member": spec["member"], "encounter": spec["encounter"]}
    documents = us.supporting(meta, us.TH_ROWS, True)
    documents["letter"] = us.rendered([("Fictional prior admission correspondence", [
        f"Case {meta['encounter']}, member {meta['member']}, facility {meta['facility']}.",
        "Prior admission record for the stated inpatient surgery. The payer reviews the final charges.",
    ])])
    baseline = {"fep-member-back-decoy": "member_payee", "fep-other-signature": "assignment_unsigned"}.get(name, "aligned")
    writer = PdfWriter()
    writer.append(BytesIO(us.overseas(blanks[2], baseline)))
    ids_seen = []

    def change(x, y, old):
        if old.isdigit() and len(old) == 1 and 454 <= x <= 602 and 704 <= y <= 730:
            ids_seen.append(old)
            return meta["member"][len(ids_seen)]
        if old == us.TH["facility"] and name == "fep-wrong-provider":
            return "Saffron Bay Rehabilitation"
        if old == "THB 158,050.00" and name == "fep-cents":
            return "THB 158,050.07"
        if old == "SYNTHETIC TEST ATTESTATION":
            return "R. Sample" if y > 80 else "L. Example"
        return None

    edit_text(writer.pages[0], change)
    assert "".join(ids_seen) == "00000042"
    if name in {"fep-member-back-decoy", "fep-other-signature"}:
        overlay(writer.pages[1], lambda c: c.drawString(68, 47, "Training note: Lantern Quay Hospital / Signed R. Sample"))
    documents["records"] = us.joined(output(writer), documents["records"])
    return meta, documents
