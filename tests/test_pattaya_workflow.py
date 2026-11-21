"""Exercise both funding routes and the synthetic THB settlement boundary through HTTP."""
import os
import shutil
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from io import BytesIO
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import pattaya_case
from app.pattaya_agents import BANK_TERMS
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
        return self.client.post(path + "/pattaya/actions", headers={"If-Match": f'"{revision}"'},
                                json={"action": action, "confirmed": True, "workflow_version": version, **overrides})

    def review(self, path):
        result = self.client.get(path + "/pattaya", params={"revision": 1})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

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
                with patch.dict(BANK_TERMS, {kind: ("35.50", "2026-11-27")}):
                    report = self.review(path)
                    self.assertEqual(report["quotes"][0]["usd_minor"], cents)
                    self.assertEqual(report["next_action"], "record_short")
                self.assertEqual(self.action(path, "record_topup", 3).status_code, 409)
                credit = self.action(path, "record_short_credit", 3)
                self.assertEqual(credit.status_code, 200, credit.text)
                self.assertEqual(credit.json()["settlement_status"], "partially_paid")
                report = self.review(path)
                self.assertEqual((report["outstanding_minor"], report["shortfall_owner"], report["patient_fx_minor"]),
                                 (30_000, "insurer", 0))
                with ThreadPoolExecutor(2) as pool:
                    receipts = list(pool.map(lambda _: self.action(path, "record_topup", 4), range(2)))
                self.assertEqual([r.status_code for r in receipts], [200, 200])
                saved = self.client.get(path).json()
                self.assertEqual(saved["settlement_status"], "paid")
                self.assertEqual(saved["case_paid_by_currency"], {"THB": 23_900_000})
                self.assertEqual([e["kind"] for e in saved["events"]], ["submission", "reply", "fx_booking", "payment", "payment"])
                self.assertEqual(self.review(path)["next_action"], "complete")
                self.assertEqual(self.action(path, "record_short_credit", 3).json()["workflow_version"], 5)

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
        self.assertEqual(self.action(other, "book_spot", 0).status_code, 404)
        headers = {"If-Match": '"1"'}
        self.assertEqual(self.client.post(path + "/pattaya/agent-review", headers=headers,
                                          json={"confirmed": False}).status_code, 422)
        self.assertEqual(self.client.post(other + "/pattaya/agent-review", headers=headers,
                                          json={"confirmed": True}).status_code, 404)
        with patch.dict(os.environ, WORKSPACE_AUTH_MODE="staff"):
            self.assertEqual(self.client.get(path + "/pattaya?revision=1").status_code, 401)
            with patch("app.staff_access._staff", return_value=("finance", "Hospital finance")):
                self.assertEqual(self.action(path, "record_short_credit", 3).status_code, 404)
                self.assertEqual(self.client.get(path + "/pattaya?revision=1").status_code, 404)
                self.assertEqual(self.client.post(path + "/pattaya/agent-review", headers=headers,
                                                  json={"confirmed": True}).status_code, 404)
