"""Local rehearsal transactions. The example has no bank, venue or payments connection."""

from decimal import Decimal
from uuid import uuid4

import psycopg

from app import discharge_store as store
from app import pattaya_case
from app.discharge_claim import discharge_packet_bytes
from app.hospital_platform import current_hospital
from app.staff_access import mode
from app.workspace_store import WorkspaceError, _writing


def seed(dsn, ident, evidence, raw, names):
    """Commit the example and its approved, submitted, confirmed starting point together."""
    with _writing(dsn) as db:
        evidence = dict(evidence, example_scenario=pattaya_case.SCENARIO)
        store.create(db, ident, evidence, raw, names)
        case = store.approve(db, ident, 1, "Fictional practice reviewer", None)
        packet = discharge_packet_bytes(case, raw)
        case = store.record(db, ident, 1, {
            "action": "submission", "workflow_version": 0, "reference": "SIM-PATTAYA-CLAIM",
            "channel": "Synthetic payer portal",
        }, "Fictional practice reviewer", None, None, None, packet, pattaya_rehearsal=True)
        return store.record(db, ident, 1, {
            "action": "reply", "workflow_version": case["workflow_version"], "reference": "SIM-PATTAYA-GUARANTEE",
            "confirmed": True, "outcome": "confirmed", "amount": "239000.00", "currency": "THB",
            "terms": pattaya_case.TERMS,
        }, "Fictional insurer", None, pattaya_case.final_decision(facility=evidence["facility"], encounter=evidence["encounter"]),
           "pattaya-final-guarantee.pdf", pattaya_rehearsal=True)


def require_case(case):
    if case.get("example_scenario") != pattaya_case.SCENARIO:
        raise WorkspaceError(404, "Pattaya practice revision not found.")
    if mode() != "local":
        hospital = current_hospital.get()
        if hospital is None or case.get("staff_practice_hospital") != hospital.slug:
            raise WorkspaceError(404, "Hospital settlement example not found.")


def apply(dsn, ident, revision, action, version, *, quote_id=None, bank_document=None, insurer_reference=None, actor=None, username=None):
    from app import pattaya_agents

    required_step = {"book_spot": "book", "book_forward": "book", "record_short_credit": "record_short",
                     "record_remittance": "top_up", "record_topup": "confirm_topup"}
    with psycopg.connect(dsn) as db:
        store._head(db, ident, revision)
        case = store._detail(db, ident, revision)
        require_case(case)
        reference = f"SIM-{ident}-{action.upper()}"
        if action in pattaya_case.CREDIT_DOCUMENTS and bank_document != pattaya_case.CREDIT_DOCUMENTS[action]:
            raise WorkspaceError(422, "Select the receiving-bank credit advice for this payment.")
        if insurer_reference is not None:
            insurer_reference = insurer_reference.strip()
            if action != "record_remittance" or not insurer_reference:
                raise WorkspaceError(422, "Supply an insurer reference only when recording its remittance.")
        if action == "record_remittance" and bank_document != "topup_instruction":
            raise WorkspaceError(422, "Select the insurer remittance instruction.")
        previous = next((event for event in case["events"]
                         if isinstance(event["data"], dict) and event["data"].get("reference") == reference), None)
        if previous:
            if action == "record_remittance" and (previous["kind"] != "topup_remittance"
                    or pattaya_agents.review(case)["remittance_status"] != "verified"):
                raise WorkspaceError(409, "The recorded remittance needs finance review.")
            if previous["kind"] == "topup_remittance" and previous["data"].get("insurer_reference") != insurer_reference:
                raise WorkspaceError(409, "A different remittance reference was already recorded. Reload its instruction.")
            if previous["kind"] == "fx_booking" and previous["data"].get("quote_id") != quote_id:
                raise WorkspaceError(409, "A different bank quote was already booked. Reload the saved ticket.")
            return case
        if case["workflow_version"] != version:
            raise WorkspaceError(409, "The ledger changed. Refresh the case to review the next step.")
        review = pattaya_agents.review(case)
        if review["next_action"] != required_step[action]:
            raise WorkspaceError(409, "That action is unavailable at the current settlement stage.")
        if action in {"book_spot", "book_forward"}:
            instrument = "spot" if action == "book_spot" else "forward"
            quote = next(offer for offer in review["quotes"] if offer["instrument"] == instrument)
            if quote_id != quote["quote_id"]:
                raise WorkspaceError(409, "The bank quote expired, changed or was not supplied. Refresh and confirm a current offer.")
            data = dict(quote, reference=reference, counterparty="Simulated partner bank",
                        bank_trade_id="SIM-FX-" + uuid4().hex, bank_status="confirmed")
            store.append_event(db, case, "fx_booking", data, actor or "Practice treasury desk", username)
            return store._detail(db, ident, revision)
        advice = pattaya_case.bank_message(ident, bank_document, hospital_slug=case.get("staff_practice_hospital"))
        if action == "record_remittance":
            if (advice.kind != "topup_instruction" or advice.case_id != ident or advice.encounter != case["encounter"]
                    or advice.beneficiary != case["facility"] or not advice.bank_reference.strip()
                    or advice.currency != "THB" or advice.gross_minor != review["outstanding_minor"] or advice.net_minor is not None):
                raise WorkspaceError(422, "The remittance instruction does not match this outstanding balance.")
            data = dict(advice.remittance_terms(), insurer_reference=insurer_reference)
            store.append_event(db, case, "topup_remittance", data, actor or "Practice insurer treasury", username,
                               advice.document(), "pattaya-topup-instruction.pdf")
            return store._detail(db, ident, revision)
        return _post_advice(db, case, action, advice, reference, actor, username)


