"""Local rehearsal transactions. The example has no bank, venue or payments connection."""

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


def apply(dsn, ident, revision, action, version, *, actor=None, username=None):
    from app import pattaya_agents

    required_step = {"book_spot": "book", "book_forward": "book", "record_short_credit": "record_short", "record_topup": "top_up"}
    with psycopg.connect(dsn) as db:
        store._head(db, ident, revision)
        case = store._detail(db, ident, revision)
        require_case(case)
        reference = f"SIM-{ident}-{action.upper()}"
        if any(event["data"].get("reference") == reference for event in case["events"]):
            return case
        if case["workflow_version"] != version:
            raise WorkspaceError(409, "The ledger changed. Refresh the case to review the next step.")
        review = pattaya_agents.review(case)
        if review["next_action"] != required_step[action]:
            raise WorkspaceError(409, "That action is unavailable at the current settlement stage.")
        if action in {"book_spot", "book_forward"}:
            instrument = "spot" if action == "book_spot" else "forward"
            quote = next(offer for offer in review["quotes"] if offer["instrument"] == instrument)
            data = dict(quote, reference=reference, counterparty="Simulated partner bank")
            store.append_event(db, case, "fx_booking", data, actor or "Practice treasury desk", username)
            return store._detail(db, ident, revision)
        first_credit = action == "record_short_credit"
        return store.record(db, ident, revision, {
            "action": "payment", "workflow_version": version, "reference": reference, "currency": "THB",
            "amount": "238700.00" if first_credit else "300.00",
            "notes": ("Simulated beneficiary credit. THB 300 remains due from the insurer."
                      if first_credit else "Simulated insurer-funded top-up credited to the hospital."),
        }, actor or "Practice hospital finance", username, None, None, pattaya_rehearsal=True)
