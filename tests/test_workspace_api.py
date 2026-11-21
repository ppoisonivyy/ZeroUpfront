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
        resources.enter_context(patch.dict(os.environ, DATABASE_URL=self.dsn, WORKSPACE_ENABLE_OCR="0"))
        self.client = resources.enter_context(TestClient(workspace_api.app))

    def replace(self, rev=1):
        return self.client.post(CASE + "/estimate", data=SAMPLE, headers=match(rev))

    def upload(self, data, rev=1):
        return self.client.post(CASE + "/estimate", files={"file": ("candidate.pdf", data, "application/pdf")},
                                data={"confirmed": "true"}, headers=match(rev))

    def approve(self, rev, reviewer="Demo coordinator"):
        return self.client.post(CASE + "/approve", json={"reviewer": reviewer}, headers=match(rev))

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
