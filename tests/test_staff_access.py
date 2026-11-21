from contextlib import ExitStack
import os
import secrets
import shutil
import unittest
from unittest.mock import patch

from argon2 import extract_parameters, Type
import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import workspace_api
from app.staff_access import COOKIE, disable, install_access, provision
from bench.case_revision import temporary_database


@unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires PostgreSQL binaries")
class StaffAccessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = ExitStack()
        cls.addClassCleanup(cls.scope.close)
        cls.dsn = cls.scope.enter_context(temporary_database())
        cls.scope.enter_context(patch.dict(os.environ, WORKSPACE_AUTH_MODE="staff", DATABASE_URL=cls.dsn,
                                           WORKSPACE_SEED_DEMO="1", WORKSPACE_HOSPITAL_NAME=" "))
        cls.browser = cls.scope.enter_context(TestClient(workspace_api.app))
        cls.credential = secrets.token_urlsafe(32)

    def setUp(self):
        self.browser.cookies.clear()

    def test_login_validation_returns_only_generic_feedback(self):
        password = secrets.token_urlsafe(32)
        for fields in ({"password": password}, {"username": "desk", "password": [password]}):
            reply = self.browser.post("/api/access/login", json=fields)
            self.assertEqual(reply.status_code, 422)
            self.assertEqual(reply.json(), {"detail": "Enter a valid username and password."})
            self.assertNotIn(password, reply.text)

    def test_openapi_schema_is_available_without_external_documentation_scripts(self):
        schema = self.browser.get("/openapi.json")
        self.assertEqual(schema.status_code, 200)
        self.assertIn("/api/access/login", schema.json()["paths"])
        for route in ("/docs", "/docs/oauth2-redirect", "/redoc"):
            self.assertEqual(self.browser.get(route).status_code, 404)

    def test_identical_passwords_have_independent_argon2id_salts_and_verifiers(self):
        password = secrets.token_urlsafe(32)
        names = ["salt-staff-a", "salt-staff-b"]
        for username in names:
            provision(self.dsn, username, "Demo staff", password)
        with psycopg.connect(self.dsn) as db:
            hashes = [row[0] for row in db.execute(
                "SELECT password_hash FROM zeroupfront_demo.staff_accounts WHERE username = ANY(%s) ORDER BY username",
                (names,))]
        self.assertEqual(len(hashes), 2)
        for encoded in hashes:
            params = extract_parameters(encoded)
            self.assertEqual((params.type, params.salt_len, params.hash_len), (Type.ID, 16, 32))
            self.assertEqual((params.memory_cost, params.time_cost, params.parallelism), (65536, 3, 4))
            self.assertNotIn(password, encoded)
        self.assertNotEqual(hashes[0].split("$")[4], hashes[1].split("$")[4])
        self.assertNotEqual(hashes[0].split("$")[5], hashes[1].split("$")[5])
        login = self.browser.post("/api/access/login", json={"username": names[0], "password": password})
        self.assertEqual(login.status_code, 200)
        for term in ["O'Neil", "%", "_"]:
            result = self.browser.post("/api/discharge/worklist/search", json={"search": term})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["total"], 0)

    def test_source_privacy_identity_and_session_lifecycle(self):
        url = "/api/cases/Z001/revisions/1/sources/policy"
        self.assertEqual(self.browser.get(url).status_code, 401)
        self.assertEqual(self.browser.get("/api/access/session").json(),
                         {"mode": "staff", "actor": None, "username": None})
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

    def test_hospital_display_name_follows_the_deployment_through_sign_in_and_out(self):
        with ExitStack() as deployments:
            second_dsn = deployments.enter_context(temporary_database())

            def start(name, dsn):
                app = FastAPI(lifespan=workspace_api.lifespan)
                install_access(app)
                app.include_router(workspace_api.discharge_router)
                with patch.dict(os.environ, WORKSPACE_HOSPITAL_NAME=name, DATABASE_URL=dsn, WORKSPACE_SEED_DEMO="0"):
                    return deployments.enter_context(TestClient(app))

            first_name, second_name = "คลอง Hospital", "Bay Hospital"
            first = start(f" {first_name} ", self.dsn)
            second = start(second_name, second_dsn)
            public = {"mode": "staff", "actor": None, "username": None}
            self.assertEqual(first.get("/api/access/session").json(), {**public, "hospital_name": first_name})
            self.assertEqual(second.get("/api/access/session").json(), {**public, "hospital_name": second_name})

            provision(self.dsn, "intake", "Intake coordinator", self.credential)
            login = first.post("/api/access/login", json={"username": "intake", "password": self.credential})
            self.assertEqual(login.status_code, 200, login.text)
            self.assertEqual(login.json()["hospital_name"], first_name)
            self.assertEqual(first.get("/api/access/session").json()["actor"], "Intake coordinator")
            second.cookies.set(COOKIE, first.cookies.get(COOKIE))
            self.assertEqual(second.get("/api/access/session").json(), {**public, "hospital_name": second_name})
            self.assertEqual(second.get("/api/discharge").status_code, 401)
            self.assertEqual(first.post("/api/access/logout").json(), {**public, "hospital_name": first_name})

    def test_reviewer_scope_is_server_bound_and_survives_password_rotation(self):
        username, payer = "meridian-reader", "Meridian Assist"
        reviewer = {"username": username, "password": self.credential}
        url = "/api/insurer/preclaims"
        self.assertEqual(self.browser.get(url).status_code, 401)
        provision(self.dsn, username, "Reviewer", self.credential, insurer=payer)
        login = self.browser.post("/api/access/login", json={**reviewer, "insurer": "Other payer"})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["insurer"], payer)
        self.assertEqual(login.json()["role"], "insurer")
        state = self.browser.get("/api/access/session", headers={"X-Insurer": "Other payer"}).json()
        self.assertEqual(state, login.json())
        self.assertEqual(self.browser.get(url).status_code, 200)
        self.assertEqual(self.browser.post(url, json={}).status_code, 403)
        for path in ("/api/discharge", "/api/cases", "/api/cases/Z001/revisions/1/sources/policy"):
            self.assertEqual(self.browser.get(path).status_code, 403, path)
        self.assertEqual(self.browser.post("/api/cases/Z001/approve", json={}).status_code, 403)
        rotated = secrets.token_urlsafe(32)
        with self.assertRaises(ValueError):
            provision(self.dsn, username, "Reviewer", rotated, reset=True, insurer="Other payer")
        provision(self.dsn, username, "Reviewer", rotated, reset=True)
        self.assertEqual(self.browser.get(url).status_code, 401)
        login = self.browser.post("/api/access/login", json={**reviewer, "password": rotated})
        self.assertEqual(login.json()["insurer"], payer)
        self.assertIsNone(self.browser.post("/api/access/logout").json()["actor"])
        provision(self.dsn, "hospital-review", "Hospital staff", self.credential)
        self.browser.post("/api/access/login", json={**reviewer, "username": "hospital-review"})
        self.assertEqual(self.browser.get(url, headers={"X-Insurer": payer}).status_code, 403)
        self.assertEqual(self.browser.get("/api/cases").status_code, 200)

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
