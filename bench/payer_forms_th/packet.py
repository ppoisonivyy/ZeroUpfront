"""Produce local, fictional exhibits on the pinned English and Thai AIA IPD originals."""

import subprocess
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / ".local/th-payer"
pdfmetrics.registerFont(TTFont("NotoThaiQA", ROOT / "app/fonts/NotoSansThai-Regular.ttf"))
BASE = "https://www.aia.co.th/content/dam/th-wise/images/th/help---support/si-141_form_library/"
FORMS = {
    "th": (
        BASE + quote("ใบนำส่งเอกสารร้องเรียนสินไหมทั่วไป") + ".pdf.coredownload.inline.pdf",
        "ed900381d9036a58c30347aa03f5d6914734f3798a114776cb629ffe48a36bc8",
    ),
    "en": (
        BASE + "ipd-en.pdf.coredownload.inline.pdf",
        "eb69605050eef54cf6bdee1589fc5b9c982afe51491e241cf1933901f1a6edec",
    ),
}
META = {
    "member": "T-TEST00001",
    "encounter": "AN-QA042",
    "procedure": "Wrist fracture fixation",
    "insurer": "AIA Thailand (synthetic test)",
    "facility": "Canal Demo Hospital",
    "admission_date": "2026-11-02",
    "discharge_date": "2026-11-04",
    "as_of": "2026-11-04",
}


def verified_form_bytes(language):
    url, expected = FORMS[language]
    path = DEST / (language + ".pdf")
    DEST.mkdir(parents=True, exist_ok=True)
    raw = (
        path.read_bytes()
        if path.exists()
        else subprocess.run(
            ["curl", "--fail", "--silent", "--show-error", "--location", "--max-time", "40", url],
            capture_output=True,
            check=True,
        ).stdout
    )
    if sha256(raw).hexdigest() != expected:
        raise ValueError(f"Published {language} form changed. Review layout before applying field positions.")
    if not path.exists():
        path.write_bytes(raw)
    return raw


def cover():
    marks = [
        (161, 126, "Mali Example (TEST)"),
        (79, 344, "X"),
        (82, 422, "X"),
        (202, 422, "X"),
        (369, 419, "X"),
        (369, 476, "X"),
        (369, 495, "X"),
    ]
    return marks + [(175 + 20.7 * i, 158, c) for i, c in enumerate("TEST00001")]


def patient(language, defect):
    th = language == "th"
    summary = [
        (135 if th else 165, 100 if th else 80, META["facility"]),
        (267 if th else 296, 101 if th else 81, "X"),
        (155 if th else 192, 152 if th else 125, "Mali Example (TEST)"),
        (329 if th else 372, 154 if th else 126, "X"),
        (109, 166 if th else 139, "18 Nov 1987"),
        (270 if th else 279, 166 if th else 139, "38"),
        (401 if th else 474, 166 if th else 139, "นักออกแบบ (ข้อมูลสมมติ)" if th else "Stage designer (fictional)"),
        (453 if th else 519, 152 if th else 125, "TEST-ID-ONLY"),
        (392 if th else 427, 180 if th else 154, "qa@example.invalid"),
        (
            164 if th else 122,
            193 if th else 168,
            "42 ซอยตัวอย่าง กรุงเทพฯ (ข้อมูลสมมติ)" if th else "42 Sample Court, Bangkok (fictional)",
        ),
        (142 if th else 159, 207 if th else 182, META["member"]),
        (178 if th else 370, 223 if th else 200, "X"),
        (53 if th else 59, 279 if th else 274, "X"),
        (165 if th else 172, 278 if th else 272, "02 Nov 2026"),
        (253 if th else 320, 278 if th else 272, "07:15"),
        (369 if th else 437, 278 if th else 272, "Fictional station, Bangkok"),
        (
            146,
            292 if th else 288,
            "สะดุดขั้นบันได ล้มลงโดยใช้มือซ้ายยันพื้น"
            if th
            else "Tripped on a step and landed on the outstretched left hand.",
        ),
        (278, 305 if th else 301, "Displaced left distal radius fracture; no open wound."),
        (228 if th else 214, 321 if th else 317, "X"),
        (306 if th else 455, 333 if th else 330, "92,750.00" if defect == "amount" else "87,500.00"),
    ]
    if defect != "consent":
        summary += [
            (115 if th else 88, 525 if th else 550, "TEST PATIENT MARK"),
            (261 if th else 234, 525 if th else 550, "04 Nov 2026"),
        ]
    # The attending physician block on Part A is distinct from the Part B certification.
    ys = (
        [674, 689, 704, 743, 772, 838, 851, 867, 880, 909, 922, 943, 967]
        if th
        else [678, 692, 706, 746, 775, 852, 879, 894, 908, 936, 948, 962, 984]
    )
    summary += [
        (99, ys[0], "02 Nov 2026"),
        (201, ys[0], "08:10"),
        (337, ys[0], "36.8 C"),
        (435, ys[0], "84"),
        (526, ys[0], "16"),
        (602, ys[0], "126/78"),
        (158, ys[1], "Pain and swelling for 55 minutes"),
        (190, ys[2], "Fall on left hand; no loss of consciousness."),
        (119, ys[3], "Dorsal deformity. Pulses and finger sensation intact."),
        (284, ys[4], "None before arrival"),
        (57, ys[5] + 2, "X"),
        (185, ys[5], "02 Nov 2026"),
        (341, ys[5], "07:15"),
        (152, ys[6], "None reported"),
        (149, ys[7], "Closed displaced left distal radius fracture"),
        (296, ys[8] + 2, "X"),
        (145, ys[9], "Unstable alignment after reduction; requires fixation."),
        (130, ys[10], "Splint, fixation, postoperative observation"),
        (140, ys[11], "QA CLINICIAN"),
        (474, ys[11], "TEST-ONLY"),
        (620, ys[11], "Orthopaedics"),
        (476, ys[12], "02 Nov 2026"),
    ]
    return summary


