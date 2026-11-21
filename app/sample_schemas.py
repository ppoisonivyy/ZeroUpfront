"""Output contracts based on the supplied training split; no held-out labels."""
from pydantic import BaseModel


class Totals(BaseModel):
    gross: int | None
    discount: int | None
    net: int | None
    source: str | None


class Billing(BaseModel):
    type: str
    currency: str | None
    reported_totals: Totals
    visible_detail_net: int | None
    detail_sources: list[str]
    reconciliation: str
    delta_reported_minus_detail: int | None
    paid_to_date: int | None
    payment_source: str | None
    balance_due: int | None
    next_step: str


class MedicalRecord(BaseModel):
    hn: str | None
    registration_source: str | None
    diagnosis: str | None
    planned_service: str | None
    signed: bool | None
    procedure_code: str | None
    plan_source: str | None
    gap: str | None


class ExhibitQuote(BaseModel):
    source: str
    quote: str


class GuaranteeRequest(BaseModel):
    status: str
    estimate_thb: int | None
    excluded_thb: int | None
    above_balance_thb: int | None
    provisional_eligible_thb: int | None
    draft_request_thb: int | None
    sources: list[str]
    policy_evidence: list[ExhibitQuote]
    next_action: str
