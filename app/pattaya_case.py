"""Fictional discharge exhibits based on Bangkok Hospital Pattaya's published lens package."""

from app.journey_examples import pdf


PROCEDURE = "Bilateral multifocal lens replacement"
SCENARIO = "pattaya_fx"
TERMS = ("The insurer guarantees net THB 239,000 to the hospital. The hospital payment is due 30 November 2026. The patient share is THB 0. "
         "The insurer bears exchange-rate changes and bank fees and must fund any payment shortfall.")


def exhibits(*, facility="Pattaya Practice Hospital", member="DEMO-PATTAYA-239", encounter="DEMO-LENS-239"):
    insurer = "Meridian Travel Cover (fictional)"
    admission, discharge = "2026-11-18", "2026-11-19"
    dates = [f"Admission date: {admission}", f"Discharge date: {discharge}"]
    case = dict(member=member, encounter=encounter, facility=facility, insurer=insurer, procedure=PROCEDURE,
                admission_date=admission, discharge_date=discharge, as_of=discharge)
    identity = [f"Member: {member}", f"Encounter: {encounter}", f"Facility: {facility}"]
    lines = {
        "bill": ["Final itemized hospital bill", *dates, "Final bill total: THB 239,000.00",
                 "Recorded patient share: THB 0.00",
                 "Charge: LENS | 2026-11-18 | Bilateral lens package | 1 | THB 239,000.00 | THB 239,000.00"],
        "summary": ["Inpatient discharge summary", *dates, f"Performed procedure: {PROCEDURE}",
                    "Attending service: Ophthalmology", "Hospital course: The patient received bilateral lens replacement.",
                    "Disposition: Discharged home", "Follow-up: Outpatient clinic in one week.",
                    "Summary status: Signed final"],
        "letter": ["Initial capped guarantee of payment", f"Payer: {insurer}", "Letter status: Initial capped guarantee",
                   "Issued on: 2026-11-16", f"Valid from: {admission}", f"Valid through: {discharge}",
                   f"Authorized procedure: {PROCEDURE}", "Authorized billed-charge ceiling: THB 239,000.00",
                   "Documented fixed patient share: THB 0.00",
                   "Final review: Payer reviews the actual bill, summary and supporting records."],
        "records": ["Hospital supporting records", *dates, "Letter received on: 2026-11-17",
                    f"Procedure record: {PROCEDURE}", "Service evidence: LENS | Bilateral lens package",
                    "Record status: Signed final"],
    }
    raw = {role: pdf([heading, f"Document ID: PATTAYA-{role.upper()}-239", "Page 1 of 1", *identity,
                      *fields, "Fictional discharge exhibit / ZeroUpfront"])
           for role, (heading, *fields) in lines.items()}
    names = {role: f"pattaya-practice-{role}.pdf" for role in raw}
    return case, raw, names


def final_decision(*, facility="Pattaya Practice Hospital", encounter="DEMO-LENS-239"):
    return pdf(["FICTIONAL INSURER GUARANTEE | Pattaya practice case", "Final decision dated 19 November 2026",
                "Meridian Travel Cover (fictional)", f"Hospital: {facility}",
                f"Encounter: {encounter}", "Covered procedure: " + PROCEDURE,
                "Guaranteed net hospital payment: THB 239,000.00", "Agreed patient share: THB 0.00",
                "Hospital payment due: 30 November 2026",
                "The insurer funds exchange-rate changes and bank fees.",
                "If the hospital receives less, the insurer pays the outstanding THB balance.",
                "Additional services need separate approval.", "Issued by the fictional insurer claims desk.", "Synthetic rehearsal. No real guarantee is issued."])