def _post_advice(db, case, action, advice, reference, actor, username):
    decision = case["payer_decision"]
    due = decision["amount_minor"] - case["paid_by_currency"].get("THB", 0)
    if (advice.kind != pattaya_case.CREDIT_DOCUMENTS[action] or advice.case_id != case["id"]
            or advice.encounter != case["encounter"] or advice.beneficiary != case["facility"]
            or not advice.bank_reference.strip() or advice.currency != decision["currency"] or advice.gross_minor != due
            or advice.net_minor is None or not 0 < advice.net_minor <= due
            or (advice.fee_minor is not None and advice.gross_minor - advice.net_minor != advice.fee_minor)):
        raise WorkspaceError(422, "The receiving-bank advice does not match this claim and outstanding amount.")
    if any(e["data"].get("bank_reference") == advice.bank_reference for e in case["events"] if e["kind"] == "payment"):
        raise WorkspaceError(409, "The receiving-bank reference is already recorded.")
    if advice.fee_minor is None:
        notes = "The receiving bank confirmed the net credit. The cause of any difference is unverified."
    elif advice.fee_minor:
        notes = f"Receiving-bank advice documents a THB {Decimal(advice.fee_minor) / 100:,.2f} deduction. The insurer covers it."
    else:
        notes = "Insurer-funded top-up. The receiving bank confirms the full credit with zero deduction."
    return store.record(db, case["id"], case["revision"], {
        "action": "payment", "workflow_version": case["workflow_version"], "reference": reference,
        "currency": advice.currency, "amount": str(Decimal(advice.net_minor) / 100), "notes": notes,
        "bank_advice": {"bank_reference": advice.bank_reference, "value_date": advice.value_date,
                        "beneficiary": advice.beneficiary, "gross_minor": advice.gross_minor, "fee_minor": advice.fee_minor},
    }, actor or "Practice hospital finance", username, advice.document(), f"pattaya-{advice.kind}-advice.pdf", pattaya_rehearsal=True)


def preview_bank_document(case, kind):
    from app import pattaya_agents

    next_step = pattaya_agents.review(case)["next_action"]
    visible = {"record_short": ("instruction", "initial_credit"), "top_up": ("topup_instruction",),
               "confirm_topup": ("topup_credit",)}
    if kind not in visible.get(next_step, ()):
        raise WorkspaceError(404, "No pending bank document of this kind. Recorded receipts have their own sources.")
    return pattaya_case.bank_message(case["id"], kind, hospital_slug=case.get("staff_practice_hospital")).document()
