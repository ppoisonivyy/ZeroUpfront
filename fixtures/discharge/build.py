"""Rebuild the fictional discharge exhibits. All amounts and identifiers were authored for testing."""
import io
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parent
TITLES = {"bill": "Final itemized hospital bill", "summary": "Inpatient discharge summary",
          "letter": "Payer preauthorization letter", "records": "Hospital supporting records"}
IDENTITY = ["Member: EXAMPLE-2402", "Encounter: EXAMPLE-VISIT-42", "Facility: Canal Bridge Demo Hospital"]
DATES = ["Admission date: 2026-12-11", "Discharge date: 2026-12-13"]
PROCEDURE = "Wrist fracture fixation"
EXHIBITS = {
    "bill": [
        [*DATES, "Final bill total: THB 87,500.00", "Recorded patient share: THB 5,000.00",
         "Charge: FAC01 | 2026-12-11 | Inpatient facility | 2 | THB 16,000.00 | THB 32,000.00",
         "Charge: OR01 | 2026-12-12 | Operating services | 1 | THB 45,000.00 | THB 45,000.00"],
        ["Charge: IMG01 | 2026-12-12 | Diagnostic imaging | 1 | THB 8,700.00 | THB 8,700.00",
         "Charge: MED01 | 2026-12-13 | Pharmacy supply | 3 | THB 1,200.00 | THB 3,600.00",
         "Credit: CR01 | MED01 | 2026-12-13 | THB 1,800.00 | Returned unused supply"]],
    "summary": [
        [*DATES, "Performed procedure: " + PROCEDURE, "Attending service: Orthopaedics",
         "Hospital course: The patient received operative care following a wrist fracture."],
        ["Disposition: Discharged home", "Follow-up: Outpatient clinic in one week.",
         "Summary status: Signed final"]],
    "letter": [
        ["Payer: Alder Transit Cover", "Letter status: Preauthorization", "Issued on: 2026-12-08",
         "Valid from: 2026-12-11", "Valid through: 2026-12-13", "Authorized procedure: " + PROCEDURE],
        ["Authorized billed-charge ceiling: THB 90,000.00", "Documented fixed patient share: THB 5,000.00",
         "Final review: Payer reviews the actual bill, summary and supporting records."]],
    "records": [
        [*DATES, "Letter received on: 2026-12-09", "Procedure record: " + PROCEDURE,
         "Service evidence: FAC01 | Inpatient facility", "Service evidence: OR01 | Operating services"],
        ["Service evidence: IMG01 | Diagnostic imaging", "Service evidence: MED01 | Pharmacy supply",
         "Credit evidence: CR01 | Returned unused supply", "Record status: Signed final"]],
}
# A scenario overrides only the exhibit that changed; all other roles use their baseline PDF.
VARIANTS = {
    "duplicate_line": ("bill", [(2, "Charge: MED01", EXHIBITS["bill"][1][1] + "\n" + EXHIBITS["bill"][1][1])]),
    "orphan_credit": ("bill", [(2, "Credit: CR01", EXHIBITS["bill"][1][2].replace("MED01", "MISSING"))]),
    "total_mismatch": ("bill", [(1, "Final bill total:", "Final bill total: THB 89,300.00")]),
    "over_cap": ("letter", [(2, "Authorized billed-charge ceiling:", "Authorized billed-charge ceiling: THB 85,000.00")]),
    "share_mismatch": ("bill", [(1, "Recorded patient share:", "Recorded patient share: THB 7,000.00")]),
    "member_mismatch": ("records", [(2, "Member:", "Member: EXAMPLE-2488")]),
    "encounter_mismatch": ("summary", [(1, "Encounter:", "Encounter: EXAMPLE-VISIT-99")]),
    "unapproved_procedure": ("summary", [(1, "Performed procedure:", "Performed procedure: Wrist fracture fixation plus tendon repair")]),
    "stay_extension": ("letter", [(1, "Valid through:", "Valid through: 2026-12-12")]),
    "late_reply": ("records", [(1, "Letter received on:", "Letter received on: 2026-12-15")]),
    "mixed_currency": ("bill", [(2, "Charge: IMG01", EXHIBITS["bill"][1][0].replace("THB", "USD"))]),
    "missing_support": ("records", [(2, "Service evidence: IMG01", None)]),
    "unit_mismatch": ("bill", [(1, "Charge: FAC01", EXHIBITS["bill"][0][-2].replace(" | 2 | ", " | 3 | "))]),
    "unsupported_terms": ("letter", [(2, "Documented fixed patient share:", "Coinsurance: 20% after deductible")]),
    "excess_credit": ("bill", [(2, "Credit: CR01", EXHIBITS["bill"][1][2].replace("1,800", "3,900"))]),
    "date_mismatch": ("summary", [(1, "Discharge date:", "Discharge date: 2026-12-14")]),
    "wrong_payer": ("letter", [(1, "Payer: ", "Payer: Orchard Travel Cover")]),
    "credit_before_charge": ("bill", [(2, "Credit: CR01", EXHIBITS["bill"][1][2].replace("2026-12-13", "2026-12-11"))]),
    "unreadable_summary": ("summary", []),
}


def render(role, scenario="aligned"):
    stream = io.BytesIO()
    c = Canvas(stream, pagesize=A4, invariant=1)
    c.setTitle(TITLES[role])
    c.setAuthor("ZeroUpfront fictional examples")
    for number, lines in enumerate(EXHIBITS[role], 1):
        if scenario != "unreadable_summary":
            words = [TITLES[role], f"Document ID: DC-{role.upper()}-42", f"Page {number} of 2",
                     *IDENTITY, *lines]
            for page, prefix, replacement in VARIANTS.get(scenario, ("", []))[1]:
                if page == number:
                    words = [part for line in words for part in ((replacement or "").splitlines()
                             if line.startswith(prefix) else [line])]
            y = 777
            for n, text in enumerate(words):
                c.setFillColorRGB(*(0.08, 0.23, 0.26) if n == 0 else (0.13, 0.19, 0.21))
                c.setFont("Helvetica-Bold" if n == 0 else "Helvetica", 19 if n == 0 else 10)
                c.drawString(42, y, text)
                y -= 35 if n == 0 else 24
            c.setFillColorRGB(0.25, 0.35, 0.37)
            c.setFont("Helvetica", 9)
            c.drawString(42, 39, "Fictional discharge exhibit / ZeroUpfront")
        c.showPage()
    c.save()
    return stream.getvalue()


def build(destination=ROOT):
    for role in EXHIBITS:
        (destination / (role + ".pdf")).write_bytes(render(role))
    for scenario, (role, _) in VARIANTS.items():
        (destination / (scenario + "-" + role + ".pdf")).write_bytes(render(role, scenario))


if __name__ == "__main__":
    build()
