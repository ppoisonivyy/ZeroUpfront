"""Validate manually recorded payer and hospital events for one submitted case revision."""
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO

from pypdf import PdfReader


DISPOSITIONS = {"partial", "denied", "authorized", "guaranteed"}


def projection(events, approved):
    status = "not_sent"
    admission = None
    deposit = None
    for event in events:
        action, data = event["kind"], event["data"]
        if action == "submission":
            status = "submitted"
        elif action == "reply":
            status = data["outcome"]
            admission = deposit = None
        elif action == "supplement":
            status = "supplement_sent"
        elif action == "admission":
            admission, deposit = data, None
        elif action == "deposit":
            deposit = data
    actions = []
    if approved:
        if status == "not_sent":
            actions.append("submission")
        else:
            actions.append("reply")
        if status == "query":
            actions.append("supplement")
        if status in DISPOSITIONS:
            actions.append("admission")
        if admission:
            actions.append("deposit")
    return dict(insurer_status=status, workflow_version=len(events), allowed_actions=actions,
                latest_event_kind=events[-1]["kind"] if events else None, events=events,
                admission_check=admission, deposit_decision=deposit)


def _required(fields, key, limit=2000):
    value = fields.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Enter a value for {key.replace('_', ' ')} (up to {limit} characters).")
    return value.strip()


def _money(fields, required):
    amount, currency = fields.get("amount"), fields.get("currency")
    currency = currency.upper() if isinstance(currency, str) else currency
    if amount in (None, ""):
        if required:
            raise ValueError("Enter the amount recorded on the decision.")
        return {}
    try:
        value = Decimal(amount)
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid monetary amount.") from None
    if not value.is_finite() or value < 0 or value > 999999999999 or value.as_tuple().exponent < -2:
        raise ValueError("Enter a nonnegative amount with at most two decimal places.")
    if currency not in {"THB", "USD"}:
        raise ValueError("Specify THB or USD for the recorded amount.")
    return {"amount": format(value, "f"), "currency": currency}


def _iso(value):
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("Enter dates in YYYY-MM-DD format.")
    return value


def _letter(fields):
    terms = {}
    for key in ("covered_member", "covered_procedure", "facility", "patient_share"):
        if fields.get(key):
            terms[key] = _required(fields, key, 300)
    for key in ("valid_from", "valid_until"):
        if fields.get(key):
            terms[key] = _iso(fields[key])
    if terms.get("valid_from", "") > terms.get("valid_until", "9999-12-31"):
        raise ValueError("The letter expiry precedes its effective date.")
    return terms


def _admission(case, fields):
    norm = lambda value: " ".join(value.split()).casefold()
    date_text = _iso(_required(fields, "actual_admission_date", 10))
    data = {"actual_procedure": _required(fields, "actual_procedure", 300),
            "actual_member": _required(fields, "actual_member", 200), "actual_admission_date": date_text,
            "notes": _required(fields, "notes"), "letter_confirmed": bool(fields.get("letter_confirmed"))}
    if fields.get("actual_facility"):
        data["actual_facility"] = _required(fields, "actual_facility", 300)
    money = _money({"amount": fields.get("actual_amount"), "currency": fields.get("currency")}, False)
    if money:
        data.update(actual_amount=money["amount"], currency=money["currency"])
    reply = next(event for event in reversed(case["events"]) if event["kind"] == "reply")
    letter = reply["data"]
    different = [key for key in ("member", "procedure", "admission_date") if norm(case[key]) != norm(data["actual_" + key])]
    unknown = []
    for term, actual in (("covered_member", "actual_member"), ("covered_procedure", "actual_procedure"),
                         ("facility", "actual_facility")):
        if not letter.get(term) or not data.get(actual):
            unknown.append(term)
        elif norm(letter[term]) != norm(data[actual]):
            different.append(term)
    for key in ("valid_from", "valid_until"):
        if not letter.get(key):
            unknown.append(key)
    if date_text < letter.get("valid_from", "") or date_text > letter.get("valid_until", "9999-12-31"):
        different.append("validity")
    if "amount" not in letter or not money:
        unknown.append("amount")
    elif money["currency"] != letter["currency"] or Decimal(money["amount"]) > Decimal(letter["amount"]):
        different.append("amount_or_currency")
    if not data["letter_confirmed"]:
        unknown.append("staff_check_of_letter_terms")
    if not letter.get("patient_share"):
        unknown.append("patient_share")
    comparable = money and letter.get("currency") == money["currency"] and "amount" in letter
    if comparable:
        # Amount above the letter ceiling only. Deductibles or excluded services can add to the patient share.
        data["remaining_estimated_amount"] = str(max(Decimal(0), Decimal(money["amount"]) - Decimal(letter["amount"])))
    data["coverage_scope"] = {"partial": "partial", "guaranteed": "written_guarantee"}.get(letter["outcome"], "no_guarantee")
    if letter.get("patient_share"):
        data["patient_share_terms"] = letter["patient_share"]
    if letter["outcome"] in {"denied", "authorized"}:
        outcome = "no_guarantee"
    else:
        settled = "partial_scope" if letter["outcome"] == "partial" else "matched"
        outcome = "mismatch" if different else ("needs_review" if unknown else settled)
    return dict(data, payer_event_id=reply["id"], outcome=outcome, differences=different, uncertainties=unknown)


