"""Fictional Meridian Assist documents for the planned-admission demonstration."""

from io import BytesIO
from textwrap import wrap

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

CASE = "ZU-0248"
PATIENT = "Amelia Morgan"
MEMBER = "DEMO-MA-0248"
PROCEDURE = "Inpatient knee arthroscopy"
INSURER = "Meridian Assist"
EDITION = "Global Select · demo edition 2026"
TOTAL = 128000
ADMISSION = "2026-11-23"
RULE_PAGE = 12
RULE = "An inpatient request must include a medical report signed by the treating physician, stating the indication and planned procedure."
BENEFIT = "Inpatient knee arthroscopy estimates up to THB 150,000 may be submitted for pre-authorisation."
SIGNATURE = "Treating physician signature: Dr. Mira Saran (fictional)"
INDICATION = "Indication: Persistent mechanical symptoms described in the treating physician's report."


def pdf(title, chapters):
    stream = BytesIO()
    c = Canvas(stream, pagesize=A4, invariant=True)
    c.setTitle(title)
    c.setAuthor("ZeroUpfront synthetic documents")
    for number, (heading, lines) in enumerate(chapters, 1):
        c.setFillColorRGB(0.08, 0.24, 0.22)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(46, 780, title)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(46, 732, heading)
        y = 686
        c.setFillColorRGB(0.12, 0.16, 0.17)
        c.setFont("Helvetica", 11)
        for para in lines:
            for line in wrap(para, 82):
                c.drawString(46, y, line)
                y -= 17
            y -= 10
        c.setFont("Helvetica", 9)
        c.drawString(46, 45, "Fictional training document | Administrative review only")
        c.drawRightString(550, 45, f"Page {number} of {len(chapters)}")
        c.showPage()
    c.save()
    return stream.getvalue()


def policy():
    sections = [
        (
            "1. Policy schedule",
            [
                "Policy wording for the fictional Global Select inpatient programme.",
                "Edition: GS-DEMO-2026.1. Issuer: Meridian Assist.",
            ],
        ),
        ("1.1 Membership", ["The request identifies the member and the planned admission."]),
        (
            "1.2 Provider eligibility",
            ["The hospital identifies its treating service and facility on the request."],
        ),
        ("1.3 Period of cover", ["The requested service date must fall inside the confirmed period of cover."]),
        (
            "2. Request process",
            ["The hospital sends the request and original supporting exhibits to the insurer."],
        ),
        ("2.1 Estimates", ["The cost estimate itemises expected facility and professional charges."]),
        ("2.2 Decision authority", ["Only a written insurer response establishes the terms of a guarantee."]),
        ("3.1 Planned inpatient benefit", [BENEFIT]),
        ("3.2 Revised costs", ["New or revised charges may require a supplementary request."]),
        (
            "3.3 Patient contributions",
            ["A contribution follows the insurer's written terms for the actual encounter."],
        ),
        (
            "4.1 Required supporting documents",
            ["Include the applicable policy, treatment information and an itemised estimate."],
        ),
        (
            "4.2 Medical report",
            [RULE, "The coordinator checks the report against the member and encounter before submission."],
        ),
    ]
    return pdf("Meridian Assist | Global Select | GS-DEMO-2026.1", sections)


def exhibits(hospital):
    identity = [
        f"Patient: {PATIENT}",
        f"Member: {MEMBER}",
        f"Case: {CASE}",
        f"Hospital: {hospital}",
        f"Planned procedure: {PROCEDURE}",
        f"Admission date: {ADMISSION}",
    ]
    unsigned = pdf(
        "Treating service | Medical report",
        [("Initial report", identity + [INDICATION, "Treating physician signature: Pending"])],
    )
    signed = pdf(
        "Treating service | Medical report", [("Signed replacement report", identity + [INDICATION, SIGNATURE])]
    )
    estimate = pdf(
        "Hospital billing | Pre-admission estimate",
        [
            (
                "Itemised cost estimate",
                identity
                + [
                    "Facility and theatre: THB 90,000",
                    "Professional charges: THB 38,000",
                    "Estimated total: THB 128,000",
                ],
            )
        ],
    )
    return {"policy": policy(), "report": unsigned, "estimate": estimate, "replacement": signed}


def pages(raw):
    return [" ".join((p.extract_text() or "").split()) for p in PdfReader(BytesIO(raw)).pages]


def case_values(hospital):
    return {
        "patient": PATIENT,
        "member": MEMBER,
        "procedure": PROCEDURE,
        "insurer": INSURER,
        "hospital": hospital,
        "total": TOTAL,
        "currency": "THB",
        "admission_date": ADMISSION,
        "form_edition": "MA-IP-01",
        "policy_edition": "GS-DEMO-2026.1",
        "rule_page": RULE_PAGE,
        "rule_quote": RULE,
        "indication": INDICATION,
        "signature": SIGNATURE,
    }


def checks(policy_bytes, report_bytes, estimate_bytes, case_id, values, *, signed_attestation=False):
    policy_pages, estimate_pages = map(pages, (policy_bytes, estimate_bytes))
    page = values["rule_page"]
    verified = len(policy_pages) >= page and values["rule_quote"] in policy_pages[page - 1]
    identity = [
        f"Patient: {values['patient']}",
        f"Member: {values['member']}",
        f"Case: {case_id}",
        f"Hospital: {values['hospital']}",
        f"Planned procedure: {values['procedure']}",
        f"Admission date: {values['admission_date']}",
    ]
    if report_bytes is None:
        signed = signed_attestation
    else:
        report_pages = pages(report_bytes)
        signed = len(report_pages) == 1 and all(
            text in report_pages[0] for text in [*identity, values["indication"], values["signature"]]
        )
    amount = f"Estimated total: {values['currency']} {values['total']:,}"
    estimated = len(estimate_pages) == 1 and all(text in estimate_pages[0] for text in [*identity, amount])
    return verified, signed, estimated


def request_pdf(case_id, values, revision, actor=None, *, report_page=None):
    title = f"{values['insurer']} | Global Select | {values['form_edition']} (fictional)"
    return pdf(
        title,
        [
            (
                "Inpatient pre-authorisation request",
                [
                    f"Request reference: {case_id} | Evidence revision {revision}",
                    f"Patient: {values['patient']}",
                    f"Member: {values['member']}",
                    f"Hospital: {values['hospital']}",
                    f"Requested admission: {values['admission_date']}",
                    f"Procedure: {values['procedure']}",
                    f"Itemised estimate: {values['currency']} {values['total']:,}",
                    "Exhibits: policy wording, signed treating physician report and itemised estimate.",
                    f"Rule: Global Select section 4.2, physical page {values['rule_page']}.",
                    (f"Hospital staff visually attested the treating physician mark on report page {report_page} "
                     "and confirmed the encounter, indication and planned procedure.")
                    if report_page else "Verified case packet: signed medical report with indication and procedure.",
                    f"Hospital staff review: {actor}" if actor else "Draft for hospital staff review.",
                    "The hospital requests pre-authorisation. The insurer has not issued a payment guarantee.",
                ],
            )
        ],
    )
