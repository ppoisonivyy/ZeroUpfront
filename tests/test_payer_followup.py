"""Real HTTP correspondence binding and duplicate-send behavior on a disposable PostgreSQL hospital."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from hashlib import sha256
from io import BytesIO
import os
import shutil
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from app.journey_examples import pdf
from app.workspace_api import app
from bench.case_revision import temporary_database


@unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires disposable PostgreSQL")
class PayerFollowupTests(unittest.TestCase):
    def test_query_ownership_draft_binding_and_double_send(self):
        with ExitStack() as stack:
            dsn = stack.enter_context(temporary_database())
            stack.enter_context(patch.dict(os.environ, DATABASE_URL=dsn, WORKSPACE_AUTH_MODE="local"))
            client = stack.enter_context(TestClient(app))
            h = {"If-Match": '"1"'}
            src = pdf(["Synthetic query for missing documents"])
            def event(path, version, action, fields, original=None):
                return client.post(path + "/workflow", headers=h,
                                   data={"actor":"Coordinator", "action":action, "workflow_version":str(version), **fields},
                                   files={"file":("correspondence.pdf", original, "application/pdf")} if original else None)
            def opened_case():
                added = client.post("/api/discharge/examples/aligned")
                added.raise_for_status()
                path = "/api/discharge/" + added.json()["id"]
                client.post(path + "/approve", headers=h, json={"reviewer":"Coordinator"}).raise_for_status()
                event(path, 0, "submission", {"channel":"Payer portal", "reference":"S-1"}).raise_for_status()
                return path
            path = opened_case()
            query = {"reference":"Q-1", "terms":"Provide the records.", "outcome":"query", "confirmed":"true"}
            for invalid in ({"assign_follow_up":"true"}, {"owner":"Desk"}, {"follow_up_date":"2026-12-02"},
                            {"owner":"Desk", "follow_up_date":"2026-02-31"}):
                self.assertEqual(event(path, 1, "reply", query | invalid, src).status_code, 422)
            decision = event(path, 1, "reply", query, src).json()
            self.assertEqual(decision["follow_up"], {"assigned":False, "owner":None, "due":None})
            self.assertEqual(decision["payer_decision"]["follow_up_assignment"], "unassigned")
            reply_id = decision["events"][-1]["id"]
            send = {"confirmed":"true", "payer_event_id":reply_id, "reference":"T-1", "channel":"Portal",
                    "owner":"Weekend desk", "follow_up_date":"2026-12-03"}
            self.assertEqual(event(path, 2, "supplement", send | {"owner":""}, src).status_code, 422)
            self.assertEqual(event(path, 2, "supplement", send | {"payer_event_id":reply_id+100}, src).status_code, 409)
            thai = "ขอส่งเอกสารเพิ่มเติมเพื่อประกอบการพิจารณา"
            draft = {"workflow_version":2, "payer_event_id":reply_id, "text":"Records enclosed.\n" + thai}
            response = client.post(path + "/follow-up-draft", headers=h, json=draft)
            self.assertEqual(response.status_code, 200, response.text[:120])
            digest = sha256(response.content).hexdigest()
            self.assertEqual(response.headers["x-draft-sha256"], digest)
            page = PdfReader(BytesIO(response.content)).pages[0]
            text = page.extract_text()
            for expected in ("Q-1", "Records enclosed.", "Evidence revision: 1", decision["id"], decision["insurer"]):
                self.assertIn(expected, text)
            self.assertIn((b"\xfe\xff" + thai.encode("utf-16be")).hex().encode(), page.get_contents().get_data())
            foreign = opened_case()
            other = event(foreign, 1, "reply", query, src).json()
            other_answer = send | {"payer_event_id":other["events"][-1]["id"]}
            self.assertEqual(event(foreign, 2, "supplement", other_answer, response.content).status_code, 409)
            self.assertEqual(client.post(foreign + "/follow-up-draft", headers=h, json=draft).status_code, 409)
            stripped = PdfWriter()
            stripped.add_page(page)
            out = BytesIO()
            stripped.write(out)
            self.assertEqual(event(path, 2, "supplement", send | {"file_origin":"workspace"}, out.getvalue()).status_code, 409)
            current = send | {"file_origin":"workspace", "draft_sha256":digest}
            self.assertEqual(event(path, 2, "supplement", current, out.getvalue()).status_code, 409)
            revised = event(path, 2, "reply", query | {"reference":"Q-2", "assign_follow_up":"true",
                            "owner":"Monday desk", "follow_up_date":"2026-12-04"}, src).json()
            newer_id = revised["events"][-1]["id"]
            self.assertEqual(revised["follow_up"], {"assigned":True,"owner":"Monday desk","due":"2026-12-04"})
            self.assertEqual(event(path, 3, "supplement", current | {"payer_event_id":newer_id}, response.content).status_code, 409)
            self.assertEqual(client.post(path + "/follow-up-draft", headers=h,
                             json=draft | {"workflow_version":3}).status_code, 409)
            saved = client.post(path + "/follow-up-draft", headers=h,
                                json=draft | {"workflow_version":3, "payer_event_id":newer_id})
            saved.raise_for_status()
            outgoing = current | {"payer_event_id":newer_id, "draft_sha256":saved.headers["x-draft-sha256"]}
            with ThreadPoolExecutor(2) as pool:
                statuses = sorted(r.status_code for r in pool.map(
                    lambda _: event(path, 3, "supplement", outgoing, saved.content), range(2)))
            self.assertEqual(statuses, [200,409])
            ledger = client.get(path).json()
            sent = ledger["events"][-1]
            self.assertEqual(ledger["payer_decision"], revised["payer_decision"])
            self.assertEqual(ledger["follow_up"], {"owner":"Weekend desk","due":"2026-12-03","assigned":True})
            self.assertEqual(sent["data"]["source_verification"], "matched_saved_draft")
            self.assertEqual(sent["data"]["packet_sha256"], sha256(saved.content).hexdigest())
            self.assertEqual(client.get(sent["source_url"]).content, saved.content)
            self.assertEqual(client.get(decision["events"][-1]["source_url"]).content, src)
            self.assertEqual(client.post(path + "/follow-up-draft", headers=h,
                             json=draft | {"workflow_version":4, "payer_event_id":newer_id}).status_code, 409)
            next_query = event(path, 4, "reply", query | {"reference":"Q-3"}, src).json()
            manual = send | {"payer_event_id":next_query["events"][-1]["id"], "file_origin":"external"}
            self.assertEqual(event(path, 5, "supplement", manual | {"reference":"t-1"}, src).status_code, 409)
            external = event(path, 5, "supplement", manual | {"reference":"T-2"}, src).json()
            self.assertEqual(external["events"][-1]["data"]["source_verification"], "staff_attested")