def certificate(language, defect):
    delta = 4 if language == "th" else 0
    rows = [
        (98, 83, "Mali Example (TEST)"),
        (307, 85, "X"),
        (368, 83, "HN-QA017"),
        (463, 83, "AN-QA999" if defect == "encounter" else META["encounter"]),
        (553, 83, "38"),
        (99, 103, "02 Nov 2026"),
        (198, 103, "08:10"),
        (333, 103, "04 Nov 2026"),
        (432, 103, "14:30"),
        (567, 103, "02 Nov 2026"),
        (444, 137, "02 Nov 2026"),
        (581, 137, "07:15"),
        (413, 164, "Fall on outstretched left hand"),
        (456, 180, "Closed left distal radius fracture"),
        (488, 265, "6 weeks to review wrist function"),
        (391, 211, "X"),
        (478, 238, "X"),
        (263, 309, "X"),
        (280, 639, "X"),
        (280, 658, "X"),
        (280, 676, "X"),
        (280, 695, "X"),
        (381, 307, "Unstable displaced fracture; operative fixation indicated."),
        (103, 342, "36.8"),
        (164, 342, "84"),
        (233, 342, "16"),
        (302, 342, "126/78"),
        (234, 359, "Dorsal angulation with swelling; skin and distal perfusion intact."),
        (236, 396, "PA and lateral radiographs confirm displaced intra-articular fracture."),
        (129, 445, "None recorded"),
        (106, 461, "Closed distal radius fracture, left"),
        (374, 461, "S52.5"),
        (101, 512, "Splint and operative fixation; neurovascular observation."),
        (137, 547, "Open reduction and volar plate fixation"),
        (584, 547, "03 Nov 2026"),
        (146, 617, "None documented"),
        (215, 849, "Discharged home; radiograph and wrist clinic in 7 days."),
        (398, 910, "Orthopaedics"),
        (619, 910, "TEST-ONLY"),
        (570, 927, "04 Nov 2026"),
        (112, 947, META["facility"]),
    ]
    if defect != "certification":
        rows.append((143, 910, "TEST CLINICIAN MARK"))
    return [(x, y + delta, value) for x, y, value in rows]


def filled_form(language, defect="clean"):
    reader = PdfReader(BytesIO(verified_form_bytes(language)))
    bodies = ([cover()] if language == "th" else []) + [
        patient(language, defect),
        certificate(language, defect),
    ]
    writer = PdfWriter()
    for page, rows in zip(reader.pages, bodies, strict=True):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        stream = BytesIO()
        c = Canvas(stream, pagesize=(width, height), invariant=1)
        c.setFillColorRGB(0.035, 0.16, 0.45)
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(width / 2, height - 8, "SYNTHETIC TEST DATA  /  NO SUBMISSION OR PAYMENT")
        c.setFont("Helvetica", 7)
        # Field positions measured from top of each 1024-point-high reference rendering.
        for x, y, value in rows:
            is_thai = any("\u0e00" <= char <= "\u0e7f" for char in value)
            c.setFont("NotoThaiQA" if is_thai else "Helvetica", 7)
            c.drawString(x * height / 1024, height - y * height / 1024, value, shaping=is_thai)
        c.save()
        writer.add_page(page).merge_page(PdfReader(BytesIO(stream.getvalue())).pages[0])
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


