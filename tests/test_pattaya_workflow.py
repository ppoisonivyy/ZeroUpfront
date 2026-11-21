"""Exercise both funding routes and the synthetic THB settlement boundary through HTTP."""
import os
import shutil
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import replace
from io import BytesIO
from unittest.mock import patch

import psycopg
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import pattaya_agents, pattaya_case
from app.discharge_claim import evaluate_discharge
from app.workspace_api import app
from bench.case_revision import temporary_database


class PattayaExhibitsTests(unittest.TestCase):
    def test_originals_support_a_fixed_baht_guarantee(self):
        meta, originals, filenames = pattaya_case.exhibits()
        report = evaluate_discharge(dict(meta, id="D-TEST"), originals, filenames, _pattaya_fixture=True)
        self.assertTrue(all(len(PdfReader(BytesIO(raw)).pages) == 1 for raw in originals.values()))
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["letter_kind"], "initial_gop")
        self.assertEqual(report["currency"], "THB")
        self.assertEqual(report["bill_total_minor"], report["source_reported_cap_minor"])
        self.assertEqual((report["source_reported_cap_minor"], report["source_reported_patient_share_minor"]),
                         (23_900_000, 0))


    def test_matching_upload_metadata_cannot_enable_fixture_screening(self):
        meta, originals, filenames = pattaya_case.exhibits()
        report = evaluate_discharge(dict(meta, id="D-GENERIC", example_scenario="pattaya_fx"), originals, filenames)
        self.assertEqual(report["status"], "needs_review")
        self.assertIn("clinical_review", {finding["code"] for finding in report["findings"]})


@unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires disposable PostgreSQL")
class PattayaWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(pattaya_agents, "time", return_value=900))

    @classmethod
    def setUpClass(cls):
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        dsn = stack.enter_context(temporary_database())
        stack.enter_context(patch.dict(os.environ, DATABASE_URL=dsn, WORKSPACE_AUTH_MODE="local", WORKSPACE_ENABLE_PATTAYA_AI="0"))
        cls.client = stack.enter_context(TestClient(app))

    def new(self, scenario="pattaya_fx"):
        response = self.client.post("/api/discharge/examples/" + scenario)
        self.assertEqual(response.status_code, 201, response.text)
        case = response.json()
        return "/api/discharge/" + case["id"], case

    def action(self, path, action, version, revision=1, **overrides):
        if action in {"book_spot", "book_forward"}:
            overrides.setdefault("quote_id", pattaya_agents.quotes()[action.removeprefix("book_")]["quote_id"])
        if action in pattaya_case.CREDIT_DOCUMENTS:
            overrides.setdefault("bank_document", pattaya_case.CREDIT_DOCUMENTS[action])
        if action == "record_remittance":
            overrides.setdefault("bank_document", "topup_instruction")
        return self.client.post(path + "/pattaya/actions", headers={"If-Match": f'"{revision}"'},
                                json={"action": action, "confirmed": True, "workflow_version": version, **overrides})

    def review(self, path):
        result = self.client.get(path + "/pattaya", params={"revision": 1})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_booking_requires_the_displayed_terms_and_keeps_them_after_repricing(self):
        path, _ = self.new()
        original = next(q for q in self.review(path)["quotes"] if q["instrument"] == "forward")
        with patch.dict(pattaya_agents.BANK_TERMS, forward=("35.00", "2026-11-30")):
            self.assertEqual(self.action(path, "book_forward", 2, quote_id=original["quote_id"]).status_code, 409)
            self.assertEqual(self.action(path, "book_forward", 2, quote_id=None).status_code, 409)
            refreshed = self.review(path)
            self.assertIsNone(refreshed["booking"])
            fresh = next(q for q in refreshed["quotes"] if q["instrument"] == "forward")
            accepted = self.action(path, "book_forward", 2, quote_id=fresh["quote_id"])
            self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(self.action(path, "book_forward", 2, quote_id=fresh["quote_id"]).status_code, 200)
        self.assertEqual(self.action(path, "book_forward", 2, quote_id=original["quote_id"]).status_code, 409)
        self.assertEqual(self.action(path, "record_short_credit", 3).status_code, 200)
        report = self.review(path)
        self.assertEqual(report["booked_quote"], fresh)
        self.assertEqual(report["next_action"], "top_up")
        self.assertEqual(report["outstanding_minor"], 30000)
        self.assertEqual(self.action(path, "record_remittance", 4).status_code, 200)
        self.assertEqual(self.action(path, "record_topup", 5).json()["settlement_status"], "paid")

    def test_expired_quote_and_recovery_when_booking_response_is_lost(self):
        path, _ = self.new()
        with patch.object(pattaya_agents, "time", return_value=599):
            first = self.review(path)["quotes"][0]
        with patch.object(pattaya_agents, "time", return_value=600):
            expired = self.action(path, "book_spot", 2, quote_id=first["quote_id"])
            self.assertEqual(expired.status_code, 409)
            self.assertEqual(self.review(path)["next_action"], "book")
            fresh = self.review(path)["quotes"][0]
            self.assertNotEqual(first["quote_id"], fresh["quote_id"])
            self.assertEqual(self.action(path, "book_spot", 2, quote_id=fresh["quote_id"]).status_code, 200)
        # The desk did not receive the success response. Always inspect the saved trade first.
        with patch.object(pattaya_agents, "time", return_value=1200):
            recovered = self.client.get(path).json()
            ticket = recovered["events"][-1]["data"]
            self.assertEqual(ticket["bank_status"], "confirmed")
            self.assertTrue(ticket["bank_trade_id"].startswith("SIM-FX-"))
            self.assertEqual(self.review(path)["booked_quote"], fresh)
            retried = self.action(path, "book_spot", 2, quote_id=fresh["quote_id"]).json()
            self.assertEqual(recovered["events"], retried["events"])
            self.assertEqual(retried["paid_by_currency"], {})

    def test_both_instruments_reach_paid_only_after_the_insurer_credit(self):
        for kind, cents in (("spot", 702941), ("forward", 686782)):
            with self.subTest(kind=kind):
                path, case = self.new()
                self.assertEqual(case["example_scenario"], "pattaya_fx")
                self.assertEqual(case["payer_decision"]["amount_minor"], 23_900_000)
                self.assertEqual(len(case["sources"]), 4)
                decision = self.client.get(case["events"][-1]["source_url"])
                guarantee = PdfReader(BytesIO(decision.content)).pages[0].extract_text()
                self.assertIn("THB 239,000.00", guarantee)
                self.assertIn("30 November 2026", guarantee)
                self.assertIn("30 November 2026", case["payer_decision"]["terms"])
                self.assertIn("insurer pays the outstanding THB balance", guarantee)
                self.assertEqual(self.review(path)["next_action"], "book")
                self.assertEqual(self.action(path, "record_short_credit", 2).status_code, 409)
                self.assertEqual(self.action(path, "book_" + kind, 2, confirmed=False).status_code, 422)
                booked = self.action(path, "book_" + kind, 2)
                self.assertEqual(booked.status_code, 200, booked.text)
                self.assertEqual(booked.json()["events"][-1]["data"]["usd_minor"], cents)
                self.assertEqual(booked.json()["settlement_status"], "unpaid")
                with patch.dict(pattaya_agents.BANK_TERMS, {kind: ("35.50", "2026-11-27")}):
                    report = self.review(path)
                    self.assertEqual(report["booked_quote"]["usd_minor"], cents)
                    self.assertEqual(report["next_action"], "record_short")
                self.assertEqual(self.action(path, "record_topup", 3).status_code, 409)
                credit = self.action(path, "record_short_credit", 3)
                self.assertEqual(credit.status_code, 200, credit.text)
                self.assertEqual(credit.json()["settlement_status"], "partially_paid")
                posting = credit.json()["events"][-1]
                self.assertEqual(posting["data"]["shortfall_follow_up_owner"], posting["actor"])
                report = self.review(path)
                self.assertEqual((report["outstanding_minor"], report["shortfall_owner"], report["patient_fx_minor"]),
                                 (30_000, "insurer", 0))
                self.assertEqual(self.action(path, "record_topup", 4).status_code, 409)
                instruction = self.action(path, "record_remittance", 4, insurer_reference=" TREASURY-267 ")
                self.assertEqual(instruction.status_code, 200, instruction.text)
                self.assertEqual(instruction.json()["events"][-1]["data"]["insurer_reference"], "TREASURY-267")
                self.assertEqual(self.action(path, "record_remittance", 4, insurer_reference="TREASURY-267").json()["workflow_version"], 5)
                self.assertEqual(self.action(path, "record_remittance", 4, insurer_reference="CHANGED").status_code, 409)
                pending = self.review(path)
                self.assertEqual((pending["next_action"], pending["outstanding_minor"], pending["patient_fx_minor"]),
                                 ("confirm_topup", 30_000, 0))
                with ThreadPoolExecutor(2) as pool:
                    receipts = list(pool.map(lambda _: self.action(path, "record_topup", 5), range(2)))
                self.assertEqual([r.status_code for r in receipts], [200, 200])
                saved = self.client.get(path).json()
                self.assertEqual(saved["settlement_status"], "paid")
                self.assertEqual(saved["case_paid_by_currency"], {"THB": 23_900_000})
                self.assertEqual([e["kind"] for e in saved["events"]], ["submission", "reply", "fx_booking", "payment", "topup_remittance", "payment"])
                self.assertEqual(self.review(path)["next_action"], "complete")
                self.assertEqual(self.action(path, "record_short_credit", 3).json()["workflow_version"], 6)

    def test_worklist_and_case_share_stage_through_each_department_handoff(self):
        path, case = self.new()
        actions = [(None, "book"), ("book_forward", "record_short"), ("record_short_credit", "top_up"),
                   ("record_remittance", "confirm_topup"), ("record_topup", "complete")]
        for action, expected in actions:
            if action:
                result = self.action(path, action, case["workflow_version"])
                self.assertEqual(result.status_code, 200, result.text)
                case = result.json()
            response = self.client.post("/api/discharge/worklist/search", json={"search": case["id"]})
            self.assertEqual(response.status_code, 200, response.text)
            row = response.json()["items"][0]["pattaya_settlement"]
            desk = self.review(path)
            self.assertEqual(row["next_action"], expected)
            self.assertEqual((row["next_action"], row["outstanding_minor"]), (desk["next_action"], desk["outstanding_minor"]))

    def test_conflicting_saved_instruction_blocks_credit_and_idempotent_replay(self):
        path, case = self.new()
        self.assertEqual(self.action(path, "book_spot", 2).status_code, 200)
        self.assertEqual(self.action(path, "record_short_credit", 3).status_code, 200)
        with ThreadPoolExecutor(2) as pool:
            retries = list(pool.map(lambda _: self.action(path, "record_remittance", 4), range(2)))
        for result in retries:
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["workflow_version"], 5)
        instruction = retries[0].json()["events"][-1]
        # Exercise restored records through the same database reads as the live case and queue.
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            db.execute("UPDATE zeroupfront_demo.discharge_events SET data=%s WHERE id=%s",
                       (Jsonb({**instruction["data"], "currency": "USD", "instructed_minor": 17}), instruction["id"]))
        report = self.review(path)
        self.assertEqual((report["remittance_status"], report["next_action"]), ("conflict", "review"))
        row = self.client.post("/api/discharge/worklist/search", json={"search": case["id"]}).json()["items"][0]
        self.assertEqual(row["pattaya_settlement"]["next_action"], "review")
        self.assertEqual(self.action(path, "record_remittance", 4).status_code, 409)
        self.assertEqual(self.action(path, "record_topup", 5).status_code, 409)
        saved = self.client.get(path).json()
        self.assertEqual(saved["workflow_version"], 5)
        self.assertEqual(saved["paid_by_currency"], {"THB": pattaya_agents.SHORT_CREDIT_MINOR})
        self.assertIsNone(saved["patient_statement_facts"]["insurer_outstanding_minor"])

    def test_preview_and_archive_receiving_bank_evidence(self):
        path, _ = self.new()
        bank_path = path + "/pattaya/bank-documents/"
        def preview(kind):
            return self.client.get(bank_path + kind, params={"revision": 1})

        self.assertEqual(preview("initial_credit").status_code, 404)
        self.assertEqual(self.action(path, "book_spot", 2).status_code, 200)
        instruction = preview("instruction")
        self.assertEqual(instruction.status_code, 200)
        self.assertIn("Beneficiary credit unconfirmed", PdfReader(BytesIO(instruction.content)).pages[0].extract_text())
        self.assertEqual(self.action(path, "record_short_credit", 3, bank_document="instruction").status_code, 422)
        self.assertEqual(self.action(path, "record_short_credit", 3, bank_document=None).status_code, 422)
        self.assertEqual(self.client.get(path).json()["paid_by_currency"], {})
        for action, kind, version, gross, fee, net in (
            ("record_short_credit", "initial_credit", 3, 23_900_000, 30_000, 23_870_000),
            ("record_topup", "topup_credit", 5, 30_000, 0, 30_000),
        ):
            if action == "record_topup":
                self.assertEqual(preview(kind).status_code, 404)
                original = preview("topup_instruction")
                self.assertEqual(original.status_code, 200)
                self.assertEqual(self.action(path, "record_remittance", 4, bank_document="topup_credit").status_code, 422)
                instruction = self.action(path, "record_remittance", 4).json()["events"][-1]
                self.assertTrue(instruction["data"]["bank_reference"])
                self.assertEqual(self.client.get(instruction["source_url"]).content, original.content)
            shown = preview(kind)
            self.assertEqual(shown.status_code, 200, shown.text[:120])
            result = self.action(path, action, version)
            self.assertEqual(result.status_code, 200, result.text)
            event = result.json()["events"][-1]
            receipt = event["data"]
            self.assertEqual((receipt["gross_minor"], receipt["fee_minor"], receipt["amount_minor"]), (gross, fee, net))
            self.assertNotEqual(receipt["bank_reference"], receipt["reference"])
            self.assertEqual(receipt["beneficiary"], "Pattaya Practice Hospital")
            original = self.client.get(event["source_url"])
            self.assertEqual(original.content, shown.content)
            source = PdfReader(BytesIO(original.content)).pages[0].extract_text()
            for value in (receipt["bank_reference"], receipt["value_date"], receipt["beneficiary"], "Posted to beneficiary account"):
                self.assertIn(value, source)
            self.assertEqual(preview(kind).status_code, 404)
        self.assertEqual(self.action(path, "record_topup", 4, bank_document="instruction").status_code, 422)

    def test_bank_message_must_match_the_claim_and_confirm_net_thb_credit(self):
        path, case = self.new()
        self.assertEqual(self.action(path, "book_forward", 2).status_code, 200)
        message = pattaya_case.bank_message(case["id"], "initial_credit")
        for change in ({"beneficiary": "Different Practice Hospital"}, {"case_id": "D-OTHER"},
                       {"currency": "USD"}, {"encounter": "DEMO-OTHER"}, {"bank_reference": ""},
                       {"net_minor": 23_869_999}, {"kind": "instruction", "net_minor": None}):
            with self.subTest(change=change), patch("app.pattaya_case.bank_message", return_value=replace(message, **change)):
                self.assertEqual(self.action(path, "record_short_credit", 3).status_code, 422)
        self.assertEqual(self.client.get(path).json()["paid_by_currency"], {})
        with patch("app.pattaya_case.bank_message", return_value=replace(message, fee_minor=None)):
            result = self.action(path, "record_short_credit", 3)
        self.assertEqual(result.status_code, 200)
        receipt = result.json()["events"][-1]
        self.assertIsNone(receipt["data"]["fee_minor"])
        self.assertIn("unverified", receipt["data"]["notes"])
        self.assertIn("Unspecified", PdfReader(BytesIO(self.client.get(receipt["source_url"]).content)).pages[0].extract_text())
        self.assertEqual(self.review(path)["shortfall_owner"], "insurer")

    def test_seed_write_failure_rolls_back_entire_example(self):
        def total():
            return self.client.get("/api/discharge/worklist").json()["total"]

        before = total()
        with patch("app.pattaya_case.final_decision", side_effect=ValueError("fixture issue")):
            with self.assertRaisesRegex(ValueError, "fixture issue"):
                self.client.post("/api/discharge/examples/pattaya_fx")
        self.assertEqual(total(), before)

    def test_mutations_are_scoped_to_the_fixture_revision_and_local_mode(self):
        path, _ = self.new()
        with ThreadPoolExecutor(2) as pool:
            attempts = list(pool.map(lambda k: self.action(path, "book_" + k, 2), ("spot", "forward")))
        self.assertEqual(sorted(r.status_code for r in attempts), [200, 409])
        self.assertEqual(self.action(path, "record_short_credit", 2).status_code, 409)
        self.assertEqual(self.action(path, "record_short_credit", 3, revision=2).status_code, 412)
        bill = self.client.get(path + "/revisions/1/sources/bill").content
        correction = self.client.post(path + "/documents", headers={"If-Match": '"1"'}, data={"confirmed": "true"},
                                      files={"bill": ("different-bill.pdf", bill, "application/pdf")})
        self.assertEqual(correction.status_code, 409, correction.text)
        self.assertEqual(self.client.get(path).json()["revision"], 1)
        self.assertEqual(self.review(path)["next_action"], "record_short")

        self.assertEqual(self.client.post(path + "/workflow", headers={"If-Match": '"1"'}, data={
            "action": "payment", "workflow_version": 3, "actor": "Practice reviewer", "amount": "239000",
            "currency": "THB", "reference": "manual", "notes": "Bypass the bank rehearsal",
        }).status_code, 409)
        other, _ = self.new("aligned")
        self.assertEqual(self.client.get(other + "/pattaya?revision=1").status_code, 404)
        self.assertEqual(self.client.get(other + "/pattaya/bank-documents/initial_credit?revision=1").status_code, 404)
        self.assertEqual(self.action(other, "book_spot", 0).status_code, 404)
        headers = {"If-Match": '"1"'}
        self.assertEqual(self.client.post(path + "/pattaya/agent-review", headers=headers,
                                          json={"confirmed": False}).status_code, 422)
        self.assertEqual(self.client.post(other + "/pattaya/agent-review", headers=headers,
                                          json={"confirmed": True}).status_code, 404)
        with patch.dict(os.environ, WORKSPACE_AUTH_MODE="staff"):
            self.assertEqual(self.client.get(path + "/pattaya?revision=1").status_code, 401)
            with patch("app.staff_access._staff", return_value=("desk", "Hospital coordinator", "coordinator", None)):
                self.assertEqual(self.action(path, "record_short_credit", 3).status_code, 404)
                self.assertEqual(self.client.get(path + "/pattaya?revision=1").status_code, 404)
                self.assertEqual(self.client.get(path + "/pattaya/bank-documents/initial_credit?revision=1").status_code, 404)
                self.assertEqual(self.client.post(path + "/pattaya/agent-review", headers=headers,
                                                  json={"confirmed": True}).status_code, 404)
