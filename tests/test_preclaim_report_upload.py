"""Review uploads through the mounted hospital and insurer desks on disposable PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from hashlib import sha256
from io import BytesIO
import json
import os
import secrets
import shutil
import unittest
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from pypdf import PdfWriter

from app import hospital_demo, preclaim_fixture as fixture, preclaims
from app.hospital_platform import Hospital, build_platform
from app.staff_access import provision
from app.workspace_api import create_workspace
from bench.case_revision import temporary_database


@unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires disposable PostgreSQL")
class UploadedReportTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.dsn = self.stack.enter_context(temporary_database())
        hospital = Hospital("canal-bridge", "Canal Bridge Demo Hospital", self.dsn)
        hospital_demo.seed(hospital)
        directory = {hospital.slug: {"hospital_name": hospital.name, "database_url_env": "REPORT_TEST_DB"}}
        self.stack.enter_context(patch.dict(os.environ, WORKSPACE_HOSPITALS=json.dumps(directory), REPORT_TEST_DB=self.dsn))
        platform = build_platform(create_workspace)
        self.staff = self.stack.enter_context(TestClient(platform))
        self.payer = TestClient(platform)
        self.finance = TestClient(platform)
        self.anon = TestClient(platform)
        password = secrets.token_urlsafe(30)
        self.api = "/h/canal-bridge/api"
        self.case = self.api + "/preclaims/" + fixture.CASE
        for client, user, role, payer in [(self.staff, "desk", "coordinator", None),
                                          (self.payer, "payer", "insurer", fixture.INSURER),
                                          (self.finance, "finance", "finance", None)]:
            self.addCleanup(client.close)
            provision(self.dsn, user, user.title(), password, role=role, insurer=payer)
            client.post(self.api + "/access/login", json={"username": user, "password": password}).raise_for_status()
        self.addCleanup(self.anon.close)

    def upload(self, raw, revision=1, client=None, confirmed=True):
        return (client or self.staff).post(self.case + "/reports", headers={"If-Match": f'"{revision}"'},
                                           data={"confirmed": str(confirmed).lower()},
                                           files={"file": ("report", raw, "application/octet-stream")})

    def attest(self, revision, page, **extra):
        return self.staff.post(self.case + "/reports/attest", headers={"If-Match": f'"{revision}"'},
                               json={"confirmed": True, "identity_confirmed": True, "page": page, **extra})

    def act(self, action, revision):
        return self.staff.post(self.case + "/" + action, headers={"If-Match": f'"{revision}"'}, json={"confirmed": True})

    def test_unsigned_mismatched_and_concurrent_edits(self):
        start = self.staff.get(self.case).json()
        report = next(source for source in start["sources"] if source["role"] == "report")
        signed = self.staff.get(self.case + "/report-example").content
        writer = PdfWriter()
        writer.append(BytesIO(self.staff.get(report["url"]).content))
        writer.append(BytesIO(signed))
        out = BytesIO()
        writer.write(out)
        good = out.getvalue()
        wrong = fixture.exhibits("Different Hospital")["replacement"]
        for client, status in [(self.payer, 403), (self.finance, 403), (self.anon, 401)]:
            self.assertEqual(self.upload(good, client=client).status_code, status)
        for raw in (b"not a report", wrong):
            self.assertEqual(self.upload(raw).status_code, 422)
        self.assertEqual(self.upload(good, confirmed=False).status_code, 422)
        self.assertEqual(self.staff.get(self.case).json()["revision"], 1)

        def concurrent(action):
            with ThreadPoolExecutor(2) as pool:
                return sorted(resp.status_code for resp in pool.map(lambda _: action(), range(2)))

        self.assertEqual(concurrent(lambda: self.upload(good)), [200, 412])
        packet = self.staff.get(self.case).json()
        self.assertEqual((packet["status"], packet["gap"]["code"], packet["draft_url"]),
                         ("needs_documents", "report_attestation_required", None))
        self.assertEqual(packet["report_evidence"]["identity_status"], "matched")
        self.assertEqual(self.act("attach-report", 2).status_code, 409)
        self.assertEqual(self.act("review", 2).status_code, 409)
        self.assertEqual(self.upload(good, 2).status_code, 409)
        item = next(x for x in self.staff.get(self.api + "/cases").json() if x["id"] == fixture.CASE)
        self.assertEqual(item["workflow_stage"], "needs_documents")
        self.assertEqual(self.attest(2, 3).status_code, 422)
        self.assertEqual(self.attest(2, 1, identity_confirmed=False).status_code, 422)
        self.assertEqual(concurrent(lambda: self.attest(2, 2)), [200, 412])
        attested = self.staff.get(self.case).json()
        source = next(s for s in attested["sources"] if s["role"] == "report")
        self.assertEqual((attested["report_evidence"]["page"], source["page"], source["quote"]), (2, 2, ""))
        self.assertEqual(self.staff.get(source["url"]).content, good)
        self.assertEqual(self.act("review", 3).status_code, 200)
        self.assertEqual(self.upload(good, 3).status_code, 409)

    def test_scanned_original_staff_attestation_and_exact_payer_copy(self):
        im = Image.new("RGB", (600, 300), "white")
        draw = ImageDraw.Draw(im)
        draw.multiline_text((15, 20), f"Patient: {fixture.PATIENT}\nMember: {fixture.MEMBER}\nCase: {fixture.CASE}\n"
                            f"Planned procedure: {fixture.PROCEDURE}\nIndication: persistent mechanical symptoms.\n"
                            "Treating physician mark (synthetic):", fill="black", spacing=6)
        draw.line([(22, 230), (40, 207), (37, 233), (64, 219), (60, 230), (91, 222)], fill="black", width=3)
        buf = BytesIO()
        im.save(buf, format="PNG")
        raw = buf.getvalue()

        # A failing head transaction must leave neither an unattached image nor a partial revision.
        with patch.object(preclaims, "_save_report_revision", side_effect=RuntimeError("interrupted write")):
            with self.assertRaisesRegex(RuntimeError, "interrupted write"):
                self.upload(raw)
        with psycopg.connect(self.dsn) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM zeroupfront_demo.documents WHERE digest=%s",
                                         (sha256(raw).hexdigest(),)).fetchone())
        packet = self.upload(raw).json()
        evidence = packet["report_evidence"]
        self.assertEqual((evidence["content_type"], evidence["pages"], evidence["status"], evidence["identity_status"],
                          evidence["sha256"]), ("image/png", 1, "needs_review", "manual_review", sha256(raw).hexdigest()))
        self.assertEqual(self.staff.get(evidence["original_url"]).content, raw)
        view = next(s for s in packet["sources"] if s["role"] == "report")
        self.assertEqual(view["quote"], "")
        self.assertEqual(len(fixture.pages(self.staff.get(view["url"]).content)), 1)
        self.assertEqual(self.payer.get(evidence["original_url"].replace("/preclaims/", "/insurer/preclaims/")).status_code, 404)
        final = self.attest(2, 1).json()
        self.assertEqual((final["revision"], final["status"], final["report_evidence"]["attested_by"]),
                         (3, "ready_for_review", "desk"))
        self.assertEqual(self.staff.get(self.case + "?revision=2").json()["report_evidence"]["status"], "needs_review")
        self.assertIn("visually attested", fixture.pages(self.staff.get(final["draft_url"]).content)[0])
        self.act("review", 3).raise_for_status()
        self.act("submit", 3).raise_for_status()
        payer_packet = self.payer.get(self.case.replace("/preclaims/", "/insurer/preclaims/")).json()
        original = self.payer.get(payer_packet["report_evidence"]["original_url"])
        self.assertEqual((original.status_code, original.headers["Content-Type"], original.content), (200, "image/png", raw))
        self.assertEqual(payer_packet["report_evidence"]["page"], 1)
        self.assertEqual(self.upload(raw, 3).status_code, 409)
