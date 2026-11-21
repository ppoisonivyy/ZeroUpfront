"""Exercise the coordinator HTTP contract and revision races against isolated PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from io import BytesIO
import os
from pathlib import Path
import shutil
from threading import Barrier, Event
import unittest
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from fastapi.testclient import TestClient
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from app import workspace_api
from bench.case_revision import temporary_database


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CASE = "/api/cases/Z002"
SAMPLE = {"sample": "true", "confirmed": "true"}


def match(rev):
    return {"If-Match": f'"{rev}"'}


@unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires disposable PostgreSQL tools")
class WorkspaceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = ExitStack()
        cls.addClassCleanup(cls.cluster.close)
        cls.admin_dsn = cls.cluster.enter_context(temporary_database())

    def setUp(self):
        name = self._testMethodName
        with psycopg.connect(self.admin_dsn, autocommit=True) as db:
            db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        self.dsn = make_conninfo(self.admin_dsn, dbname=name)
        resources = ExitStack()
        self.addCleanup(resources.close)
        resources.enter_context(patch.dict(os.environ, DATABASE_URL=self.dsn, WORKSPACE_AUTH_MODE="local", WORKSPACE_ENABLE_OCR="0"))
        self.client = resources.enter_context(TestClient(workspace_api.app))

    def replace(self, rev=1):
        return self.client.post(CASE + "/estimate", data=SAMPLE, headers=match(rev))

    def upload(self, data, rev=1):
        return self.client.post(CASE + "/estimate", files={"file": ("candidate.pdf", data, "application/pdf")},
                                data={"confirmed": "true"}, headers=match(rev))

    def approve(self, rev, reviewer="Demo coordinator"):
        return self.client.post(CASE + "/approve", json={"reviewer": reviewer}, headers=match(rev))

    def intake(self, **overrides):
        fields = {"member": "DEMO-Z002", "insurer": "Alder Transit Cover", "policy_edition": "AT-2026.1",
                  "procedure": "Wrist fracture fixation", "admission_date": "2026-11-25", "confirmed": "true"}
        docs = {"policy": (FIXTURES / "policies/alder.pdf").read_bytes(),
                "plan": (FIXTURES / "cases/Z002/plan.pdf").read_bytes(),
                "estimate": (FIXTURES / "cases/Z002/estimate.pdf").read_bytes()} | overrides
        return self.client.post("/api/cases", data=fields,
                                files={role: (role + ".pdf", raw, "application/pdf") for role, raw in docs.items()})

    def event(self, case, rev, version, action, *, document=None, **fields):
        data = {"actor": "Demo staff", "action": action, "workflow_version": str(version)} | fields
        files = {"file": ("correspondence.pdf", document, "application/pdf")} if document else None
        return self.client.post(case + "/workflow", headers=match(rev), data=data, files=files)

    @staticmethod
    def letter(text):
        stream = BytesIO()
        page = Canvas(stream)
        page.drawString(50, 700, text)
        page.save()
        return stream.getvalue()

    def test_case_hold_survives_revision_and_blocks_release_until_resolved(self):
        created = self.event(CASE, 1, 0, "hold", category="policy", notes="Obtain signed rider.")
        self.assertEqual(created.status_code, 200, created.text)
        hold = created.json()["open_holds"][0]
        self.assertEqual(self.replace().json()["open_hold_count"], 1)
        self.assertEqual(self.approve(2).status_code, 409)
        stale = self.event(CASE, 1, 1, "resolve_hold", hold_id=str(hold["id"]), notes="Old tab.")
        self.assertEqual(stale.status_code, 412)
        closed = self.event(CASE, 2, 0, "resolve_hold", hold_id=str(hold["id"]), notes="Rider verified in portal.")
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertEqual(closed.json()["open_hold_count"], 0)
        self.assertEqual(self.approve(2).status_code, 200)
        self.assertEqual(self.event(CASE, 2, 1, "hold", category="consent", notes="Consent withdrawn.").status_code, 200)
        self.assertEqual(self.client.get(CASE + "/export?revision=2").status_code, 409)
        self.assertEqual(self.event(CASE, 2, 2, "submission", reference="X", channel="portal").status_code, 409)
        worklist = self.client.get("/api/cases").json()
        self.assertEqual(next(c for c in worklist if c["id"] == "Z002")["open_hold_count"], 1)
        self.assertEqual(self.client.get(CASE, params={"revision": 1}).json()["open_holds"], [hold])

    def test_new_intake_replacement_and_immutable_clarification(self):
        self.assertEqual(self.intake(plan=b"not a PDF").status_code, 422)
        self.assertEqual(len(self.client.get("/api/cases").json()), 3)
        new = self.intake()
        self.assertEqual(new.status_code, 201, new.text)
        case = "/api/cases/" + new.json()["id"]
        self.assertTrue(new.json()["intake"])
        self.assertEqual(new.json()["status"], "needs_itemization")
        self.assertNotIn("ocr_pages", new.json())
        revised = self.client.post(case + "/estimate", data={"confirmed": "true"}, headers=match(1),
                                   files={"file": ("new.pdf", (FIXTURES / "cases/Z002/revised-estimate.pdf").read_bytes())})
        self.assertEqual(revised.status_code, 200, revised.text)
        self.assertEqual(revised.json()["status"], "ready_for_review")
        self.assertEqual((revised.json()["revision"], new.json()["revision"]), (2, 1))
        self.assertEqual(self.client.get(new.json()["sources"][0]["url"]).status_code, 200)
        foreign = self.intake(policy=self.letter("Independently worded policy. Payment terms require clarification."))
        self.assertEqual(foreign.status_code, 201, foreign.text)
        other = "/api/cases/" + foreign.json()["id"]
        self.assertEqual(foreign.json()["status"], "needs_review")
        self.assertEqual(self.client.get(other + "/clarification?revision=1").status_code, 409)
        review = {"actor": "Taylor", "fields": {"member": {"role": "plan", "page": 1, "quote": "Member DEMO-Z002"}}}
        recorded = self.client.post(other + "/evidence", headers=match(1), json=review)
        self.assertEqual(recorded.status_code, 200, recorded.text)
        self.assertTrue(recorded.json()["clarification_available"])
        self.assertEqual(recorded.json()["manual_review"]["actor"], "Taylor")
        self.assertEqual(recorded.json()["status"], "needs_review")
        clarification = self.client.get(other + "/clarification?revision=2")
        self.assertEqual(clarification.status_code, 200, clarification.text[:200])
        self.assertEqual(len(PdfReader(BytesIO(clarification.content)).attachments), 3)
        self.assertEqual(self.client.get(other + "/export?revision=2").status_code, 409)

    def test_payer_query_supplement_guarantee_admission_and_separate_deposit(self):
        self.assertEqual(self.replace().status_code, 200)
        self.assertEqual(self.approve(2).status_code, 200)
        send = self.event(CASE, 2, 0, "submission", reference="S-1", channel="Payer portal")
        self.assertEqual(send.status_code, 200, send.text)
        self.assertEqual(send.json()["insurer_status"], "submitted")
        letter = self.letter("Synthetic payer correspondence for DEMO-Z002")
        query = self.event(CASE, 2, 1, "reply", outcome="query", reference="Q-1", terms="Provide detail.",
                           document=letter, confirmed="true")
        self.assertEqual(query.status_code, 200, query.text)
        source = query.json()["events"][-1]["source_url"]
        self.assertEqual(self.client.get(source).content, letter)
        self.assertEqual(self.event(CASE, 2, 1, "reply", outcome="denied").status_code, 409)
        supplement = self.event(CASE, 2, 2, "supplement", reference="Q-1", notes="Sent follow-up pages.",
                                document=self.letter("Further information"), confirmed="true")
        self.assertEqual(supplement.json()["insurer_status"], "supplement_sent")
        guarantee = self.event(CASE, 2, 3, "reply", outcome="guaranteed", reference="G-1", terms="THB 82,000",
                               document=letter, confirmed="true", amount="82000", currency="thb",
                               valid_from="2026-11-20", valid_until="2026-12-01", facility="Demo Hospital",
                               covered_procedure="Wrist fracture fixation", covered_member="DEMO-Z002",
                               patient_share="Patient pays the amount over the letter limit.")
        self.assertEqual(guarantee.json()["insurer_status"], "guaranteed", guarantee.text)
        self.assertIsNone(guarantee.json()["deposit_decision"])
        self.assertEqual(self.client.get("/api/cases").json()[1]["insurer_status"], "guaranteed")
        facts = {"actual_member": "DEMO-Z002", "actual_procedure": "Wrist fracture fixation",
                 "actual_admission_date": "2026-11-25", "notes": "Staff checked the current letter.",
                 "actual_facility": "Demo Hospital", "currency": "THB", "letter_confirmed": "true"}
        admission = self.event(CASE, 2, 4, "admission", **facts, actual_amount="95000")
        self.assertEqual(admission.json()["admission_check"]["outcome"], "mismatch")
        self.assertIn("amount_or_currency", admission.json()["admission_check"]["differences"])
        corrected = self.event(CASE, 2, 5, "admission", **facts, actual_amount="82000")
        self.assertEqual(corrected.json()["admission_check"]["outcome"], "matched")
        self.assertIsNone(corrected.json()["deposit_decision"])
        deposit = self.event(CASE, 2, 6, "deposit", outcome="reduced", amount="5000", currency="THB",
                             notes="Finance recorded the patient's remaining share.")
        self.assertEqual(deposit.json()["deposit_decision"]["amount"], "5000")
        self.assertEqual(deposit.json()["insurer_status"], "guaranteed")
        self.assertEqual(self.client.get(CASE + "/export?revision=2").status_code, 200)
        self.assertEqual(self.upload((FIXTURES / "cases/Z002/estimate.pdf").read_bytes(), 2).json()["events"], [])
        prior = self.client.get(CASE + "?revision=2").json()
        self.assertEqual(len(prior["events"]), 7)
        late = self.event(CASE, 3, 7, "reply", target_revision="2", outcome="denied", reference="D-2",
                          document=letter, confirmed="true", terms="Revised decision.")
        self.assertEqual(late.json()["revision"], 2)
        self.assertEqual(late.json()["insurer_status"], "denied")
        self.assertIsNone(late.json()["deposit_decision"])
        self.assertEqual(self.client.get(CASE).json()["insurer_status"], "not_sent")

    def test_seeds_and_case_bound_immutable_sources(self):
        queue = self.client.get("/api/cases").json()
        self.assertEqual([(row["id"], row["status"]) for row in queue],
                         [("Z001", "ready_for_review"), ("Z002", "needs_itemization"), ("Z003", "possible_exclusion")])
        current = self.client.get(CASE).json()
        sources = {item["role"]: item for item in current["sources"]}
        original = self.client.get(sources["estimate"]["url"]).content
        self.assertEqual(original, (FIXTURES / "cases/Z002/estimate.pdf").read_bytes())
        sample = self.client.get(CASE + "/sample-estimate")
        self.assertEqual(sample.content, (FIXTURES / "cases/Z002/revised-estimate.pdf").read_bytes())
        response = self.upload(sample.content)
        self.assertEqual(response.status_code, 200, response.text)
        updated = response.json()
        self.assertEqual((updated["revision"], updated["total"], updated["status"]), (2, 82000, "ready_for_review"))
        self.assertEqual([line["amount"] for line in updated["lines"]], [52000, 30000])
        self.assertEqual(self.client.get(sources["estimate"]["url"]).content, original)
        self.assertEqual(self.client.get(CASE, params={"revision": 1}).json()["status"], "needs_itemization")
        self.assertEqual(self.client.get(CASE, params={"revision": 20}).status_code, 404)
        self.assertEqual(self.client.get("/api/cases/Z003/sample-estimate").status_code, 404)
        self.assertEqual(self.replace(2).json()["revision"], 2)
        with TestClient(workspace_api.app) as restarted:
            self.assertEqual(restarted.get(CASE).json()["revision"], 2)

    def test_invalid_or_unconfirmed_file_never_reaches_cloud_or_changes_case(self):
        with patch.dict(os.environ, WORKSPACE_ENABLE_OCR="1"), patch.object(workspace_api, "OpenAI") as cloud:
            for data in (b"no pdf", b"%PDF-1.4 invalid bytes", (FIXTURES / "cases/Z003/estimate.pdf").read_bytes()):
                with self.subTest(size=len(data)):
                    self.assertEqual(self.upload(data).status_code, 422)
            cloud.assert_not_called()
        self.assertEqual(self.upload(b"a" * (workspace_api.MAX_UPLOAD_BYTES + 1)).status_code, 413)
        self.assertEqual(self.client.post(CASE + "/estimate", data={"sample": "true"},
                                          headers=match(1)).status_code, 422)
        for header, status in (({}, 428), ({"If-Match": "1"}, 400), ({"If-Match": "*"}, 400)):
            self.assertEqual(self.client.post(CASE + "/estimate", data=SAMPLE, headers=header).status_code, status)
        self.assertEqual(self.client.get(CASE).json()["revision"], 1)
        self.assertEqual(self.approve(1).status_code, 409)
        self.assertEqual(self.client.get(CASE + "/export?revision=1").status_code, 409)

    def test_racing_replacements_and_approval_replays(self):
        def simultaneously(action):
            barrier = Barrier(2, timeout=10)

            def run():
                barrier.wait()
                return action()

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(run) for _ in range(2)]
                return [future.result(timeout=20) for future in futures]

        responses = simultaneously(self.replace)
        self.assertEqual(sorted(response.status_code for response in responses), [200, 412])
        self.assertEqual(self.approve(1).status_code, 412)
        self.assertEqual(self.approve(2, "Demo\nname").status_code, 422)
        approved = simultaneously(lambda: self.approve(2))
        self.assertEqual([response.status_code for response in approved], [200, 200])
        self.assertEqual(approved[0].json(), approved[1].json())
        self.assertEqual(self.approve(2, "Another demo coordinator").status_code, 409)
        packet = self.client.get(CASE + "/export?revision=2")
        self.assertEqual(packet.status_code, 200, packet.text[:100])
        self.assertTrue(packet.content.startswith(b"%PDF"))
        actual = PdfReader(BytesIO(packet.content)).attachments
        self.assertCountEqual((uploads[0] for uploads in actual.values()),
                              (self.client.get(source["url"]).content for source in approved[0].json()["sources"]))
        self.assertEqual(self.client.get(CASE).json()["insurer_status"], "not_sent")
        original = (FIXTURES / "cases/Z002/estimate.pdf").read_bytes()
        self.assertEqual(self.upload(original, 2).json()["status"], "needs_itemization")
        self.assertEqual(self.client.get(CASE + "/export?revision=2").status_code, 412)
        self.assertEqual(self.client.get(CASE + "?revision=2").json()["reviewer"], "Demo coordinator")

    def test_replacement_during_export_discards_generated_packet(self):
        self.assertEqual(self.replace().status_code, 200)
        self.assertEqual(self.approve(2).status_code, 200)
        rendering, release = Event(), Event()
        real_packet = workspace_api.packet_bytes

        def delayed(case, originals):
            rendering.set()
            if not release.wait(10):
                raise AssertionError("timed out waiting for replacement")
            return real_packet(case, originals)

        with patch.object(workspace_api, "packet_bytes", delayed), ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.client.get, CASE + "/export?revision=2")
            try:
                self.assertTrue(rendering.wait(10))
                self.assertEqual(self.upload((FIXTURES / "cases/Z002/estimate.pdf").read_bytes(), 2).status_code, 200)
            finally:
                release.set()
            response = pending.result(timeout=15)
        self.assertEqual(response.status_code, 412)
        self.assertEqual(response.headers["content-type"], "application/json")

    def test_export_validates_persisted_originals_against_the_approved_manifest(self):
        self.assertEqual(self.replace().status_code, 200)
        reviewed = self.approve(2).json()
        estimate = next(source for source in reviewed["sources"] if source["role"] == "estimate")
        with psycopg.connect(self.dsn) as db:
            db.execute("UPDATE zeroupfront_demo.documents SET pdf=%s WHERE digest=%s",
                       (b"invalid stored PDF content", estimate["sha256"]))
        packet = self.client.get(CASE + "/export?revision=2")
        self.assertEqual(packet.status_code, 409)
        self.assertEqual(packet.headers["content-type"], "application/json")
