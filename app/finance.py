"""Deterministic THB calculations, plus adapters for the supplied synthetic text exhibits.

Amounts are Decimal baht, with at most two fractional digits. A ReviewRequired
exception means the adapter cannot establish the packet facts for this format.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re

AMOUNT = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?"
ZERO = Decimal("0")


class ReviewRequired(ValueError):
    """Staff must resolve missing or ambiguous source information before calculation."""


def money(raw: str) -> Decimal:
    text = raw.strip()
    if not re.fullmatch(AMOUNT, text) or len(text.replace(",", "")) > 18:
        raise ReviewRequired(f"Invalid or unreadable THB amount: {text!r}")
    return Decimal(text.replace(",", ""))


def check_amount(value: Decimal) -> None:
    if (not isinstance(value, Decimal) or not value.is_finite() or value < ZERO
            or value.as_tuple().exponent < -2 or value.adjusted() >= 18):
        raise ReviewRequired("THB amounts must be finite, nonnegative decimals with at most two fractional digits")


@dataclass(frozen=True)
class Charges:
    gross: Decimal
    discount: Decimal
    net: Decimal

    def __post_init__(self):
        for value in (self.gross, self.discount, self.net):
            check_amount(value)

    @classmethod
    def from_row(cls, text: str) -> Charges:
        cells = [cell.strip() for cell in text.split("|")]
        if len(cells) != 4 or not cells[0]:
            raise ReviewRequired("Expected a labeled gross, discount and net row")
        return cls(*(money(cell) for cell in cells[1:]))

    def consistent(self) -> bool:
        return self.gross - self.discount == self.net


def reconcile_statement(reported: Charges, lines: list[Charges], complete: bool,
                        paid_to_date: Decimal | None) -> dict:
    """Reconcile a single statement revision. The caller verifies page and receipt identity."""
    if paid_to_date is not None:
        check_amount(paid_to_date)
    visible = sum((line.net for line in lines), ZERO) if lines else None
    delta = None
    balance = None
    if not complete:
        status = "incomplete_pages"
    elif visible is None:
        status = "missing_detail"
    else:
        delta = reported.net - visible
        if delta:
            status = "net_mismatch"
        elif (not reported.consistent() or any(not line.consistent() for line in lines)
              or sum(line.gross for line in lines) != reported.gross
              or sum(line.discount for line in lines) != reported.discount):
            status = "amount_mismatch"
        elif paid_to_date is not None and paid_to_date > reported.net:
            status = "payment_exceeds_charges"
        else:
            status = "matches"
            if paid_to_date is not None:
                balance = reported.net - paid_to_date
    return {"reported_gross": reported.gross, "reported_discount": reported.discount,
            "reported_net": reported.net, "visible_detail_net": visible,
            "delta_reported_minus_detail": delta, "paid_to_date": paid_to_date,
            "balance_due": balance, "reconciliation": status}


def billing_fields(case: str, exhibits: dict[str, str]) -> dict:
    """Read the supplied pipe-delimited Thai statement format for one encounter."""
    headers = {}
    attached = set()
    lines = []
    has_columns = False
    totals = []
    subtotals = []
    receipts = []
    for source, text in exhibits.items():
        if re.fullmatch(r"R p[1-9]\d*", source):
            cells = [s.strip() for s in text.split("|")]
            if (len(cells) != 4 or cells[:2] != ["ใบเสร็จรับเงิน", case]
                    or cells[3].casefold() != "all payments to date"):
                raise ReviewRequired("Receipt identity or cumulative payment scope is ambiguous")
            payment = re.fullmatch(rf"ยอดชำระ\s+({AMOUNT})\s+THB", cells[2])
            if not payment:
                raise ReviewRequired("Receipt amount or currency is ambiguous")
            receipts.append(money(payment[1]))
            continue
        slot = re.fullmatch(r"B p([1-9]\d*) (header|columns|subtotal|total|row [1-9]\d*)", source)
        if not slot:
            raise ReviewRequired(f"Unknown statement exhibit {source!r}")
        page = int(slot[1])
        attached.add(page)
        kind = slot[2]
        if kind == "header":
            cells = [s.strip() for s in text.split("|")]
            if len(cells) != 5 or cells[2:4] != [case, "THB"]:
                raise ReviewRequired("Statement member or currency mismatch")
            marker = re.fullmatch(r"Page (\d+) of (\d+)", cells[4], re.I)
            if not marker or int(marker[1]) != page or int(marker[2]) < page:
                raise ReviewRequired("Invalid statement page counter")
            headers[page] = int(marker[2])
        elif kind == "columns":
            if [v.strip() for v in text.split("|")] != ["Item List", "Total Amount", "Discount", "Total Net"]:
                raise ReviewRequired("Unknown statement column order")
            has_columns = True
        elif kind == "subtotal":
            subtotals.append((page, Charges.from_row(text)))
        elif kind == "total":
            totals.append(Charges.from_row(text))
        else:
            lines.append((page, Charges.from_row(text)))

    if not headers or set(headers) != attached or len(set(headers.values())) != 1:
        raise ReviewRequired("Missing or conflicting page headers")
    if not has_columns:
        raise ReviewRequired("Missing gross, discount and net column headings")
    count = next(iter(headers.values()))
    complete = len(headers) == count
    if len(totals) == 1:
        reported = totals[0]
        for page, subtotal in subtotals:
            result = reconcile_statement(subtotal, [value for p, value in lines if p == page], True, None)
            if result["reconciliation"] != "matches":
                raise ReviewRequired(f"Page {page} subtotal conflicts with detail")
    elif not totals and len(subtotals) == 1 and len(headers) == 1:
        reported = subtotals[0][1]
    else:
        raise ReviewRequired("Need a single unambiguous statement total")
    if len(receipts) > 1:
        raise ReviewRequired("Multiple cumulative receipts need an identified effective revision")
    return reconcile_statement(reported, [value for _, value in lines], complete,
                               receipts[0] if receipts else None)


def reconcile_gop(total: Decimal, items: list[tuple[str, Decimal]],
                  excluded_labels: set[str], balance: Decimal | None, can_draft: bool) -> dict:
    """Apply exclusions first, cap the remainder, then enforce submission readiness."""
    check_amount(total)
    if balance is not None:
        check_amount(balance)
    for _, value in items:
        check_amount(value)
    if not items or sum(value for _, value in items) != total:
        raise ReviewRequired("Itemized estimate disagrees with its stated total")
    normalized_exclusions = {label.strip().casefold() for label in excluded_labels}
    excluded = sum((value for label, value in items if label.strip().casefold() in normalized_exclusions), ZERO)
    eligible = min(total - excluded, balance) if balance is not None else None
    excess = total - excluded - eligible if eligible is not None else None
    ready = can_draft and eligible is not None
    return {"estimate_thb": total, "excluded_thb": excluded, "above_balance_thb": excess,
            "provisional_eligible_thb": eligible, "draft_request_thb": eligible if ready else None,
            "status": "READY FOR IPD REVIEW" if ready else "HOLD"}


def gop_fields(case: str, exhibits: dict[str, str]) -> dict:
    """Read one synthetic Lotus/River-style schedule, policy, plan and itemized estimate."""
    allowed = {"S p1", "N p1", "Q p1"}
    if not allowed.issubset(exhibits):
        raise ReviewRequired("Missing schedule, signed plan exhibit or estimate")
    scope = "Planned inpatient procedures in Thailand are covered during the membership period up to the available inpatient balance."
    required_docs = "Attach an itemized estimate and a signed treatment plan."
    clauses = []
    excluded = set()
    for source, wording in exhibits.items():
        if source in allowed:
            continue
        if not re.fullmatch(r"P §[1-9]\d*", source):
            raise ReviewRequired(f"Unrecognized exhibit {source!r}")
        wording = wording.strip()
        clauses.append(wording)
        if wording in {scope, required_docs}:
            continue
        exclusion = re.fullmatch(r"(.+?) (?:is|are) excluded\.", wording)
        if not exclusion:
            raise ReviewRequired(f"A policy clause needs interpretation at {source}")
        # This adapter matches the explicit excluded line label used in these two rulebooks.
        if exclusion[1] not in {"Personal convenience items", "Guest accommodation"}:
            raise ReviewRequired(f"Unmapped exclusion at {source}")
        excluded.add(exclusion[1].casefold())
    if scope not in clauses or required_docs not in clauses or not excluded:
        raise ReviewRequired("Required policy clauses are missing")

    schedule = [s.strip() for s in exhibits["S p1"].split("|")]
    if (len(schedule) != 5 or schedule[1] != f"member {case}"
            or schedule[3] != "no deductible, co-pay or waiting period"):
        raise ReviewRequired("Member, policy schedule or cost-sharing terms need review")
    known_exclusions = {"Mock Lotus schedule": {"personal convenience items"},
                        "Mock River schedule": {"guest accommodation"}}
    if known_exclusions.get(schedule[0]) != excluded:
        raise ReviewRequired("Policy exclusions do not match the supported schedule")
    period = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})", schedule[2])
    available = re.fullmatch(rf"available THB ({AMOUNT}|\[unreadable\])", schedule[4])
    if not period or not available:
        raise ReviewRequired("Coverage period, available benefit or currency needs review")
    balance = None if available[1] == "[unreadable]" else money(available[1])

    plan = [s.strip() for s in exhibits["N p1"].split("|")]
    if (len(plan) != 6 or plan[0] != case or not plan[1].endswith(", Thailand")
            or plan[3] != "inpatient" or not plan[4].startswith("planned ")):
        raise ReviewRequired("Planned service, member, admission type or territory needs review")
    try:
        start, end = date.fromisoformat(period[1]), date.fromisoformat(period[2])
        admission = date.fromisoformat(plan[2])
    except ValueError as error:
        raise ReviewRequired("Invalid service date or coverage period") from error
    if not start <= admission <= end:
        raise ReviewRequired("Admission falls outside the documented coverage period")
    if plan[5] not in {"clinician signature: present", "clinician signature: blank"}:
        raise ReviewRequired("Unrecognized signature evidence")

    quote = [s.strip() for s in exhibits["Q p1"].split("|")]
    if len(quote) != 4 or quote[:2] != [case, "same provider and admission"] or not quote[2].startswith("estimate THB: "):
        raise ReviewRequired("Estimate member, provider, scope or currency needs review")
    items = []
    # The fixture grammar separates lines with a comma and space; thousands separators have no space.
    for line in quote[2].removeprefix("estimate THB: ").split(", "):
        entry = re.fullmatch(rf"(.+?)\s+({AMOUNT})", line)
        if not entry:
            raise ReviewRequired("Unreadable estimate item")
        label = entry[1].casefold()
        if label not in {"procedure", "bed"} | excluded:
            raise ReviewRequired("Unclassified estimate line")
        items.append((label, money(entry[2])))
    if not quote[3].startswith("total "):
        raise ReviewRequired("No explicit total on estimate")
    return reconcile_gop(money(quote[3].removeprefix("total ")), items, excluded, balance,
                         plan[5] == "clinician signature: present")
