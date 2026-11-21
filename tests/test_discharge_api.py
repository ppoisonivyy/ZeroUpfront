"""Exercise the independent discharge and payment workflows through their public API."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader
import httpx
from openai import AuthenticationError, APIConnectionError, RateLimitError

from app.discharge_claim import load_discharge_fixture
from app.journey_examples import pdf
from app.workspace_api import app
from app.workspace_http_common import ocr_service_error
from bench.case_revision import temporary_database


ROOT = "/api/discharge"


def match(rev):
    return {"If-Match": f'"{rev}"'}


@unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires disposable PostgreSQL")
class DischargeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resources = ExitStack()
        cls.addClassCleanup(resources.close)
        dsn = resources.enter_context(temporary_database())
        resources.enter_context(
            patch.dict(os.environ, DATABASE_URL=dsn, WORKSPACE_AUTH_MODE="local", WORKSPACE_ENABLE_OCR="0")
        )
        cls.client = resources.enter_context(TestClient(app))

    def new(self, scenario):
        response = self.client.post(ROOT + "/examples/" + scenario)
        self.assertEqual(response.status_code, 201, response.text)
        return ROOT + "/" + response.json()["id"], response.json()

    def approve(self, path, rev):
        return self.client.post(path + "/approve", headers=match(rev), json={"reviewer": "Discharge reviewer"})

    def event(self, path, rev, version, action, fields, raw=None):
        return self.client.post(
            path + "/workflow",
            headers=match(rev),
            data=dict(action=action, workflow_version=version, actor="Hospital finance") | fields,
            files={"file": ("reply.pdf", raw, "application/pdf")} if raw else None,
        )

    def test_all_declared_scenarios_have_expected_http_disposition_and_findings(self):
        manifest = Path(__file__).resolve().parents[1] / "fixtures/discharge/expected.json"
        for name, expected in json.loads(manifest.read_text()).items():
            with self.subTest(name=name):
                path, case = self.new(name)
                self.assertEqual(case["status"], expected["status"])
                self.assertTrue(set(expected["required_findings"]).issubset({f["code"] for f in case["findings"]}))
                self.assertIsNone(case["payable_minor"])
                if case["status"] == "needs_review":
                    self.assertEqual(self.approve(path, 1).status_code, 409)
                for source in case["sources"]:
                    self.assertEqual(self.client.get(source["url"]).status_code, 200)

    def test_corrected_bundle_is_atomic_and_old_sources_remain_available(self):
        path, case = self.new("duplicate_line")
        self.assertTrue(case["sample_bill_available"])
        original = next(s for s in case["sources"] if s["role"] == "bill")
        orig_bytes = self.client.get(original["url"]).content
        sample = self.client.get(path + "/sample-bill")
        self.assertEqual(sample.status_code, 200)
        self.assertNotEqual(orig_bytes, sample.content)

        def correct():
            return self.client.post(
                path + "/documents", headers=match(1), data={"sample_bill": "true", "confirmed": "true"}
            )

        with ThreadPoolExecutor(2) as pool:
            responses = [f.result(timeout=15) for f in [pool.submit(correct), pool.submit(correct)]]
        self.assertEqual(sorted(r.status_code for r in responses), [200, 412])
        current = self.client.get(path).json()
        self.assertEqual((current["status"], current["revision"]), ("ready_for_review", 2))
        self.assertEqual(self.client.get(original["url"]).content, orig_bytes)
        self.assertEqual(self.client.get(path + "?revision=1").json()["status"], "needs_review")
        self.assertEqual(self.approve(path, 1).status_code, 412)
        self.assertEqual(self.client.get(path + "/export?revision=2").status_code, 409)
        self.assertEqual(self.approve(path, 2).status_code, 200)
        packet = self.client.get(path + "/export?revision=2")
        self.assertEqual(packet.status_code, 200, packet.text[:200])
        files = PdfReader(BytesIO(packet.content)).attachments
        self.assertEqual(len(files), 4)
        self.assertCountEqual(
            [contents[0] for contents in files.values()],
            [self.client.get(s["url"]).content for s in current["sources"]],
        )

    def test_new_claim_missing_sources_can_be_corrected_as_one_revision(self):
        meta, raw, names = load_discharge_fixture()
        data = {k: v for k, v in meta.items() if k != "id"} | {"confirmed": "true"}
        response = self.client.post(
            ROOT, data=data, files={"letter": (names["letter"], raw["letter"], "application/pdf")}
        )
        self.assertEqual(response.status_code, 201, response.text)
        path = ROOT + "/" + response.json()["id"]
        self.assertEqual(response.json()["status"], "needs_review")
        remaining = {
            role: (names[role], file, "application/pdf") for role, file in raw.items() if role != "letter"
        }
        replacement = self.client.post(
            path + "/documents", headers=match(1), data={"confirmed": "true"}, files=remaining
        )
        self.assertEqual(replacement.status_code, 200, replacement.text)
        self.assertEqual(replacement.json()["status"], "ready_for_review")
        self.assertEqual(replacement.json()["revision"], 2)
        self.assertEqual(
            self.client.post(
                ROOT, data=data | {"prior_case_id": "missing"}, files={"letter": (names["letter"], raw["letter"])}
            ).status_code,
            422,
        )

    def test_submission_queries_and_payer_confirmation_are_separate_from_cash(self):
        path, case = self.new("aligned")
        self.assertEqual(self.approve(path, 1).status_code, 200)
        amount = {"amount": "2000.50", "currency": "THB"}
        reference = {"reference": "PORTAL-EXAMPLE"}
        reply = reference | amount | {"outcome": "partial", "terms": "Partial confirmation.", "confirmed": "true"}
        letter = pdf(["Synthetic partial payment confirmation of THB 2,000.50."])
        self.assertEqual(self.event(path, 1, 0, "reply", reply, letter).status_code, 409)
        self.assertEqual(
            self.event(path, 1, 0, "submission", reference | {"channel": "Payer portal"}).json()["insurer_status"],
            "submitted",
        )
        self.assertEqual(self.event(path, 1, 1, "reply", reply).status_code, 422)
        query = self.event(
            path, 1, 1, "reply", reply | {"outcome": "query", "terms": "Send exhibit."}, letter
        ).json()
        self.assertEqual(query["insurer_status"], "query")
        partial = self.event(path, 1, 2, "reply", reply, letter).json()
        self.assertEqual(partial["payer_decision"]["amount_minor"], 200050)
        self.assertEqual(partial["settlement_status"], "unpaid")
        self.assertIsNone(partial["payable_minor"])
        self.assertEqual(self.client.get(partial["events"][-1]["source_url"]).content, letter)
        receipt = {"amount": "2000.00", "currency": "THB", "reference": "WIRE-1", "notes": "Verified remittance."}
        self.assertEqual(self.event(path, 1, 3, "payment", receipt | {"currency": "USD"}).status_code, 422)
        paid = self.event(path, 1, 3, "payment", receipt).json()
        self.assertEqual(paid["paid_by_currency"], {"THB": 200000})
        self.assertEqual(paid["settlement_status"], "partially_paid")
        self.assertEqual(self.event(path, 1, 4, "payment", receipt).status_code, 409)
        final = self.event(path, 1, 4, "payment", receipt | {"reference": "WIRE-2", "amount": "0.50"}).json()
        self.assertEqual(final["insurer_status"], "partial")
        self.assertEqual(final["settlement_status"], "paid")
        confirmed = self.event(path, 1, 5, "reply", reply | {"outcome": "confirmed"}, letter).json()
        self.assertEqual(confirmed["insurer_status"], "confirmed")
        denied = self.event(
            path, 1, 6, "reply", reply | {"outcome": "declined", "terms": "Decision superseded."}, letter
        ).json()
        self.assertEqual(denied["settlement_status"], "reconciliation_required")
        self.assertEqual(denied["paid_by_currency"], {"THB": 200050})
        archived = denied["events"][0]
        sent_pdf = self.client.get(archived["source_url"]).content
        self.assertEqual(len(PdfReader(BytesIO(sent_pdf)).attachments), 4)
        _, replacement, names = load_discharge_fixture("duplicate_line")
        newer = self.client.post(
            path + "/documents",
            headers=match(1),
            data={"confirmed": "true"},
            files={"bill": (names["bill"], replacement["bill"])},
        )
        self.assertEqual(newer.status_code, 200, newer.text)
        self.assertEqual(newer.json()["insurer_status"], "not_sent")
        self.assertEqual(newer.json()["case_paid_by_currency"], {"THB": 200050})
        self.assertEqual(newer.json()["paid_by_currency"], {})
        self.assertEqual(self.client.get(archived["source_url"]).content, sent_pdf)
        self.assertEqual(self.client.get(path + "/export?revision=1").status_code, 412)

    def test_intake_retry_key_is_scoped_to_the_original_discharge_manifest(self):
        meta, raw, names = load_discharge_fixture()
        data = {k: v for k, v in meta.items() if k != "id"} | {"confirmed": "true"}
        files = {role: (names[role], pdf_bytes, "application/pdf") for role, pdf_bytes in raw.items()}
        header = {"Idempotency-Key": "discharge-retry"}

        def intake():
            return self.client.post(ROOT, data=data, files=files, headers=header)

        with ThreadPoolExecutor(2) as pool:
            results = [future.result(timeout=20) for future in [pool.submit(intake), pool.submit(intake)]]
        self.assertEqual([r.status_code for r in results], [201, 201])
        self.assertEqual(results[0].json()["id"], results[1].json()["id"])
        del files["records"]
        self.assertEqual(intake().status_code, 409)

    def test_provider_outage_and_project_errors_remain_distinct_from_document_findings(self):
        request = httpx.Request("POST", "https://example.invalid/v1/responses")
        denied = AuthenticationError("denied", response=httpx.Response(401, request=request), body={})
        rate = RateLimitError("limit", response=httpx.Response(429, request=request), body={})
        quota = RateLimitError(
            "quota", response=httpx.Response(429, request=request), body={"code": "insufficient_quota"}
        )
        for exc, status, phrase in (
            (denied, 503, "authenticate"),
            (rate, 429, "rate limited"),
            (quota, 503, "quota"),
            (APIConnectionError(request=request), 503, "temporarily unavailable"),
        ):
            with self.subTest(phrase=phrase):
                response = ocr_service_error(exc)
                self.assertEqual(response.status_code, status)
                self.assertIn(phrase, response.detail)