def validate_event(case, action, fields, attached):
    if action not in case["allowed_actions"]:
        raise ValueError("This action is unavailable at the current stage of this revision.")
    if action in {"reply", "supplement"}:
        if not attached or not fields.get("confirmed"):
            raise ValueError("Attach the original PDF and confirm its identity and contents for this revision.")
    elif attached:
        raise ValueError("This action does not accept an attachment.")
    if action == "hold":
        category = fields.get("category")
        if category not in {"eligibility", "network", "consent", "policy", "medical", "timing", "billing", "other"}:
            raise ValueError("Choose a case hold reason.")
        return {"category": category, "notes": _required(fields, "notes")}
    if action == "resolve_hold":
        hold_id = fields.get("hold_id")
        if not any(item["id"] == hold_id for item in case["open_holds"]):
            raise ValueError("Choose an open hold on this case.")
        return {"hold_id": hold_id, "notes": _required(fields, "notes")}
    if action == "submission":
        return {"reference": _required(fields, "reference", 200), "channel": _required(fields, "channel", 100)}
    if action == "reply":
        outcome = fields.get("outcome")
        if outcome not in DISPOSITIONS | {"query"}:
            raise ValueError("Choose a supported response from the payer.")
        return {"outcome": outcome, "reference": _required(fields, "reference", 200),
                "terms": _required(fields, "terms"), **_money(fields, outcome in {"partial", "guaranteed"}),
                **_letter(fields)}
    if action == "supplement":
        return {"reference": _required(fields, "reference", 200), "notes": _required(fields, "notes")}
    if action == "admission":
        return _admission(case, fields)
    outcome = fields.get("outcome")
    if outcome not in {"waived", "required", "reduced", "deferred"}:
        raise ValueError("Choose the hospital's deposit decision.")
    data = _money(fields, outcome in {"required", "reduced"})
    if outcome in {"required", "reduced"} and Decimal(data["amount"]) == 0:
        raise ValueError("Use waived to record a zero deposit.")
    if outcome == "waived" and "amount" in data and Decimal(data["amount"]) != 0:
        raise ValueError("A waived deposit must have a zero amount.")
    return {"outcome": outcome, "notes": _required(fields, "notes"), **data}


def validate_attachment(raw, filename):
    if (not filename or len(filename) > 160 or not filename.isprintable()
            or "/" in filename or "\\" in filename or not filename.lower().endswith(".pdf")):
        raise ValueError("Choose a PDF with a short filename and no directories.")
    if not raw.startswith(b"%PDF-"):
        raise ValueError("Attach a readable PDF.")
    try:
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 200:
            raise ValueError
    except Exception as exc:
        raise ValueError("Attach an unencrypted PDF containing 1–200 pages.") from exc
