"""Read-only agents for the fictional Pattaya THB guarantee and treasury rehearsal."""

import hashlib
import json
import os
import re
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from time import time

from openai import OpenAI, OpenAIError

from app.pattaya_case import TERMS, bank_message


GUARANTEE_MINOR = 23_900_000
SHORT_CREDIT_MINOR = 23_870_000
TRADE_DATE = "2026-11-19"
HOSPITAL_DUE_DATE = "2026-11-30"
BANK_TERMS = {"spot": ("34.00", "2026-11-23"), "forward": ("34.80", HOSPITAL_DUE_DATE)}
QUOTE_WINDOW_SECONDS = 300


def _quote(instrument, rate, trade_date, value_date, due_date, expires_at=None):
    terms = dict(instrument=instrument, rate_thb_per_usd=rate, trade_date=trade_date,
                 value_date=value_date, hospital_due_date=due_date, buy_currency="THB",
                 thb_minor=GUARANTEE_MINOR, sell_currency="USD",
                 usd_minor=int((GUARANTEE_MINOR / Decimal(rate)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    if expires_at is not None:
        terms["expires_at"] = expires_at
    payload = json.dumps(terms, sort_keys=True, separators=(",", ":")).encode()
    prefix = "v2-" if expires_at is not None else "v1-"
    terms["quote_id"] = prefix + hashlib.sha256(payload).hexdigest()
    return terms


def quotes():
    """All workers rotate the simulated quote sheet on the same UTC boundary."""
    window_end = (int(time()) // QUOTE_WINDOW_SECONDS + 1) * QUOTE_WINDOW_SECONDS
    expires_at = datetime.fromtimestamp(window_end, UTC).isoformat()
    return {instrument: _quote(instrument, rate, TRADE_DATE, value_date, HOSPITAL_DUE_DATE, expires_at)
            for instrument, (rate, value_date) in BANK_TERMS.items()}


def model_enabled():
    return (os.getenv("WORKSPACE_AUTH_MODE") == "local"
            and os.getenv("WORKSPACE_ENABLE_PATTAYA_AI") == "1" and bool(os.getenv("OPENAI_API_KEY")))


def _thb(minor):
    return f"THB {Decimal(minor) / 100:,.2f}".removesuffix(".00")


def _guarantee(case):
    decision = case.get("payer_decision") or {}
    return (case.get("currency") == decision.get("currency") == "THB"
            and case.get("bill_total_minor") == case.get("source_reported_cap_minor") == GUARANTEE_MINOR
            and case.get("source_reported_patient_share_minor") == 0
            and decision.get("outcome") == "confirmed" and decision.get("amount_minor") == GUARANTEE_MINOR)


def _funding(case):
    """Read the saved ticket. A later quote sheet cannot reprice an existing booking."""
    bookings = [event["data"] for event in case["events"] if event["kind"] == "fx_booking"]
    if not bookings:
        return None, True
    if len(bookings) != 1:
        return None, False
    saved = bookings[0]
    if not isinstance(saved, dict):
        return None, False
    instrument, rate = saved.get("instrument"), saved.get("rate_thb_per_usd")
    if (instrument not in ("spot", "forward") or not isinstance(rate, str)
            or not re.fullmatch(r"[0-9]{1,10}(?:\.[0-9]{1,10})?", rate) or Decimal(rate) <= 0):
        return None, False
    try:
        trade, value, due = (date.fromisoformat(saved[key]) for key in ("trade_date", "value_date", "hospital_due_date"))
    except (KeyError, TypeError, ValueError):
        return None, False
    if (trade.isoformat() != TRADE_DATE or due.isoformat() != HOSPITAL_DUE_DATE
            or not trade <= value <= due or (instrument == "forward" and trade == value)):
        return None, False
    expires_at = saved.get("expires_at")
    if "expires_at" in saved and (not isinstance(expires_at, str) or
            not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", expires_at)):
        return None, False
    ticket = _quote(instrument, rate, trade.isoformat(), value.isoformat(), due.isoformat(), expires_at)
    # Original tickets had an implicit buy-THB / sell-USD direction and THB 239,000 notional.
    versioned = {"quote_id", "buy_currency", "sell_currency", "thb_minor"}
    has_version = bool(versioned.intersection(saved))
    if has_version and type(saved.get("thb_minor")) is not int:
        return None, False
    fields = ticket if has_version else ticket.keys() - versioned
    if type(saved.get("usd_minor")) is not int or any(saved.get(key) != ticket[key] for key in fields):
        return None, False
    return ticket, True


def _latest_event(case, kind, label):
    events = [row for row in case["events"] if row["kind"] == kind]
    if not events:
        return f"No {label.lower()} recorded"
    last = events[-1]
    stamp = last.get("created_at")
    reference = f" #{last['id']}" if last.get("id") is not None else ""
    result = f"{label}{reference}"
    if not stamp:
        return result
    try:
        instant = stamp if isinstance(stamp, datetime) else datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return result
    if instant.tzinfo is None:
        return result
    return result + " · recorded " + instant.astimezone(UTC).strftime("%d %b %Y, %H:%M UTC")


def _remittance_status(case):
    """Verify one case-bound instruction against the balance when it was recorded."""
    instruction = None
    booking_seen = False
    credit_count = 0
    first_credit = {}
    for event in case["events"]:
        if event["kind"] == "fx_booking":
            booking_seen = True
        elif event["kind"] == "payment":
            credit_count += 1
            if credit_count == 1:
                first_credit = event["data"]
        elif event["kind"] == "topup_remittance":
            # Use receipt history at issuance. A later top-up does not change that balance.
            if (instruction is not None or not booking_seen or credit_count != 1
                    or first_credit.get("currency") != "THB" or first_credit.get("amount_minor") != SHORT_CREDIT_MINOR
                    or not event.get("filename") or not isinstance(event["data"], dict)):
                return "conflict"
            instruction = event["data"]
    if instruction is None:
        return "absent"
    expected = bank_message(case["id"], "topup_instruction").remittance_terms()
    if (type(instruction.get("instructed_minor")) is not int
            or instruction["instructed_minor"] != GUARANTEE_MINOR - first_credit["amount_minor"]
            or any(instruction.get(key) != value for key, value in expected.items())):
        return "conflict"
    reference = instruction.get("insurer_reference")
    if reference is not None and (not isinstance(reference, str) or not 1 <= len(reference.strip()) <= 100):
        return "conflict"
    return "verified"


def _settlement_step(verified, booked, paid, remittance):
    if not verified or paid < 0 or paid > GUARANTEE_MINOR:
        return "review"
    if paid == GUARANTEE_MINOR:
        return "complete"
    if not paid:
        return "record_short" if booked else "book"
    if booked and paid == SHORT_CREDIT_MINOR:
        return "confirm_topup" if remittance else "top_up"
    return "review"


TOOL_DESCRIPTIONS = {
    "read_guarantee": "Read the insurer's verified THB commitment, approved patient FX share and guarantee check.",
    "compare_funding": "Read the two simulated bank quotes, their USD costs and the selected funding instrument.",
    "reconcile_credits": "Read the recorded THB principal, outstanding balance and credit currency check.",
}
ACTIONS = {
    "book": ("compare_funding", "Choose a simulated bank quote to fund the approved hospital payment."),
    "record_short": ("reconcile_credits", "The funding is booked. Record the separate simulated hospital credit."),
    "top_up": ("reconcile_credits", "The insurer owes the THB 300 top-up. The patient owes zero for FX."),
    "confirm_topup": ("reconcile_credits", "The insurer recorded its remittance. Confirm the separate hospital credit advice."),
    "complete": ("reconcile_credits", "The recorded THB credits cover the insurer’s guarantee in full."),
    "review": ("reconcile_credits", "Review the records with finance before another settlement step."),
}
INSTRUCTIONS = (
    "Inspect a fictional fixed-baht hospital guarantee. You may only use the supplied read-only tools. "
    "Read the evidence needed to identify the coordinator's next simulated step. Read the guarantee "
    "and compare available funding for an unbooked claim. When funding is booked or credits exist, "
    "reconcile credits. A booking alone is no hospital credit. Select book for an unfunded, unpaid guarantee, "
    "record_short for a booked but unpaid claim, top_up for the expected first credit with a balance, "
    "confirm_topup for a recorded insurer remittance awaiting the hospital credit, complete for exact settlement, and review for conflicting evidence. Monetary minor units are hundredths. "
    "No trades, payments, financial advice or patient contact."
)


def _model_assessment(facts, next_action):
    # Only the fixed synthetic numeric/enumerated projection reaches this boundary.
    # A tool call reads the same snapshot throughout the assessment.
    required = {"read_guarantee", "compare_funding"} if next_action == "book" else {"reconcile_credits"}
    if next_action == "review":
        required = set(TOOL_DESCRIPTIONS)
    tools_used = []
    unavailable = dict(status="unavailable", focus=None,
                       summary="The optional model review is unavailable. The local checks remain available.",
                       tools=tools_used)
    if not model_enabled():
        return unavailable
    history = [{"role": "user", "content": json.dumps({
        "simulated_bank_booking_present": facts["compare_funding"]["booking"] is not None,
        "hospital_credits_present": facts["reconcile_credits"]["paid_minor"] > 0,
    })}]
    settings = dict(model=os.getenv("OPENAI_MODEL") or "gpt-6.2-sol", instructions=INSTRUCTIONS,
                    store=False, max_output_tokens=650, include=["reasoning.encrypted_content"])
    try:
        with OpenAI(timeout=12, max_retries=0) as client:
            for _ in range(2):
                remaining = {name: description for name, description in TOOL_DESCRIPTIONS.items() if name not in tools_used}
                tools = [dict(type="function", name=name, description=description, strict=True,
                              parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False})
                         for name, description in remaining.items()]
                answer = client.responses.create(input=list(history), tools=tools, tool_choice="required", **settings)
                if answer.status != "completed":
                    return unavailable
                calls = [item for item in answer.output if item.type == "function_call"]
                if not calls or len(calls) > len(remaining):
                    return unavailable
                history.extend(answer.output)
                for call in calls:
                    if call.name not in remaining or call.name in tools_used or json.loads(call.arguments) != {}:
                        return unavailable
                    tools_used.append(call.name)
                    history.append(dict(type="function_call_output", call_id=call.call_id,
                                        output=json.dumps(facts[call.name])))
                if required.issubset(tools_used):
                    break
            if not required.issubset(tools_used):
                return unavailable
            schema = {"type": "object", "properties": {"next_action": {"type": "string", "enum": list(ACTIONS)}},
                      "required": ["next_action"], "additionalProperties": False}
            final = client.responses.create(input=history, text={"format": {"type": "json_schema",
                "name": "settlement_step", "strict": True, "schema": schema}}, **settings)
            # A model can corroborate the decision, never change it or publish free-form claims.
            if final.status != "completed" or json.loads(final.output_text) != {"next_action": next_action}:
                return unavailable
    except (OpenAIError, AttributeError, TypeError, ValueError):
        return unavailable
    focus, summary = ACTIONS[next_action]
    return dict(status="reviewed", focus=focus, summary=summary, tools=tools_used)


def review(case, *, use_model=False):
    """Compute a decision from the supplied immutable revision and its recorded events."""
    if case.get("example_scenario") != "pattaya_fx":
        raise ValueError("The Pattaya agents require the fictional Pattaya example.")
    guaranteed = _guarantee(case)
    # This rehearsal recognizes only its authored guarantee. Other wording needs a sourced review.
    fees_verified = guaranteed and case["payer_decision"].get("terms") == TERMS
    patient_fx_minor = 0 if fees_verified else None
    booking, valid_booking = _funding(case)
    booked = booking["instrument"] if booking else None
    prices = list(quotes().values())
    amounts = case["paid_by_currency"]
    paid = amounts.get("THB", 0)
    valid_currency = set(amounts) <= {"THB"}
    due = GUARANTEE_MINOR if guaranteed else 0
    outstanding = max(0, due - paid)
    remittance = _remittance_status(case)
    verified = fees_verified and valid_booking and valid_currency and remittance != "conflict"
    action = _settlement_step(verified, booked, paid, remittance == "verified")
    owner = "insurer" if fees_verified and valid_currency and outstanding else None

    trace = [
        dict(agent="Guarantee", status="verified" if fees_verified else "review",
             summary=("The insurer guarantees THB 239,000 net. It covers FX differences and bank fees."
                      if fees_verified else "The guarantee confirms the THB amount. Review who covers FX differences and bank fees."
                      if guaranteed else "The current guarantee, patient share or payer decision needs review."),
             evidence=f"Guarantee letter p. 1 · final bill p. 1 · {_latest_event(case, 'reply', 'Payer decision')}"),
        dict(agent="Funding", status=("review" if not valid_booking else "booked" if booked else "quoted"),
             summary=("The recorded booking terms are inconsistent. Review the funding record."
                      if not valid_booking else f"The simulated {booked} trade delivers THB 239,000 on {booking['value_date']}."
                      if booked else "Compare the two simulated USD-to-THB quotes before recording a booking."),
             evidence=(_latest_event(case, "fx_booking", "Funding booking") if booked
                       else f"Simulated bank prices for {TRADE_DATE}")),
        dict(agent="Hospital receipts", status=action,
             summary=(f"Hospital credits total {_thb(paid)}. " + (
                 "The saved remittance instruction needs finance review." if remittance == "conflict"
                 else "Finance review is required before another settlement step." if action == "review"
                 else f"{_thb(outstanding)} remains due from the insurer." if outstanding
                 else "The THB guarantee is settled in full.")),
             evidence=f"Hospital credit ledger · {_latest_event(case, 'payment', 'Bank credit')}"),
    ]
    model_review = dict(status="not_requested", focus=None, summary="", tools=[])
    if use_model:
        facts = {
            "read_guarantee": dict(verified=fees_verified, amount_minor=due, currency="THB", patient_fx_minor=patient_fx_minor),
            "compare_funding": dict(quotes=prices, booking=booked, booked_quote=booking, valid_booking=valid_booking),
            "reconcile_credits": dict(paid_minor=paid, outstanding_minor=outstanding, currency="THB",
                                     valid_currency=valid_currency, shortfall_owner=owner, remittance_status=remittance,
                                     expected_first_credit_minor=SHORT_CREDIT_MINOR),
        }
        model_review = _model_assessment(facts, action)
    return dict(revision=case["revision"], workflow_version=case["workflow_version"], hospital_due_date=HOSPITAL_DUE_DATE,
                guaranteed_minor=due, paid_minor=paid, outstanding_minor=outstanding, patient_fx_minor=patient_fx_minor,
                shortfall_owner=owner, booking=booked, booked_quote=booking, quotes=prices, short_credit_minor=SHORT_CREDIT_MINOR,
                next_action=action, remittance_status=remittance, trace=trace, model_enabled=model_enabled(), model_review=model_review)
