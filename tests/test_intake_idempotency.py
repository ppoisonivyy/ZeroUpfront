"""Keyed admission and discharge OCR should enter the provider only once for a completed packet."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from io import BytesIO
import os
import shutil
from threading import Event
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.discharge_claim import load_discharge_fixture
from app.journey_examples import exhibits, NAMES, pdf
from app.workspace_api import app
from bench.case_revision import temporary_database


def scanned_packet(path):
    if path == "/api/cases":
        meta, raw = exhibits("mixed-scan")
        names = NAMES
        role = "estimate"
    else:
        meta, raw, names = load_discharge_fixture("aligned")
        role = "summary"
    text = PdfReader(BytesIO(raw[role])).pages[0].extract_text()
    raw[role] = pdf([], image=True)
    files = {key: (names[key], content, "application/pdf") for key, content in raw.items()}
    return dict(meta, confirmed="true", ocr="true"), files, text


@unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires disposable PostgreSQL")
class IntakeIdempotencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resources = ExitStack()
        cls.addClassCleanup(resources.close)
        dsn = resources.enter_context(temporary_database())
        resources.enter_context(patch.dict(os.environ, DATABASE_URL=dsn, WORKSPACE_AUTH_MODE="local",
                                          WORKSPACE_ENABLE_OCR="1", OPENAI_API_KEY="offline-test"))
        resources.enter_context(patch("app.workspace_api.OpenAI"))
        resources.enter_context(patch("app.discharge_api.OpenAI"))
        cls.client = resources.enter_context(TestClient(app))

    def test_waiting_duplicate_completed_replay_conflict_and_unkeyed_requests(self):
        for path in ("/api/cases", "/api/discharge"):
            with self.subTest(path=path):
                data, files, transcript = scanned_packet(path)
                entered, release = Event(), Event()
                def page(*_):
                    entered.set()
                    if not release.wait(8):
                        raise AssertionError("The simulated provider was not released.")
                    return transcript

                def post(key, fields=data):
                    headers = {"Idempotency-Key": key} if key else {}
                    return self.client.post(path, headers=headers, data=fields, files=files)

                with patch("app.intake_documents.ocr_page", side_effect=page) as provider, ThreadPoolExecutor(2) as pool:
                    first = pool.submit(post, "shared-key")
                    try:
                        self.assertTrue(entered.wait(5))
                        waiting = post("shared-key")
                        self.assertEqual((waiting.status_code, waiting.headers.get("Retry-After")), (409, "1"))
                        self.assertEqual(provider.call_count, 1)
                    finally:
                        release.set()
                    original = first.result(timeout=8)
                    self.assertEqual(original.status_code, 201, original.text)
                    replay = post("shared-key")
                    self.assertEqual((replay.status_code, replay.json()), (201, original.json()))
                    conflict = post("shared-key", data | {"procedure": "Changed procedure"})
                    self.assertEqual(conflict.status_code, 409)
                    self.assertNotIn("Retry-After", conflict.headers)
                    self.assertEqual(provider.call_count, 1)
                    first_unkeyed, second_unkeyed = post(None), post(None)
                    self.assertEqual([first_unkeyed.status_code, second_unkeyed.status_code], [201, 201])
                    self.assertNotEqual(first_unkeyed.json()["id"], second_unkeyed.json()["id"])
                    self.assertEqual(provider.call_count, 3)

    def test_failed_read_releases_key_for_later_retry(self):
        for path in ("/api/cases", "/api/discharge"):
            with self.subTest(path=path):
                data, files, transcript = scanned_packet(path)
                headers = {"Idempotency-Key": "retry-after-rollback"}
                with patch("app.intake_documents.ocr_page", side_effect=[ValueError("Invalid transcription."), transcript]) as provider:
                    for expected in (422, 201, 201):
                        reply = self.client.post(path, headers=headers, data=data, files=files)
                        self.assertEqual(reply.status_code, expected, reply.text)
                    self.assertEqual(provider.call_count, 2)
