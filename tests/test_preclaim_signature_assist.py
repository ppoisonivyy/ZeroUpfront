"""Opt-in, evidence-bound visual hints. Every provider response is a test double."""
import base64
from io import BytesIO
import json
import os
import secrets
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from openai import OpenAIError
from PIL import Image

from app import hospital_demo, preclaim_fixture as fixture, preclaim_signature_assist as assist
from app.hospital_platform import Hospital, OPENAI_BASE, build_platform, current_hospital
from app.staff_access import provision
from app.workspace_api import create_workspace
from app.workspace_store import document_digest
from bench.case_revision import temporary_database


def answer(status, pages):
    return SimpleNamespace(status="completed", output_parsed=assist.CandidatePages(status=status, pages=pages))


class VisualHintTests(unittest.TestCase):
    @patch("app.preclaim_signature_assist.OpenAI")
    def test_unusable_suggestions_are_uncertain_and_never_guess_a_page(self, provider):
        parse = provider.return_value.__enter__.return_value.responses.parse
        for response in [answer("suggested", [0]), answer("suggested", [2]), answer("suggested", [1, 1]),
                         answer("suggested", []), answer("uncertain", [1]), SimpleNamespace(status="incomplete", output_parsed=None)]:
            with self.subTest(response=response):
                parse.return_value = response
                self.assertEqual(assist._suggest(b"synthetic", "image/png", 1), {"status": "uncertain", "pages": []})
        self.assertTrue(all(call.kwargs["store"] is False for call in parse.call_args_list))

    @patch("app.preclaim_signature_assist.OpenAI")
    def test_separate_purpose_approval_and_provider_failure(self, provider):
        hospital = Hospital("north", "North", "unused", frozenset({"hosted_ocr"}))
        token = current_hospital.set(hospital)
        try:
            with self.assertRaises(HTTPException) as denied:
                assist._suggest(b"synthetic", "image/png", 1)
            self.assertEqual(denied.exception.status_code, 403)
            provider.assert_not_called()
        finally:
            current_hospital.reset(token)
        with patch.dict(os.environ, WORKSPACE_ENABLE_SIGNATURE_HINT="1", OPENAI_API_KEY="synthetic"):
            self.assertFalse(assist.enabled())
        provider.return_value.__enter__.return_value.responses.parse.side_effect = OpenAIError("mock failure")
        with self.assertRaises(HTTPException) as failure:
            assist._suggest(b"synthetic", "image/png", 1)
        self.assertEqual(failure.exception.status_code, 503)

    @unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires PostgreSQL")
    @patch("app.preclaim_signature_assist.OpenAI")
    def test_approved_coordinator_click_is_bound_to_original_and_current_pending_revision(self, provider):
        dsn = self.enterContext(temporary_database())
        password = secrets.token_urlsafe(28)
        hospital = Hospital("canal-bridge", "Canal Bridge Demo Hospital", dsn)
        directory = {hospital.slug: dict(hospital_name=hospital.name, database_url_env="HINT_TEST_DB",
                                         approved_openai_uses=[assist.PURPOSE])}
        self.enterContext(patch.dict(os.environ, WORKSPACE_HOSPITALS=json.dumps(directory), HINT_TEST_DB=dsn,
                                     WORKSPACE_AUTH_MODE="staff", OPENAI_BASE_URL=OPENAI_BASE,
                                     OPENAI_API_KEY="synthetic-test", WORKSPACE_ENABLE_SIGNATURE_HINT="0"))
        hospital_demo.seed(hospital)
        provision(dsn, "desk", "Coordinator", password)
        provision(dsn, "reviewer", "Insurer", password, insurer=fixture.INSURER)
        platform = build_platform(create_workspace)
        client = self.enterContext(TestClient(platform))
        insurer = TestClient(platform)
        self.addCleanup(insurer.close)
        api = "/h/canal-bridge/api"
        case = api + "/preclaims/" + fixture.CASE
        def upload(raw, kind, revision):
            result = client.post(case + "/reports", headers={"If-Match": f'"{revision}"'}, data={"confirmed": "true"},
                                 files={"file": ("synthetic-report", raw, kind)})
            self.assertEqual(result.status_code, 200, result.text)
            return result.json()
        for who, session in (("desk", client), ("reviewer", insurer)):
            self.assertEqual(session.post(api + "/access/login", json={"username": who, "password": password}).status_code, 200)
        raw = fixture.pdf("Synthetic physician report", [("Page one", []), ("Page two", [])])
        packet = upload(raw, "application/pdf", 1)
        sha = document_digest(raw)
        path = case + "/revisions/2/report-signature-hint"
        options = {"sha256": sha, "confirmed": True}
        parse = provider.return_value.__enter__.return_value.responses.parse
        self.assertFalse(packet["report_signature_hint_enabled"])
        self.assertEqual(client.post(path, json=options).status_code, 503)
        self.assertEqual(insurer.post(path, json=options).status_code, 403)
        with patch.dict(os.environ, WORKSPACE_ENABLE_SIGNATURE_HINT="1", OPENAI_BASE_URL="https://example.invalid/v1"):
            self.assertEqual(client.post(path, json=options).status_code, 403)
        self.enterContext(patch.dict(os.environ, WORKSPACE_ENABLE_SIGNATURE_HINT="1"))
        self.assertEqual(client.post(path, json={**options, "confirmed": False}).status_code, 422)
        self.assertEqual(client.post(path, json={**options, "sha256": "a"*64}).status_code, 409)
        with patch.object(assist, "MAX_BYTES", len(raw) - 1):
            self.assertEqual(client.post(path, json=options).status_code, 422)
        provider.assert_not_called()
        parse.return_value = answer("suggested", [2])
        result = client.post(path, json=options)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json(), {"revision": 2, "sha256": sha, "status": "suggested", "pages": [2]})
        self.assertEqual(result.headers["cache-control"], "private, no-store")
        linked = parse.call_args.kwargs["input"][0]["content"][0]["file_data"]
        self.assertEqual(base64.b64decode(linked.split(",", 1)[1]), raw)
        self.assertEqual(provider.call_args.kwargs["base_url"], OPENAI_BASE)
        self.assertFalse(provider.call_args.kwargs["http_client"].follow_redirects)
        self.assertEqual(client.get(case).json()["report_evidence"]["status"], "needs_review")

        stream = BytesIO()
        Image.new("RGB", (40, 20), "white").save(stream, format="JPEG")
        image = stream.getvalue()
        def replace_during_inference(**kwargs):
            upload(image, "image/jpeg", 2)
            return answer("suggested", [2])
        parse.side_effect = replace_during_inference
        self.assertEqual(client.post(path, json=options).status_code, 409)
        parse.side_effect = None
        parse.return_value = answer("uncertain", [])
        image_result = client.post(case + "/revisions/3/report-signature-hint", json={
            "confirmed": True, "sha256": document_digest(image)})
        self.assertEqual(image_result.json()["status"], "uncertain")
        item = parse.call_args.kwargs["input"][0]["content"][0]
        self.assertEqual(item["type"], "input_image")
        self.assertEqual(base64.b64decode(item["image_url"].split(",", 1)[1]), image)
        self.assertEqual(client.get(case).json()["report_evidence"]["status"], "needs_review")

        count = parse.call_count
        too_many_pages = fixture.pdf("Long synthetic report", [("Another page", [])] * 9)
        upload(too_many_pages, "application/pdf", 3)
        self.assertEqual(client.post(case + "/revisions/4/report-signature-hint", json={
            "confirmed": True, "sha256": document_digest(too_many_pages)}).status_code, 422)
        self.assertEqual(count, parse.call_count)
