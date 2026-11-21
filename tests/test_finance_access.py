"""Restricted finance accounts can read only assigned, revision-specific balances."""
from contextlib import ExitStack
import os
import secrets
import shutil
import unittest
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app import pattaya_agents
from app.finance_access import assign_case
from app.staff_access import provision
from app.workspace_api import create_workspace
from bench.case_revision import temporary_database


@unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires disposable PostgreSQL")
class FinanceAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scope = ExitStack()
        cls.addClassCleanup(scope.close)
        cls.dsn = scope.enter_context(temporary_database())
        scope.enter_context(patch.dict(os.environ, DATABASE_URL=cls.dsn, WORKSPACE_AUTH_MODE="staff",
                                       WORKSPACE_SEED_DEMO="0"))
        cls.client = scope.enter_context(TestClient(create_workspace()))
        with patch.dict(os.environ, WORKSPACE_AUTH_MODE="local"):
            response = cls.client.post("/api/discharge/examples/pattaya_fx")
            assert response.status_code == 201, response.text
            cls.case = response.json()["id"]
            ledger = "/api/discharge/" + cls.case + "/pattaya/actions"
            quote = pattaya_agents.quotes()["forward"]
            for fields in ({"action": "book_forward", "quote_id": quote["quote_id"], "workflow_version": 2},
                           {"action": "record_short_credit", "bank_document": "initial_credit", "workflow_version": 3}):
                reply = cls.client.post(ledger, headers={"If-Match": '"1"'}, json={**fields, "confirmed": True})
                assert reply.status_code == 200, reply.text
            other = cls.client.post("/api/discharge/examples/aligned")
            assert other.status_code == 201, other.text
            cls.other = other.json()["id"]
        cls.password = secrets.token_urlsafe(32)

    def setUp(self):
        self.client.cookies.clear()

    def login(self, username):
        response = self.client.post("/api/access/login", json={"username": username, "password": self.password})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_assignment_returned_fields_denials_audit_and_revocation(self):
        user = "finance-recon"
        provision(self.dsn, user, "Finance", self.password, role="finance")
        self.assertEqual(self.login(user)["role"], "finance")
        endpoint = "/api/finance/reconciliation"
        self.assertEqual(self.client.get(endpoint).json()["items"], [])
        assign_case(self.dsn, user, self.case)
        result = self.client.get(endpoint)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("no-store", result.headers["cache-control"])
        expected = {"case_id": self.case, "revision": 1, "current": True, "currency": "THB",
                    "approved_minor": 23900000, "credited_minor": 23870000, "outstanding_minor": 30000,
                    "receipt_count": 1, "status": "outstanding", "payer_outcome": "confirmed"}
        (row,) = result.json()["items"]
        self.assertIsInstance(row.pop("last_receipt_id"), int)
        self.assertEqual(row, expected)
        self.assertNotIn(self.other, result.text)
        claim = "/api/discharge/" + self.case
        for method, url in (("GET", "/api/discharge"), ("GET", claim), ("GET", "/api/cases"),
                            ("GET", claim + "/revisions/1/sources/summary"), ("GET", claim + "/export?revision=1"),
                            ("POST", claim + "/second-read"), ("POST", claim + "/guarantee-fees"),
                            ("POST", claim + "/workflow"), ("POST", claim + "/pattaya/actions")):
            with self.subTest(path=url):
                self.assertEqual(self.client.request(method, url).status_code, 403)
        with psycopg.connect(self.dsn) as db:
            logs = db.execute("""SELECT capability,outcome,case_id,revision FROM zeroupfront_demo.access_audit
                                  WHERE username=%s""", (user,)).fetchall()
        self.assertIn(("finance_reconciliation", "allowed", self.case, 1), logs)
        self.assertIn(("original", "denied", None, None), logs)
        self.assertIn(("ai_review", "denied", None, None), logs)
        self.assertIn(("export", "denied", None, None), logs)
        assign_case(self.dsn, user, self.case, remove=True)
        self.assertEqual(self.client.get(endpoint).json()["items"], [])
        provision(self.dsn, user, "Finance", self.password, reset=True)
        self.assertEqual(self.client.get(endpoint).status_code, 401)
        self.assertEqual(self.login(user)["role"], "finance")
        self.assertEqual(self.client.post("/api/access/logout").status_code, 200)

    def test_latest_written_nonmonetary_outcomes_remain_visible(self):
        user = "finance-nonmonetary"
        with patch.dict(os.environ, WORKSPACE_AUTH_MODE="local"):
            claim = self.client.post("/api/discharge/examples/aligned").json()["id"]
        provision(self.dsn, user, "Finance", self.password, role="finance")
        assign_case(self.dsn, user, claim)
        self.login(user)
        for version, outcome in enumerate(("query", "declined"), start=1):
            with psycopg.connect(self.dsn) as db:
                db.execute("""INSERT INTO zeroupfront_demo.discharge_events
                    (case_id,revision,version,kind,actor,data) VALUES (%s,1,%s,'reply','Staff',%s)""",
                    (claim, version, Jsonb({"outcome": outcome, "terms": "restricted letter text"})))
            response = self.client.get("/api/finance/reconciliation")
            (entry,) = response.json()["items"]
            self.assertEqual((entry["payer_outcome"], entry["status"]), (outcome, outcome))
            self.assertIsNone(entry["approved_minor"])
            self.assertIsNone(entry["outstanding_minor"])
            self.assertNotIn("restricted letter text", response.text)

    def test_unknown_decisions_and_historical_receipts_remain_separate(self):
        user = "finance-history"
        provision(self.dsn, user, "Finance", self.password, role="finance")
        assign_case(self.dsn, user, self.other)
        self.login(user)
        endpoint = "/api/finance/reconciliation"
        (entry,) = self.client.get(endpoint).json()["items"]
        self.assertEqual((entry["status"], entry["approved_minor"], entry["outstanding_minor"]),
                         ("awaiting_decision", None, None))
        with psycopg.connect(self.dsn) as db:
            db.execute("""INSERT INTO zeroupfront_demo.discharge_events
                (case_id,revision,version,kind,actor,data) VALUES (%s,1,1,'reply','Reviewer',%s),
                (%s,1,2,'payment','Reviewer',%s)""", (self.other, Jsonb({"outcome": "partial", "currency": "EUR", "amount_minor": 200}),
                self.other, Jsonb({"currency": "USD", "amount_minor": 100, "reference": "sensitive free text"})))
            db.execute("""INSERT INTO zeroupfront_demo.discharge_revisions
                          SELECT case_id,2,evidence FROM zeroupfront_demo.discharge_revisions WHERE case_id=%s AND revision=1""", (self.other,))
            db.execute("UPDATE zeroupfront_demo.discharge_cases SET head=2 WHERE id=%s", (self.other,))
        current, previous = self.client.get(endpoint).json()["items"]
        self.assertEqual((current["revision"], current["receipt_count"]), (2, 0))
        self.assertEqual((previous["status"], previous["current"], previous["credited_minor"], previous["outstanding_minor"]),
                         ("reconciliation_required", False, None, None))
        self.assertNotIn("sensitive", str(previous))

    def test_existing_coordinator_access_and_original_audit(self):
        user = "finance-test-coordinator"
        provision(self.dsn, user, "Coordinator", self.password)
        self.assertEqual(self.login(user)["role"], "coordinator")
        granted = self.client.get(f"/api/discharge/{self.case}/revisions/1/sources/summary")
        self.assertEqual(granted.status_code, 200, granted.text[:120])
        self.assertEqual(self.client.get("/api/finance/reconciliation").status_code, 403)
        with psycopg.connect(self.dsn) as db:
            self.assertEqual(db.execute("""SELECT capability,case_id,revision FROM zeroupfront_demo.access_audit
                                           WHERE username=%s AND outcome='allowed'""", (user,)).fetchall(), [("original", self.case, 1)])
