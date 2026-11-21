"""Exercise an evidence revision across two independently authenticated hospital and payer workspaces."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import os
import secrets
import shutil
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import psycopg

from app import hospital_demo, preclaim_fixture as fixture, preclaims
from app.hospital_platform import Hospital, build_platform
from app.staff_access import provision
from app.workspace_api import create_workspace
from app.workspace_store import _save_document
from bench.case_revision import temporary_database


@unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires PostgreSQL")
class PreclaimHandoffTests(unittest.TestCase):
    def test_original_replacement_review_and_payer_copy(self):
        with ExitStack() as stack:
            directory, environment, dsns = {}, {}, {}
            password = secrets.token_urlsafe(30)
            for slug, (name, code) in hospital_demo.HOSPITALS.items():
                dsn = dsns[slug] = stack.enter_context(temporary_database())
                key = f"PRECLAIM_{code}_DB"
                environment[key] = dsn
                directory[slug] = {"hospital_name": name, "database_url_env": key}
                hospital_demo.seed(Hospital(slug, name, dsn))
                for username, payer in (("desk", None), ("reviewer", fixture.INSURER), ("other", "Other payer")):
                    provision(dsn, username, username.title(), password, insurer=payer)
            stack.enter_context(patch.dict(os.environ, WORKSPACE_HOSPITALS=json.dumps(directory), **environment))
            platform = build_platform(create_workspace)
            # One live ASGI lifespan, independent cookie jars per user.
            staff = stack.enter_context(TestClient(platform))
            payer = TestClient(platform)
            other = TestClient(platform)
            stack.callback(payer.close)
            stack.callback(other.close)
            north = "/h/canal-bridge/api"
            south = "/h/lakeside/api"
            case = north + "/preclaims/" + fixture.CASE
            inbox = north + "/insurer/preclaims"
            reviewed = inbox + "/" + fixture.CASE
            self.assertEqual(staff.get(case).status_code, 401)
            for client, username in ((staff, "desk"), (payer, "reviewer"), (other, "other")):
                login = client.post(north + "/access/login", json={"username":username,"password":password})
                self.assertEqual(login.status_code, 200, login.text)
            def act(action, revision):
                return staff.post(case + "/" + action, json={"confirmed":True}, headers={"If-Match": f'"{revision}"'})
            def concurrent(action, revision):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    return sorted(resp.status_code for resp in pool.map(lambda _: act(action, revision), range(2)))
            self.assertEqual(staff.get(inbox).status_code, 403)
            self.assertEqual(payer.get(case).status_code, 403)
            self.assertEqual(payer.post(case + "/review", json={"confirmed":True}).status_code, 403)
            self.assertEqual(payer.get(inbox).json(), [])
            self.assertEqual(payer.get(reviewed).status_code, 404)
            self.assertEqual(payer.get(south + "/insurer/preclaims").status_code, 401)
            summary = next(x for x in staff.get(north + "/cases").json() if x["id"] == fixture.CASE)
            self.assertEqual((summary["input_kind"], summary["workflow_stage"]), ("payer_preclaim", "needs_documents"))
            original = staff.get(case).json()
            self.assertEqual(original["gap"]["code"], "missing_signed_report")
            self.assertTrue(original["rule"]["verified"])
            physical_page = original["rule"]["page"]
            self.assertEqual(physical_page, 12)
            policy = fixture.pages(staff.get(original["rule"]["source_url"]).content)
            self.assertIn(original["rule"]["quote"], policy[physical_page - 1])
            sources = {s["role"]: s["url"] for s in original["sources"]}
            original_report = staff.get(sources["report"]).content
            self.assertIn("Treating physician signature: Pending", fixture.pages(original_report)[0])
            self.assertEqual(staff.get(case + "/revisions/1/sources/request").status_code, 404)
            replacement = staff.get(case + "/report-example").content
            self.assertIn(fixture.SIGNATURE, fixture.pages(replacement)[0])
            self.assertEqual(act("review", 1).status_code, 409)
            self.assertEqual(act("submit", 1).status_code, 409)
            self.assertEqual(staff.post(case + "/attach-report", json={"confirmed":False},
                            headers={"If-Match":'"1"'}).status_code, 422)
            self.assertEqual(concurrent("attach-report", 1), [200, 412])
            self.assertEqual(act("review", 1).status_code, 412)
            second = staff.get(case).json()
            self.assertEqual((second["revision"], second["status"], second["issues"]), (2, "ready_for_review", []))
            self.assertEqual(staff.get(sources["report"]).content, original_report)
            self.assertEqual(staff.get(second["sources"][1]["url"]).content, replacement)
            self.assertIn("Draft for hospital staff review.", fixture.pages(staff.get(second["draft_url"]).content)[0])
            self.assertEqual(act("submit", 2).status_code, 409)
            self.assertEqual(concurrent("review", 2), [200, 409])
            self.assertEqual(payer.get(inbox).json(), [])
            saved_form = staff.get(second["draft_url"]).content
            self.assertIn("Hospital staff review: Desk", fixture.pages(saved_form)[0])
            self.assertEqual(concurrent("submit", 2), [200, 409])
            visible = payer.get(inbox).json()
            self.assertEqual(len(visible), 1)
            shared = payer.get(reviewed + "?revision=2").json()
            self.assertEqual(shared, visible[0])
            self.assertEqual((shared["id"], shared["submitted_revision"], shared["status"]),
                             (fixture.CASE, 2, "waiting_for_insurer"))
            self.assertEqual(payer.get(shared["draft_url"]).content, saved_form)
            for src in shared["sources"]:
                staff_url = next(doc["url"] for doc in second["sources"] if doc["role"] == src["role"])
                self.assertEqual(staff.get(staff_url).content, payer.get(src["url"]).content)
                self.assertEqual(other.get(src["url"]).status_code, 404)
            self.assertEqual(payer.get(reviewed + "?revision=1").status_code, 404)
            self.assertEqual(payer.get(reviewed + "/revisions/1/sources/report").status_code, 404)
            self.assertEqual(other.get(inbox).json(), [])
            self.assertEqual(other.get(reviewed).status_code, 404)
            self.assertEqual(other.get(shared["draft_url"]).status_code, 404)
            self.assertEqual(payer.get(south + "/insurer/preclaims").status_code, 401)
            for client, username in ((staff, "desk"), (payer, "reviewer")):
                self.assertEqual(client.post(south + "/access/login",
                                 json={"username":username,"password":password}).status_code, 200)
            self.assertEqual(payer.get(south + "/insurer/preclaims").json(), [])
            self.assertEqual(payer.get(shared["draft_url"].replace("/canal-bridge/", "/lakeside/")).status_code, 404)
            south_case = case.replace("/canal-bridge/", "/lakeside/")
            self.assertEqual(staff.get(south_case).json()["status"], "needs_documents")
            self.assertNotEqual(staff.get(south_case + "/report-example").content, replacement)
            self.assertEqual(staff.get(case + "?revision=1").json()["status"], "needs_documents")
            preclaims.seed(dsns["canal-bridge"], hospital_demo.HOSPITALS["canal-bridge"][0])
            self.assertEqual(staff.get(case).json()["submitted_revision"], 2)

            # A foreign hospital's genuine signed sample must not satisfy the southern encounter.
            with psycopg.connect(dsns["lakeside"]) as db:
                digest = _save_document(db, replacement)
                db.execute("UPDATE zeroupfront_demo.preclaims SET replacement=%s WHERE id=%s", (digest, fixture.CASE))
            reject = staff.post(south_case + "/attach-report", json={"confirmed":True}, headers={"If-Match":'"1"'})
            self.assertEqual(reject.status_code, 422)
            # Physical page verification must read stored evidence, even when all metadata still matches.
            misplaced_clause = fixture.pdf("Wrong edition", [("Wrong page", [fixture.RULE])])
            with psycopg.connect(dsns["lakeside"]) as db:
                digest = _save_document(db, misplaced_clause)
                db.execute("UPDATE zeroupfront_demo.preclaim_revisions SET policy=%s WHERE case_id=%s AND revision=1",
                           (digest, fixture.CASE))
            held = staff.get(south_case).json()
            self.assertFalse(held["rule"]["verified"])
            self.assertEqual(held["gap"]["code"], "unverified_rule")
            self.assertEqual(staff.post(south_case + "/attach-report", json={"confirmed":True},
                             headers={"If-Match":'"1"'}).status_code, 409)
