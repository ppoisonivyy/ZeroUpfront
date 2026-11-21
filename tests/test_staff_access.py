from contextlib import ExitStack
import os
import secrets
import shutil
import unittest
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient

from app import workspace_api
from app.staff_access import disable, provision
from bench.case_revision import temporary_database


@unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires PostgreSQL binaries")
class StaffAccessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = ExitStack()
        cls.addClassCleanup(cls.scope.close)
        cls.dsn = cls.scope.enter_context(temporary_database())
        cls.scope.enter_context(patch.dict(os.environ, WORKSPACE_AUTH_MODE="staff", DATABASE_URL=cls.dsn,
                                           WORKSPACE_SEED_DEMO="1"))
        cls.browser = cls.scope.enter_context(TestClient(workspace_api.app))
        cls.credential = secrets.token_urlsafe(32)

    def setUp(self):
        self.browser.cookies.clear()

    def test_source_privacy_identity_and_session_lifecycle(self):
        url = "/api/cases/Z001/revisions/1/sources/policy"
        self.assertEqual(self.browser.get(url).status_code, 401)
        self.assertIsNone(self.browser.get("/api/access/session").json()["actor"])
        provision(self.dsn, "coordinator", "Hospital coordinator", self.credential)
        credentials = {"username": "coordinator", "password": self.credential}
        self.assertEqual(self.browser.post("/api/access/login", json=credentials,
                                           headers={"Origin": "https://other.example"}).status_code, 403)
        login = self.browser.post("/api/access/login", json=credentials)
        self.assertEqual(login.status_code, 200, login.text)
        self.assertIn("HttpOnly", login.headers["set-cookie"])
        self.assertEqual(self.browser.get(url).status_code, 200)
        record = self.browser.post("/api/cases/Z001/approve", json={"reviewer": "Different name"},
                                   headers={"If-Match": '"1"'})
        self.assertEqual(record.status_code, 200, record.text)
        self.assertEqual(record.json()["reviewer"], "Hospital coordinator")
        token = self.browser.cookies.get("zu_staff_session")
        self.assertEqual(self.browser.post("/api/access/logout").status_code, 200)
        self.browser.cookies.set("zu_staff_session", token)
        self.assertEqual(self.browser.get(url).status_code, 401)
        self.browser.cookies.clear()
        self.assertEqual(self.browser.post("/api/access/login", json=credentials).status_code, 200)
        provision(self.dsn, "coordinator", "Hospital coordinator", secrets.token_urlsafe(32), reset=True)
        self.assertEqual(self.browser.get(url).status_code, 401)
        self.assertEqual(self.browser.post("/api/access/login", json=credentials).status_code, 401)

    def test_account_lockout_and_disable(self):
        provision(self.dsn, "shift", "Night shift", self.credential)
        credentials = {"username": "shift", "password": self.credential}
        self.assertEqual(self.browser.post("/api/access/login", json=credentials).status_code, 200)
        disable(self.dsn, "shift")
        self.assertEqual(self.browser.get("/api/cases").status_code, 401)
        for _ in range(12):
            status = self.browser.post("/api/access/login", json=credentials).status_code
            self.assertEqual(status, 401)
        self.assertEqual(self.browser.post("/api/access/login", json=credentials).status_code, 429)
        with psycopg.connect(self.dsn) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM zeroupfront_demo.staff_sessions WHERE username='shift'").fetchone()[0], 0)
