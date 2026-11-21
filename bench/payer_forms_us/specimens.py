"""Generate fictional evidence on two official US paper form specimens, using only local files."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from textwrap import wrap
from urllib.request import urlopen
from zipfile import ZipFile

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

CMS_URL = "https://www.cms.gov/regulations-and-guidance/legislation/paperworkreductionactof1995/downloads/cms-1450.zip"
FEP_URL = "https://www.fepblue.org/-/media/PDFs/Forms/2024/Overseas-Medical-Claim-Form---GeoBlue-06082023.pdf"
PINNED = {
    "official.zip": (
        CMS_URL,
        "177d4eec7b6e0719da9aa52405b6271567b0af9c05d11a4250edbb863523cf84",
    ),
    "fep.pdf": (
        FEP_URL,
        "04102af2e92d179cf5eeec9acc6437af1a925a4183fdf8e647f80385242542cc",
    ),
}


def get_blanks(cache: Path):
    cache.mkdir(parents=True, exist_ok=True)
    for filename, (url, expected) in PINNED.items():
        target = cache / filename
        if not target.exists():
            with urlopen(url, timeout=60) as response:
                content = response.read()
            if sha256(content).hexdigest() != expected:
                raise ValueError(
                    f"Publisher changed {filename}. Review the new edition before using this overlay."
                )
            target.write_bytes(content)
        if sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Source fingerprint differs for {filename}.")
    with ZipFile(cache / "official.zip") as package:
        front = package.read("CMS-1450 UB04-front.pdf")
        back = package.read("CMS-1450 UB04 - Back.pdf")
    return front, back, (cache / "fep.pdf").read_bytes()


@dataclass(frozen=True)
class Charge:
    ref: str
    day: str
    label: str
    units: int
    price: int
    evidence: str

    @property
    def amount(self):
        return self.units * self.price


US = {
    "member": "TEST-MBI-0042",
    "encounter": "US-H-042",
    "facility": "Juniper Teaching Hospital",
    "insurer": "Medicare Part A",
    "procedure": "Inpatient medical management of pneumonia",
    "admission_date": "2026-10-31",
    "discharge_date": "2026-11-03",
    "as_of": "2026-11-04",
}
TH = {
    "member": "R00000042",
    "encounter": "TH-IP-077",
    "facility": "Lantern Quay Hospital",
    "insurer": "BCBS Federal Employee Program",
    "procedure": "Inpatient distal radius fracture fixation",
    "admission_date": "2026-10-31",
    "discharge_date": "2026-11-03",
    "as_of": "2026-11-04",
}
US_ROWS = [
    Charge(
        "0120",
        "11/02",
        "Semi-private room",
        3,
        2660,
        "Bed census, nights Oct 31, Nov 1 and 2",
    ),
    Charge(
        "0250", "11/02", "Pharmacy", 4, 145, "Dispensing log RX-08, four billed lots"
    ),
    Charge("0300", "11/02", "Laboratory", 3, 240, "Laboratory accession list L21-L23"),
    Charge(
        "0320",
        "11/02",
        "Diagnostic radiology",
        2,
        340,
        "Chest imaging reports R11 and R12",
    ),
    Charge(
        "0450",
        "10/31",
        "Emergency department",
        1,
        1325,
        "Emergency encounter note ED-19",
    ),
]
TH_ROWS = [
    Charge("R001", "11/02", "Inpatient room", 3, 8400, "Ward census, three nights"),
    Charge("O001", "11/01", "Operating theatre", 1, 62800, "Operative log OP-33"),
    Charge(
        "I001",
        "11/01",
        "Fixation plate and screws",
        1,
        37450,
        "Implant sticker sheet IMP-08",
    ),
    Charge("X001", "11/02", "Imaging", 2, 4100, "Imaging records XR-21 and XR-25"),
    Charge(
        "L001", "11/02", "Laboratory", 3, 1250, "Diagnostic register LAB-11 to LAB-13"
    ),
    Charge("A001", "11/01", "Anaesthesia", 1, 18200, "Anaesthesia record AR-22"),
    Charge("P001", "11/02", "Dispensed supplies", 9, 350, "Dispensary ticket P-91"),
    Charge(
        "C001",
        "11/03",
        "Returned supplies credit",
        -2,
        350,
        "Return slip R-91 against P001",
    ),
]


def rendered(pages):
    out = BytesIO()
    c = Canvas(out, pagesize=letter, invariant=1)
    c.setAuthor("ZeroUpfront synthetic evaluation")
    for title, lines in pages:
        c.setFont("Helvetica-Bold", 15)
        c.drawString(34, 750, title)
        y = 723
        c.setFont("Helvetica", 10)
        for line in lines:
            for part in wrap(line, width=99) or [""]:
                c.drawString(34, y, part)
                y -= 15
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(
            34,
            29,
            "Fictional encounter for local software QA. No actual care, enrollment, signature or payment.",
        )
        c.showPage()
    c.save()
    return out.getvalue()


def joined(*documents):
    out, writer = BytesIO(), PdfWriter()
    for document in documents:
        for page in PdfReader(BytesIO(document)).pages:
            writer.add_page(page)
    writer.write(out)
    return out.getvalue()


def supporting(meta, rows, abroad):
    name = "Casey Example" if abroad else "Morgan Example"
    currency = "THB" if abroad else "USD"
    header = [
        meta["facility"],
        "101 Example Quay, Bangkok 10000"
        if abroad
        else "101 Example Way, Demo City, MA 00000",
        f"Patient {name}  |  Member {meta['member']}  |  Admission {meta['encounter']}",
        f"Service period 31 October - 3 November 2026  |  Payer {meta['insurer']}",
    ]
    summary = [
        (
            "Discharge summary / signed fictional copy",
            header
            + [
                "31 Oct. Admitted from emergency assessment after a fall at home. Imaging demonstrated a displaced distal radius fracture."
                if abroad
                else "31 Oct. Admitted to the medical service after emergency assessment for community-acquired pneumonia. Inpatient monitoring and respiratory support were recorded.",
                "1 Nov. Operative register OP-33 records plate fixation. Anaesthetic and implant identifiers match the support ledger."
                if abroad
                else "1 Nov. Serial medical observations, pharmacy dispensing and initial chest imaging are recorded in the hospital record.",
                "2 Nov. Ward team recorded satisfactory recovery. The clinical team completed repeat imaging and documented no extension of stay.",
                "3 Nov. Discharged home at 10:00. Inpatient service ended on this date. Follow-up was arranged in the outpatient clinic.",
                "Attending reviewer: Doctor Example / synthetic signature / 3 Nov 2026.",
            ],
        ),
        (
            "Discharge reconciliation / follow-up",
            header
            + [
                "Disposition: home. No interfacility transfer. Three ward nights, excluding discharge day.",
                "Hospital procedure: " + meta["procedure"],
                "No separate outpatient visit is included.",
                "Clinical record and final hospital account checked by Sample Ward Coordinator on 4 Nov 2026.",
            ],
        ),
    ]
    ledger = header + [f"Charges in {currency}. Date in month/day within 2026.", ""]
    support = header + ["Authenticated source identifiers and encounters", ""]
    for row in rows:
        ledger.append(
            f"{row.ref}   {row.day}   {row.label}   {row.units} x {row.price:,.2f} = {row.amount:,.2f}"
        )
        support.append(
            f"{row.ref}  {row.day}  {row.evidence}. Assigned to {meta['encounter']}."
        )
    ledger += [
        "",
        f"Grand total {currency} {sum(row.amount for row in rows):,.2f}. Closed by Sample Biller, 4 November 2026.",
    ]
    return {
        "bill": rendered([("Final itemized hospital invoice", ledger)]),
        "summary": rendered(summary),
        "records": rendered([("Clinical and financial supporting register", support)]),
    }


def institutional(front, back, issue):
    """Place the fictional values in the official fixed boxes using its measured 950px proof grid."""
    buffer = BytesIO()
    c = Canvas(buffer, pagesize=letter, invariant=1)
    scale = 792 / 950

    def field(x, y, value, size=6.5):
        c.setFont("Helvetica", size)
        c.drawString(x * scale, 792 - y * scale, value)

    field(58, 77, US["facility"])
    field(58, 89, "101 Example Way, Demo City MA 00000")
    field(58, 102, "TRAINING PROVIDER")
    field(245, 76, "Juniper Teaching Hospital")
    field(483, 75, US["encounter"])
    field(483, 89, "MR-70042")
    field(650, 87, "0117" if issue == "replacement_missing_reference" else "0111")
    field(519, 111, "103126")
    field(574, 111, "110326")
    field(143, 125, "EXAMPLE, MORGAN")
    field(383, 125, "108 Fiction Lane")
    field(331, 139, "Demo City")
    field(548, 139, "MA")
    field(577, 139, "00000")
    field(53, 164, "02141955")
    field(125, 164, "F")
    field(147, 164, "103126")
    field(186, 164, "16")
    field(211, 164, "1")
    field(242, 164, "7")
    field(262, 164, "10")
    field(285, 164, "02" if issue == "disposition_conflict" else "01")
    for i, row in enumerate(US_ROWS):
        y = 293 + i * 12.88
        field(54, y, row.ref)
        field(88, y, row.label)
        field(453, y, str(row.units))
        field(528, y, str(row.amount))
        field(570, y, "00")
    field(54, 576, "0001")
    field(119, 576, "1")
    field(174, 576, "1")
    field(398, 576, "110426")
    total = sum(r.amount for r in US_ROWS) + (
        500 if issue == "bill_total_disagrees" else 0
    )
    field(528, 576, str(total))
    field(570, 576, "00")
    field(596, 576, "0")
    field(649, 576, "00")
    field(55, 602, "MEDICARE PART A")
    field(570, 602, "0000000000")
    field(55, 654, "EXAMPLE, MORGAN")
    field(255, 654, "18")
    field(278, 654, "TEST-MBI-0099" if issue == "wrong_member" else US["member"])
    field(81, 744, "J189")
    field(54, 797, "")
    field(495, 784, "0000000000")
    field(442, 798, "EXAMPLE")
    field(579, 798, "ATTENDING")
    field(55, 847, "Synthetic QA only - simulated IDs")
    field(70, 52, "FICTIONAL ENCOUNTER - EDUCATIONAL SPECIMEN - NOT FOR FILING", 8)
    c.save()
    writer = PdfWriter()
    page = writer.add_page(PdfReader(BytesIO(front)).pages[0])
    page.merge_page(PdfReader(BytesIO(buffer.getvalue())).pages[0])
    writer.add_page(PdfReader(BytesIO(back)).pages[0])
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def overseas(blank, issue):
    """Print filled values at the publisher's widget coordinates, preserving both original pages."""
    source = PdfReader(BytesIO(blank))
    values = {
        "1A PatName": "Casey Example",
        "1B PatDOB": "05/15/1984",
        "1E ContractHolder": "Casey Example",
        "1F SubDOB": "05/15/1984",
        "1G SubAddress": "101 Example Lane, Bangkok, Thailand 10000",
        "1H Email": "casey@example.invalid",
        "ECNo": "05",
        "IDNo": "00000042",
        "3A VisitReason": "Fall at home; distal radius fracture; inpatient fixation and three ward nights.",
        "3C DateOfAccid": "10/31/2026",
        "3C TimeOfAccid": "10:00",
        "3C Time of Accident - Am/PM": "AM",
        "3C Accident Location": "Home",
        "1C Patient's Gender": "Female",
        "1D Patient's Relationship": "Self",
        "2A Other Health Insurance": "No",
        "3B Work Related Accident": "No",
        "4 CHARGES - BEGIN DATE": "10/31/2026",
        "4 CHARGES - END DATE": "11/03/2026",
        "4 TOTAL CHARGES": f"THB {sum(r.amount for r in TH_ROWS):,}.00",
        "4 CHARGES - NUMBER OF BILLS": "1",
        "SignatureDate": "11/04/2026",
        "SIGNATURE OF CONTRACT HOLDER OR PATIENT": "SYNTHETIC TEST ATTESTATION",
        "Home Phone Number": "202-555-0142",
    }
    if issue == "member_payee":
        values.update(
            {
                "5A Requested Currency": "Currency on Bills",
                "5B Reimbursement Type": "Check",
            }
        )
    else:
        values.update(
            {
                "5D AssignBenToProvName": TH["facility"],
                "5D AssignBenToProvStreetAddress": "101 Example Quay",
                "5D AssignBenToProvCity": "Bangkok",
                "5D AssignBenefitsToProvZip": "10000",
                "5D AssignBenefitsToProvCountry": "Thailand",
                "5D DateOfSignatureAssOfBenefits": "11/04/2026",
            }
        )
        if issue != "assignment_unsigned":
            values["5D AUTHORIZATION OF BENEFITS SIGNATURE"] = (
                "SYNTHETIC TEST ATTESTATION"
            )
    if issue == "form_total_disagrees":
        values["4 TOTAL CHARGES"] = "THB 160,000.00"
    buffer = BytesIO()
    c = Canvas(buffer, pagesize=letter, invariant=1)
    c.setFillColorRGB(0.08, 0.18, 0.35)
    for annot in source.pages[0]["/Annots"].get_object():
        obj = annot.get_object()
        parent = obj["/Parent"].get_object() if "/Parent" in obj else {}
        key = obj.get("/T", parent.get("/T"))
        value = values.get(key)
        if value is None:
            continue
        x1, y1, x2, y2 = map(float, obj["/Rect"])
        x, y = min(x1, x2), min(y1, y2)
        w = abs(x2 - x1)
        if obj.get("/FT", parent.get("/FT")) == "/Btn":
            if "/" + value in obj.get("/AP", {}).get("/N", {}):
                c.setFont("Helvetica-Bold", 10)
                c.drawString(x + 3, y + 3, "X")
        elif key in {"ECNo", "IDNo"}:
            c.setFont("Helvetica", 11)
            for i, glyph in enumerate(value):
                c.drawCentredString(x + (i + 0.5) * w / len(value), y + 6, glyph)
        else:
            size = min(10, (w - 3) / stringWidth(value, "Helvetica", 1))
            c.setFont("Helvetica", size)
            c.drawString(x + 2, y + 2.5, value)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(19, 775, "FICTIONAL LOCAL TEST / NO REAL SIGNATURE")
    c.save()
    writer = PdfWriter()
    page = writer.add_page(source.pages[0], excluded_keys=["/Annots"])
    page.merge_page(PdfReader(BytesIO(buffer.getvalue())).pages[0])
    writer.add_page(source.pages[1])
    out = BytesIO()
    writer.write(out)
    return out.getvalue()