def exhibit(title, identifier, pages):
    out = BytesIO()
    c = Canvas(out, pagesize=A4, invariant=1)
    c.setTitle(title)
    for number, lines in enumerate(pages, 1):
        blocks = [
            title,
            f"Document ID: {identifier}",
            f"Page {number} of {len(pages)}",
            "Member: " + META["member"],
            "Encounter: " + META["encounter"],
            "Facility: " + META["facility"],
            *lines,
        ]
        y = 775
        for i, line in enumerate(blocks):
            c.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 19 if i == 0 else 9)
            c.drawString(35, y, line)
            y -= 35 if i == 0 else 22
        c.setFont("Helvetica", 9)
        c.drawString(35, 38, "Fictional discharge exhibit / ZeroUpfront")
        c.showPage()
    c.save()
    return out.getvalue()


def exhibits():
    dates = ["Admission date: 2026-11-02", "Discharge date: 2026-11-04"]
    # Six dated service entries, a partial supply credit, signed summary and tracked authorization.
    charges = [
        ("BED", "2026-11-02", "Ward and nursing nights", 2, 6500),
        ("OR", "2026-11-03", "Theatre and fluoroscopy", 1, 24000),
        ("PLATE", "2026-11-03", "Volar plate and screw set", 1, 18800),
        ("SURG", "2026-11-03", "Surgeon and anaesthesia", 1, 21400),
        ("XR", "2026-11-04", "Radiograph views", 2, 2850),
        ("PHARM", "2026-11-04", "Medication and sterile packs", 4, 1450),
    ]
    entries = [
        f"Charge: {code} | {date} | {name} | {qty} | THB {price:,.2f} | THB {qty * price:,.2f}"
        for code, date, name, qty, price in charges
    ]
    evidence = [f"Service evidence: {code} | {name}" for code, _, name, _, _ in charges]
    return {
        "bill": exhibit(
            "Final itemized hospital bill",
            "QA-BILL-017",
            [
                [
                    *dates,
                    "Final bill total: THB 87,500.00",
                    "Recorded patient share: THB 5,000.00",
                    *entries[:3],
                ],
                [
                    *entries[3:],
                    "Credit: RET01 | PHARM | 2026-11-04 | THB 1,200.00 | Unused dressing and supply credit",
                ],
            ],
        ),
        "summary": exhibit(
            "Inpatient discharge summary",
            "QA-SUM-017",
            [
                [
                    *dates,
                    "Performed procedure: Wrist fracture fixation",
                    "Attending service: Orthopaedics",
                    "Hospital course: The patient received operative care following a wrist fracture.",
                ],
                [
                    "Disposition: Discharged home",
                    "Follow-up: Outpatient clinic in one week.",
                    "Summary status: Signed final",
                ],
            ],
        ),
        "letter": exhibit(
            "Payer preauthorization letter",
            "QA-AUTH-017",
            [
                [
                    "Payer: " + META["insurer"],
                    "Letter status: Preauthorization",
                    "Issued on: 2026-11-02",
                    "Valid from: 2026-11-02",
                    "Valid through: 2026-11-04",
                    "Authorized procedure: Wrist fracture fixation",
                ],
                [
                    "Authorized billed-charge ceiling: THB 90,000.00",
                    "Documented fixed patient share: THB 5,000.00",
                    "Final review: Payer reviews the actual bill, summary and supporting records.",
                ],
            ],
        ),
        "records": exhibit(
            "Hospital supporting records",
            "QA-LOG-017",
            [
                [
                    *dates,
                    "Letter received on: 2026-11-02",
                    "Procedure record: Wrist fracture fixation",
                    *evidence[:3],
                ],
                [
                    *evidence[3:],
                    "Credit evidence: RET01 | Unused dressing and supply credit",
                    "Record status: Signed final",
                ],
            ],
        ),
    }


def joined(*originals):
    writer, out = PdfWriter(), BytesIO()
    for raw in originals:
        writer.append(BytesIO(raw))
    writer.write(out)
    return out.getvalue()
