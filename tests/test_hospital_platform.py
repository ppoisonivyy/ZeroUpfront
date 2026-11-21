"""Hospital selection, sessions and original exhibits across dedicated PostgreSQL databases."""
from contextlib import ExitStack
import json
import os
import shutil
import unittest
from unittest.mock import patch

import psycopg
from psycopg.conninfo import make_conninfo
from fastapi.testclient import TestClient

from app import discharge_store
from app.discharge_claim import evaluate_discharge, load_discharge_fixture
from app.hospital_platform import build_platform, configured_hospitals
from app.staff_access import provision
from app.finance_access import assign_case
from app.workspace_api import create_workspace
from bench.case_revision import temporary_database


REGISTRY = {
    "north": {"hospital_name": "North Hospital", "database_url_env": "NORTH_DATABASE_URL"},
    "south": {"hospital_name": "โรงพยาบาลใต้", "database_url_env": "SOUTH_DATABASE_URL"},
}


class HospitalDirectoryTests(unittest.TestCase):
    def test_config_is_explicit_and_secrets_are_never_echoed(self):
        with patch.dict(os.environ, NORTH_DATABASE_URL="postgresql://user:secret@db/north",
                        SOUTH_DATABASE_URL="dbname=north host=db user=other"):
            invalid = ["", "[]", "{}", '{"north":{},"north":{}}', json.dumps({"../bad": REGISTRY["north"]}),
                       json.dumps({"north": dict(REGISTRY["north"], database_url_env="not-set")}),
                       json.dumps({"north": dict(REGISTRY["north"], database_url_env="MISSING_HOSPITAL_DATABASE")}),
                       json.dumps({"north": dict(REGISTRY["north"], hospital_name="\n")}), json.dumps(REGISTRY)]
            for config in invalid:
                with self.subTest(config=config), patch.dict(os.environ, WORKSPACE_HOSPITALS=config):
                    with self.assertRaises(ValueError) as error:
                        configured_hospitals()
                    self.assertNotIn("secret", str(error.exception))
            with patch.dict(os.environ, WORKSPACE_HOSPITALS=json.dumps({"north": REGISTRY["north"]})):
                self.assertNotIn("secret", repr(configured_hospitals()))


@unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires disposable PostgreSQL")
class HospitalPlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cleanup = ExitStack()
        cls.addClassCleanup(cleanup.close)
        base = cleanup.enter_context(temporary_database())
        with psycopg.connect(base, autocommit=True) as db:
            db.execute("CREATE DATABASE north")
            db.execute("CREATE DATABASE south")
        cls.databases = {slug: make_conninfo(base, dbname=slug) for slug in REGISTRY}
        cleanup.enter_context(patch.dict(os.environ, WORKSPACE_HOSPITALS=json.dumps(REGISTRY),
            WORKSPACE_AUTH_MODE="local", WORKSPACE_SEED_DEMO="1", NORTH_DATABASE_URL=cls.databases["north"],
            SOUTH_DATABASE_URL=cls.databases["south"]))
        cls.platform = build_platform(create_workspace)
        # Static client assets are optional for the API-only module.
        cls.client = cleanup.enter_context(TestClient(cls.platform))
        cls.bills = {}
        for slug, scenario in (("north", "duplicate_line"), ("south", "aligned")):
            dsn = cls.databases[slug]
            provision(dsn, "desk", slug.title() + " desk", "Sample passphrase for " + slug)
            meta, raw, names = load_discharge_fixture(scenario)
            meta["id"] = "shared-case-id"
            evidence = meta | evaluate_discharge(meta, raw, names)
            discharge_store.create(dsn, meta["id"], evidence, raw, names)
            cls.bills[slug] = raw["bill"]

    def setUp(self):
        self.client.cookies.clear()

    def login(self, slug):
        return self.client.post(f"/h/{slug}/api/access/login", headers={"Origin": "http://testserver"},
                                json={"username": "desk", "password": "Sample passphrase for " + slug})

    def test_directory_is_public_and_root_clinical_routes_have_no_default(self):
        self.assertEqual(self.client.get("/api/hospitals").json(),
                         {"mode": "multi", "hospitals": [{"slug": s, "name": p["hospital_name"]} for s,p in REGISTRY.items()]})
        for path in ("/api/access/session", "/api/cases", "/api/discharge", "/h/missing/api/cases"):
            self.assertEqual(self.client.get(path).status_code, 404)
        for slug in REGISTRY:
            session = self.client.get(f"/h/{slug}/api/access/session").json()
            self.assertEqual((session["mode"], session["actor"], session["hospital_name"]),
                             ("staff", None, REGISTRY[slug]["hospital_name"]))
            self.assertEqual(self.client.get(f"/h/{slug}/api/discharge").status_code, 401)
            invalid = self.client.post(f"/h/{slug}/api/access/login", json={"password": ["test only"]})
            self.assertEqual(invalid.json(), {"detail": "Enter a valid username and password."})
            self.assertEqual(invalid.status_code, 422)
            for route in ("/docs", "/redoc"):
                self.assertEqual(self.client.get(f"/h/{slug}" + route).status_code, 404)

    def test_two_sessions_cannot_swap_originals_or_sign_out_the_other_hospital(self):
        self.assertNotEqual(self.bills["north"], self.bills["south"])
        north = self.login("north")
        self.assertEqual(north.status_code, 200, north.text)
        self.assertIn("Path=/h/north/api", north.headers["set-cookie"])
        case_path = "/api/discharge/shared-case-id"
        self.assertEqual(self.client.get("/h/south" + case_path).status_code, 401)
        south = self.login("south")
        self.assertEqual(south.status_code, 200, south.text)
        for slug in REGISTRY:
            base = f"/h/{slug}"
            self.assertEqual(self.client.get(base + "/api/cases").json(), [])
            self.assertEqual(self.client.get(base + "/api/access/session").json()["actor"], slug.title() + " desk")
            case = self.client.get(base + case_path).json()
            bill = next(s for s in case["sources"] if s["role"] == "bill")
            self.assertTrue(bill["url"].startswith(base + case_path + "/"))
            self.assertEqual(self.client.get(bill["url"]).content, self.bills[slug])
            self.assertEqual(self.client.post(base + "/api/discharge/examples/aligned").status_code, 404)
            self.assertEqual(self.client.post(base + "/api/examples/missing-estimate").status_code, 404)
        self.assertEqual(self.client.post("/h/north/api/access/logout").status_code, 200)
        self.assertEqual(self.client.get("/h/north" + case_path).status_code, 401)
        self.assertEqual(self.client.get("/h/south" + case_path).status_code, 200)

    def test_finance_assignments_and_sessions_are_local_to_each_hospital(self):
        username = "payment-review"
        for slug, dsn in self.databases.items():
            provision(dsn, username, "Finance staff", "Temporary finance passphrase " + slug, role="finance")
        assign_case(self.databases["north"], username, "shared-case-id")
        path = "/api/finance/reconciliation"
        north = self.client.post("/h/north/api/access/login", json={
            "username": username, "password": "Temporary finance passphrase north"})
        self.assertEqual(north.status_code, 200, north.text)
        self.assertEqual(self.client.get("/h/south" + path).status_code, 401)
        south = self.client.post("/h/south/api/access/login", json={
            "username": username, "password": "Temporary finance passphrase south"})
        self.assertEqual(south.status_code, 200, south.text)
        self.assertEqual(self.client.get("/h/south" + path).json()["items"], [])
        self.assertEqual([row["case_id"] for row in self.client.get("/h/north" + path).json()["items"]],
                         ["shared-case-id"])
        for slug in self.databases:
            denied = self.client.get(f"/h/{slug}/api/discharge/shared-case-id/revisions/1/sources/bill")
            self.assertEqual(denied.status_code, 403)

    def test_reassigned_database_secret_fails_on_startup(self):
        with patch.dict(os.environ, NORTH_DATABASE_URL=self.databases["south"],
                        SOUTH_DATABASE_URL=self.databases["north"]):
            with self.assertRaisesRegex(ValueError, "bound to a different hospital"):
                with TestClient(build_platform(create_workspace)):
                    pass

    def test_mounted_upload_requires_staff_and_stays_in_the_selected_database(self):
        meta, raw, names = load_discharge_fixture("aligned")
        fields = {k: v for k, v in meta.items() if k not in {"id", "as_of"}} | {"confirmed": "true"}
        uploads = {role: (names[role], source, "application/pdf") for role, source in raw.items()}
        path = "/h/north/api/discharge"
        self.assertEqual(self.client.post(path, data=fields, files=uploads).status_code, 401)
        self.assertEqual(self.login("north").status_code, 200)
        self.assertEqual(self.client.post("/h/north/api/access/login", files=uploads).status_code, 415)
        created = self.client.post(path, data=fields, files=uploads)
        self.assertEqual(created.status_code, 201, created.text)
        case = created.json()
        for source in case["sources"]:
            self.assertEqual(self.client.get(source["url"]).content, raw[source["role"]])
        self.assertEqual(self.login("south").status_code, 200)
        self.assertEqual(self.client.get("/h/south/api/discharge/" + case["id"]).status_code, 404)
