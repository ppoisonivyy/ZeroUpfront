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
            self.assertEqual(len(client.get(base + "/discharge").json()), 4)
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
            self.assertEqual(len(client.get(base + "/discharge").json()), 4)

    def test_seeded_pattaya_claim_is_scoped_and_retains_simulated_receipts(self):
        with ExitStack() as stack:
            directory, connections, hospitals = {}, {}, {}
            password = secrets.token_urlsafe(32)
            for slug, (name, code) in hospital_demo.HOSPITALS.items():
                dsn = stack.enter_context(temporary_database())
                key = f"TEST_{code}_DSN"
                directory[slug] = {"hospital_name": name, "database_url_env": key}
                connections[key] = dsn
                hospital = hospitals[slug] = Hospital(slug, name, dsn)
                hospital_demo.seed(hospital)
                provision(dsn, "judge", f"{code} coordinator", password)
            stack.enter_context(patch.dict(os.environ, WORKSPACE_HOSPITALS=json.dumps(directory), **connections))
            client = stack.enter_context(TestClient(build_platform(create_workspace)))
            for slug in directory:
                base = f"/h/{slug}/api"
                self.assertEqual(client.get(base + "/discharge").status_code, 401)
                self.assertEqual(client.post(base + "/access/login", json={"username":"judge","password":password}).status_code, 200)
                self.assertEqual(client.post(base + "/discharge/examples/pattaya_fx").status_code, 404)

            base = "/h/canal-bridge/api/discharge"
            case_url = base + "/D-CB-PATTAYA"
            south_case = "/h/lakeside/api/discharge/D-LS-PATTAYA"
            self.assertEqual(client.get(base + "/D-LS-PATTAYA/pattaya?revision=1").status_code, 404)
            self.assertEqual(client.get(base + "/D-CB-001/pattaya?revision=1").status_code, 404)
            self.assertEqual(client.get(case_url + "/pattaya?revision=1").json()["next_action"], "book")
            case = client.get(case_url).json()
            self.assertEqual(case["staff_practice_hospital"], "canal-bridge")
            proof = next(row["source_url"] for row in case["events"] if row["kind"] == "reply")
            self.assertTrue(proof.startswith(base))
            guarantee = PdfReader(BytesIO(client.get(proof).content)).pages[0].extract_text()
            self.assertIn("Hospital: Canal Bridge Demo Hospital", guarantee)
            self.assertIn("Encounter: VISIT-CB-FX", guarantee)
            self.assertEqual(client.post(case_url + "/pattaya/agent-review", json={"confirmed":True},
                                         headers={"If-Match":'"1"'}).status_code, 404)

            version = case["workflow_version"]
            for action in ("book_forward", "record_short_credit", "record_topup"):
                response = client.post(case_url + "/pattaya/actions", headers={"If-Match":'"1"'},
                                       json={"action":action,"confirmed":True,"workflow_version":version})
                self.assertEqual(response.status_code, 200, response.text)
                saved = response.json()
                version = saved["workflow_version"]
                self.assertEqual(saved["events"][-1]["username"], "judge")
                self.assertEqual(saved["events"][-1]["actor"], "CB coordinator")
            hospital_demo.seed(hospitals["canal-bridge"])
            self.assertEqual(client.get(case_url + "/pattaya?revision=1").json()["next_action"], "complete")
            self.assertEqual(client.get(south_case + "/pattaya?revision=1").json()["next_action"], "book")
