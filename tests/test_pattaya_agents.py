"""Exercise the Pattaya agents without a network connection or model key."""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from openai import OpenAIError

from app import pattaya_agents as agents
from app import pattaya_case


AI_ENV = {"OPENAI_API_KEY": "synthetic-test-key", "WORKSPACE_AUTH_MODE": "local",
          "WORKSPACE_ENABLE_PATTAYA_AI": "1"}


def claim(booking=None, paid=0):
    events = [{"kind": "reply", "data": {"terms": "Private notes must stay local."}}]
    if booking:
        events.append({"kind": "fx_booking", "data": agents.quotes()[booking]})
    if paid:
        events.append({"kind": "payment", "id": 50, "created_at": "2026-11-30T16:00:00+07:00",
                       "data": {"amount_minor": paid, "currency": "THB"}})
    return {
        "example_scenario": "pattaya_fx", "currency": "THB", "bill_total_minor": 23900000,
        "source_reported_cap_minor": 23900000, "source_reported_patient_share_minor": 0,
        "payer_decision": {"currency": "THB", "amount_minor": 23900000, "outcome": "confirmed", "terms": pattaya_case.TERMS},
        "events": events, "paid_by_currency": {"THB": paid} if paid else {}, "revision": 1,
        "workflow_version": len(events), "member": "PATIENT-PRIVATE", "id": "DISCHARGE-PRIVATE",
    }


def read(*names):
    return SimpleNamespace(status="completed", output=[
        SimpleNamespace(type="function_call", name=name, call_id="call-" + name, arguments="{}")
        for name in names
    ])


def decide(action):
    return SimpleNamespace(status="completed", output_text=json.dumps({"next_action": action}))


class PattayaAgentTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(agents, "time", return_value=900))

    def test_fixed_guarantee_spot_or_forward_and_separate_receipts(self):
        self.assertEqual(agents.review(claim())["next_action"], "book")
        for instrument, usd in [("spot", 702941), ("forward", 686782)]:
            with self.subTest(instrument=instrument):
                booked = agents.review(claim(instrument))
                quote = agents.quotes()[instrument]
                self.assertEqual(quote["usd_minor"], usd)
                self.assertEqual(quote["trade_date"], "2026-11-19")
                self.assertEqual(quote["value_date"], "2026-11-23" if instrument == "spot" else "2026-11-30")
                self.assertEqual(quote["hospital_due_date"], "2026-11-30")
                self.assertEqual(booked["paid_minor"], 0)
                self.assertEqual(booked["next_action"], "record_short")
                short = agents.review(claim(instrument, 23870000))
                self.assertEqual(short["next_action"], "top_up")
                self.assertEqual(short["guaranteed_minor"], 23900000)
                self.assertEqual(short["outstanding_minor"], 30000)
                self.assertEqual(short["shortfall_owner"], "insurer")
                self.assertEqual(short["patient_fx_minor"], 0)
                self.assertIn("THB 300 remains due from the insurer", short["trace"][-1]["summary"])
                self.assertIn("Bank credit #50 · recorded 30 Nov 2026, 09:00 UTC", short["trace"][-1]["evidence"])
                settled = agents.review(claim(instrument, 23900000))
                self.assertEqual(settled["next_action"], "complete")
                self.assertIsNone(settled["shortfall_owner"])

    def test_saved_tickets_and_legacy_tickets_keep_their_executed_price(self):
        original = agents.quotes()["forward"]
        original_schema = {"instrument", "rate_thb_per_usd", "trade_date", "value_date", "hospital_due_date", "usd_minor"}
        legacy_quote = agents._quote("forward", "34.80", original["trade_date"], original["value_date"], original["hospital_due_date"])
        for saved, expected in [(original, original), (legacy_quote, legacy_quote),
                                ({k: original[k] for k in original_schema}, legacy_quote)]:
            with self.subTest(version=saved.get("quote_id", "unversioned")):
                case = claim("forward", 23870000)
                case["events"][1]["data"] = saved
                with patch.dict(agents.BANK_TERMS, forward=("35.00", "2026-11-27")):
                    report = agents.review(case)
                self.assertEqual(report["booked_quote"], expected)
                self.assertEqual(report["booked_quote"]["usd_minor"], 686782)
                current = next(q for q in report["quotes"] if q["instrument"] == "forward")
                self.assertEqual(current["usd_minor"], 682857)
                self.assertNotEqual(current["quote_id"], report["booked_quote"]["quote_id"])
                self.assertIn("2026-11-30", report["trace"][1]["summary"])
                self.assertEqual(report["next_action"], "top_up")
                self.assertEqual((report["outstanding_minor"], report["shortfall_owner"]), (30000, "insurer"))

    def test_inconsistent_trade_ticket_requires_review(self):
        for key, invalid in [("instrument", "swap"), ("trade_date", None), ("value_date", "2026-11-18"),
                             ("rate_thb_per_usd", "NaN"), ("usd_minor", True), ("thb_minor", 239000),
                             ("sell_currency", "EUR"), ("buy_currency", "USD"), ("quote_id", "wrong")]:
            with self.subTest(key=key):
                case = claim("forward", 23870000)
                case["events"][1]["data"][key] = invalid
                report = agents.review(case)
                self.assertEqual(report["next_action"], "review")
                self.assertIsNone(report["booked_quote"])
                self.assertEqual(report["outstanding_minor"], 30000)

    def test_instruction_is_bound_to_one_claim_and_the_balance_at_issuance(self):
        case = claim("forward", agents.SHORT_CREDIT_MINOR)
        valid = pattaya_case.bank_message(case["id"], "topup_instruction").remittance_terms()
        instruction = {"kind": "topup_remittance", "data": valid, "filename": "instruction.pdf"}
        for changed in ({"instructed_minor": 30000.0}, {"instructed_minor": True}, {"bank_reference": "SIM-SEND-02-OTHER"},
                        {"reference": "SIM-OTHER-RECORD_REMITTANCE"}, {"currency": "USD"}, {"value_date": "2026-12-09"},
                        {"instructed_minor": 12345}, {"insurer_reference": "  "}):
            with self.subTest(changed=changed):
                case["events"].append(dict(instruction, data={**valid, **changed}))
                self.assertEqual(agents.review(case)["next_action"], "review")
                case["events"].pop()
        for label, events in {
            "duplicate": [*case["events"], instruction, instruction],
            "before first credit": [instruction, *case["events"]],
            "after booking but before credit": [*case["events"][:-1], instruction, case["events"][-1]],
            "no archived source": [*case["events"], dict(instruction, filename=None)],
            "empty payload": [*case["events"], dict(instruction, data={})],
        }.items():
            with self.subTest(label=label):
                result = agents.review({**case, "events": events})
                self.assertEqual((result["remittance_status"], result["next_action"]), ("conflict", "review"))
        self.assertEqual(agents.review(case)["remittance_status"], "absent")
        case["events"].append(instruction)
        self.assertEqual(agents.review(case)["next_action"], "confirm_topup")

    def test_unconfirmed_fee_terms_preserve_numeric_balance_and_withhold_liability(self):
        for terms in (None, "Fee allocation will be agreed separately.", pattaya_case.TERMS + " Subject to amendment."):
            with self.subTest(terms=terms):
                case = claim("spot", 23870000)
                case["payer_decision"]["terms"] = terms
                result = agents.review(case)
                self.assertEqual(result["guaranteed_minor"], 23900000)
                self.assertEqual(result["outstanding_minor"], 30000)
                self.assertIsNone(result["patient_fx_minor"])
                self.assertIsNone(result["shortfall_owner"])
                self.assertEqual(result["next_action"], "review")

    def test_unexpected_evidence_needs_finance_review(self):
        examples = []
        duplicate = claim("spot")
        duplicate["events"].append(duplicate["events"][-1])
        examples.append(duplicate)
        changed_price = claim("spot")
        changed_price["events"][-1]["data"]["rate_thb_per_usd"] = "1"
        examples.append(changed_price)
        unapproved = claim()
        unapproved["payer_decision"]["outcome"] = "declined"
        examples.append(unapproved)
        mixed = claim("forward", 23870000)
        mixed["paid_by_currency"]["USD"] = 30000
        examples.append(mixed)
        examples.extend([claim("spot", 4500), claim("spot", 24000000)])
        for case in examples:
            with self.subTest(case=case):
                self.assertEqual(agents.review(case)["next_action"], "review")

    @patch("app.pattaya_agents.OpenAI")
    def test_normal_cases_and_missing_consent_cannot_call_model(self, provider):
        generic = claim()
        generic.pop("example_scenario")
        with self.assertRaises(ValueError):
            agents.review(generic, use_model=True)
        with patch.dict(os.environ, AI_ENV, clear=True):
            self.assertEqual(agents.review(claim())["model_review"]["status"], "not_requested")
            for field, value in [("WORKSPACE_AUTH_MODE", "staff"), ("OPENAI_API_KEY", ""),
                                 ("WORKSPACE_ENABLE_PATTAYA_AI", "0")]:
                with patch.dict(os.environ, {field: value}):
                    result = agents.review(claim(), use_model=True)
                    self.assertFalse(result["model_enabled"])
                    self.assertEqual(result["model_review"]["status"], "unavailable")
        provider.assert_not_called()

    @patch.dict(os.environ, AI_ENV, clear=True)
    @patch("app.pattaya_agents.OpenAI")
    def test_evidence_handoffs_use_only_whitelisted_financial_fields(self, provider):
        create = provider.return_value.__enter__.return_value.responses.create
        create.side_effect = [read("read_guarantee"), read("compare_funding"), decide("book")]
        report = agents.review(claim(), use_model=True)
        self.assertEqual(report["model_review"]["status"], "reviewed")
        self.assertEqual(report["model_review"]["tools"], ["read_guarantee", "compare_funding"])
        self.assertEqual(create.call_count, 3)
        provider.assert_called_once_with(timeout=12, max_retries=0)
        for call in create.call_args_list:
            self.assertIs(call.kwargs["store"], False)
            self.assertNotIn("PATIENT-PRIVATE", str(call.kwargs))
            self.assertNotIn("DISCHARGE-PRIVATE", str(call.kwargs))
            self.assertNotIn("Private notes", str(call.kwargs))
        outbound = [item for item in create.call_args.kwargs["input"]
                    if isinstance(item, dict) and item.get("type") == "function_call_output"]
        self.assertEqual(len(outbound), 2)
        self.assertEqual(json.loads(outbound[0]["output"])["amount_minor"], 23900000)
        quote = json.loads(outbound[1]["output"])["quotes"][1]
        self.assertEqual(quote, agents.quotes()["forward"])

    @patch.dict(os.environ, AI_ENV, clear=True)
    @patch("app.pattaya_agents.OpenAI")
    def test_only_corroborated_model_decisions_are_shown(self, provider):
        create = provider.return_value.__enter__.return_value.responses.create
        ledger = claim("forward", 23870000)
        for replies, verdict in [
            ([read("reconcile_credits"), decide("top_up")], "reviewed"),
            ([read("reconcile_credits"), decide("complete")], "unavailable"),
            ([read("book_trade")], "unavailable"),
            ([read("read_guarantee"), read("read_guarantee")], "unavailable"),
            ([read("reconcile_credits"), SimpleNamespace(status="completed", output_text="invalid")], "unavailable"),
            ([OpenAIError("provider unavailable")], "unavailable"),
        ]:
            with self.subTest(verdict=verdict, replies=replies):
                create.side_effect = replies
                report = agents.review(ledger, use_model=True)
                self.assertEqual(report["next_action"], "top_up")
                self.assertEqual(report["paid_minor"], 23870000)
                self.assertEqual(report["outstanding_minor"], 30000)
                self.assertEqual(report["model_review"]["status"], verdict)
