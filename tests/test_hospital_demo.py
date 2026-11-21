"""Exercise the seeded correction and a second seeding pass through a staffed workspace."""
from contextlib import ExitStack
from io import BytesIO
import json
import os
import secrets
import shutil
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import hospital_demo
from app.hospital_platform import Hospital, build_platform
from app.staff_access import provision
from app.workspace_api import create_workspace
from bench.case_revision import temporary_database


@unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires PostgreSQL")
class HospitalDemoTests(unittest.TestCase):
    def test_corrected_bill_and_history_survive_reseeding(self):
        with ExitStack() as stack:
            dsn = stack.enter_context(temporary_database())
            slug, (name, code) = next(iter(hospital_demo.HOSPITALS.items()))
            hospital = Hospital(slug, name, dsn)
            directory = {slug: {"hospital_name": name, "database_url_env": "TEST_HOSPITAL_DSN"}}
            stack.enter_context(patch.dict(os.environ, WORKSPACE_HOSPITALS=json.dumps(directory), TEST_HOSPITAL_DSN=dsn))
            hospital_demo.seed(hospital)
            password = secrets.token_urlsafe(32)
            provision(dsn, "judge", "Demo coordinator", password)
            client = stack.enter_context(TestClient(build_platform(create_workspace)))
            base = f"/h/{slug}/api"
            self.assertEqual(client.post(base + "/access/login", json={"username":"judge","password":password}).status_code, 200)
            self.assertEqual(len(client.get(base + "/cases").json()), 1)
            self.assertEqual(len(client.get(base + "/discharge").json()), 3)
            claim = base + "/discharge/D-" + code + "-001"
            original = client.get(claim).json()
            self.assertEqual((original["status"], original["revision"]), ("needs_review", 1))
            corrected = client.get(claim + "/sample-bill")
            self.assertEqual(corrected.status_code, 200)
            text = "".join(page.extract_text() for page in PdfReader(BytesIO(corrected.content)).pages)
            self.assertIn(original["encounter"], text)
            self.assertIn(name, text)
            saved = client.post(claim + "/documents", data={"sample_bill": "true", "confirmed": "true"},
                                headers={"If-Match": '"1"'})
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual((saved.json()["revision"], saved.json()["status"]), (2, "ready_for_review"))
            hospital_demo.seed(hospital)
            self.assertEqual(client.get(claim).json()["revision"], 2)
            self.assertEqual(client.get(claim, params={"revision":1}).json()["status"], "needs_review")
            self.assertEqual(len(client.get(base + "/discharge").json()), 3)
