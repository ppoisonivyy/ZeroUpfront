"""Fictional discharge exhibits based on Bangkok Hospital Pattaya's published lens package."""

from dataclasses import dataclass
from decimal import Decimal

from app.journey_examples import pdf


FACILITY = "Pattaya Practice Hospital"
ENCOUNTER = "DEMO-LENS-239"
CREDIT_DOCUMENTS = {"record_short_credit": "initial_credit", "record_topup": "topup_credit"}
PROCEDURE = "Bilateral multifocal lens replacement"
SCENARIO = "pattaya_fx"
TERMS = ("The insurer guarantees net THB 239,000 to the hospital. The hospital payment is due 30 November 2026. The patient share is THB 0. "
         "The insurer bears exchange-rate changes and bank fees and must fund any payment shortfall.")


def exhibits(*, facility=FACILITY, member="DEMO-PATTAYA-239", encounter=ENCOUNTER):
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


def final_decision(*, facility=FACILITY, encounter=ENCOUNTER):
    return pdf(["FICTIONAL INSURER GUARANTEE | Pattaya practice case", "Final decision dated 19 November 2026",
                "Meridian Travel Cover (fictional)", f"Hospital: {facility}",
                f"Encounter: {encounter}", "Covered procedure: " + PROCEDURE,
                "Guaranteed net hospital payment: THB 239,000.00", "Agreed patient share: THB 0.00",
                "Hospital payment due: 30 November 2026",
                "The insurer funds exchange-rate changes and bank fees.",
                "If the hospital receives less, the insurer pays the outstanding THB balance.",
                "Additional services need separate approval.", "Issued by the fictional insurer claims desk.", "Synthetic rehearsal. No real guarantee is issued."])


@dataclass(frozen=True)
class BankMessage:
    kind: str
    case_id: str
    encounter: str
    beneficiary: str
    bank_reference: str
    value_date: str
    currency: str
    gross_minor: int
    fee_minor: int | None
    net_minor: int | None

    def remittance_terms(self):
        """The immutable terms shared by the saved instruction and its replay check."""
        return dict(reference=f"SIM-{self.case_id}-RECORD_REMITTANCE", bank_reference=self.bank_reference,
                    value_date=self.value_date, currency=self.currency, instructed_minor=self.gross_minor)

    def document(self):
        def money(minor):
            return f"{self.currency} {Decimal(minor) / 100:,.2f}"

        is_instruction = self.kind in ("instruction", "topup_instruction")
        heading = "SENDER TRANSFER INSTRUCTION" if is_instruction else "BENEFICIARY CREDIT ADVICE"
        lines = [f"SIMULATED {heading}", "Pattaya practice case / fictional bank document",
                 "Issued by: " + ("Practice Sending Bank" if is_instruction else "Practice Receiving Bank"),
                 f"Bank reference: {self.bank_reference}", f"Claim reference: {self.case_id}",
                 f"Encounter: {self.encounter}", f"Beneficiary: {self.beneficiary}",
                 f"{'Requested' if is_instruction else 'Credit'} value date: {self.value_date}",
                 f"Instructed amount: {money(self.gross_minor)}"]
        if is_instruction:
            lines.append("Status: Transfer requested. Beneficiary credit unconfirmed.")
        else:
            lines.append("Status: Posted to beneficiary account")
            lines.append("Receiving-bank deduction: " + (money(self.fee_minor) if self.fee_minor is not None else "Unspecified"))
            lines.append(f"Net credited to hospital: {money(self.net_minor)}")
        return pdf(lines)


def bank_message(ident, kind, *, hospital_slug=None):
    # The sample receiving bank issues these facts independently of the hospital ledger.
    if kind == "instruction":
        leg, value_date, gross, fee, net = "SEND-01", "2026-11-30", 23_900_000, None, None
    elif kind == "initial_credit":
        leg, value_date, gross, fee, net = "CREDIT-01", "2026-11-30", 23_900_000, 30_000, 23_870_000
    elif kind == "topup_instruction":
        leg, value_date, gross, fee, net = "SEND-02", "2026-12-01", 30_000, None, None
    elif kind == "topup_credit":
        leg, value_date, gross, fee, net = "CREDIT-02", "2026-12-01", 30_000, 0, 30_000
    else:
        raise ValueError("Unknown practice bank document.")
    facility, encounter = FACILITY, ENCOUNTER
    if hospital_slug is not None:
        # The fictional bank uses the registered beneficiary for this seeded hospital.
        from app.hospital_demo import HOSPITALS
        facility, code = HOSPITALS[hospital_slug]
        encounter = f"VISIT-{code}-FX"
    return BankMessage(kind, ident, encounter, facility, f"SIM-{leg}-{ident}", value_date, "THB", gross, fee, net)
