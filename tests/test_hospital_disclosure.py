"""Exercise each mounted hospital's disclosure policy with synthetic PDFs and a fake provider."""
import json
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from openai import APIConnectionError

from app import discharge_api, guarantee_fees, workspace_api
from app.discharge_claim import evaluate_discharge, load_discharge_fixture
from app.hospital_platform import HospitalContext, OPENAI_BASE, build_platform, configured_hospitals
from app.journey_examples import exhibits, pdf


def clinical_routes(hospital):
    # Mount the production routes with a synthetic document store. Session/role isolation
    # is exercised separately by the PostgreSQL hospital-platform tests.
    app = FastAPI()
    app.state.dsn = hospital.dsn
    app.add_middleware(HospitalContext, hospital=hospital)
    app.include_router(workspace_api.router)
    app.include_router(discharge_api.router)
    return app


class HospitalDisclosureTests(unittest.TestCase):
    def setUp(self):
        north = {"hospital_name": "North", "database_url_env": "NORTH",
                 "approved_openai_uses": ["payer_second_read", "guarantee_fees", "hosted_ocr"]}
        south = {"hospital_name": "South", "database_url_env": "SOUTH"}
        registry = {"north": north, "south": south, "fees": dict(south, database_url_env="FEES", approved_openai_uses=["guarantee_fees"])}
        self.enterContext(patch.dict(os.environ, WORKSPACE_HOSPITALS=json.dumps(registry), NORTH="dbname=north",
                                     SOUTH="dbname=south", FEES="dbname=fees", OPENAI_BASE_URL=OPENAI_BASE,
                                     OPENAI_API_KEY="test-only", WORKSPACE_ENABLE_OCR="1", WORKSPACE_ENABLE_AI_REVIEW="1"))
        self.client = self.enterContext(TestClient(build_platform(clinical_routes)))
        self.meta, self.raw, names = load_discharge_fixture("duplicate_line")
        self.case = dict(self.meta, **evaluate_discharge(self.meta, self.raw, names))
        self.case.update(revision=1, events=[{"kind":"reply", "id":1, "source_url":"/original.pdf", "data":{"outcome":"confirmed"}}])
        self.enterContext(patch("app.discharge_store.snapshot", return_value=(self.case, self.raw, names)))
        self.enterContext(patch("app.discharge_store.detail", return_value=self.case))
        self.source = self.enterContext(patch("app.discharge_store.source", return_value=self.raw["letter"]))
        self.scan = pdf(["Synthetic sample"], image=True)
        self.providers = {}
        for module in ("app.workspace_api", "app.discharge_api", "app.payer_ai_reader", "app.guarantee_fees"):
            provider = self.enterContext(patch(module + ".OpenAI"))
            provider.return_value.__enter__.return_value.responses.parse.side_effect = APIConnectionError(
                request=httpx.Request("POST", OPENAI_BASE))
            self.providers[module] = provider

    def call_scans_and_readers(self, slug):
        path = f"/h/{slug}/api"
        meta, docs = exhibits()
        data = {k: v for k, v in meta.items() if k != "id"} | {"confirmed":"true", "ocr":"true"}
        docs["estimate"] = self.scan
        admission = self.client.post(path + "/cases", data=data, files={role:(role+".pdf", raw) for role,raw in docs.items()})
        fields = {k:v for k,v in self.meta.items() if k not in {"id", "as_of"}} | {"confirmed":"true", "ocr":"true"}
        discharge = self.client.post(path + "/discharge", data=fields, files={"bill":("bill.pdf", self.scan)})
        base = path + "/discharge/example"
        headers = {"If-Match": '"1"'}
        second = self.client.post(base + "/second-read", headers=headers, json={"confirmed":True, "family":"aia"})
        fees = self.client.post(base + "/guarantee-fees", headers=headers, json={"confirmed":True, "event_id":1})
        return [admission, discharge, second, fees]

    def test_staff_opt_in_and_retry_cannot_override_hospital_policy(self):
        for _ in range(2):
            for response in self.call_scans_and_readers("south"):
                self.assertEqual(response.status_code, 403, response.text)
        for provider in self.providers.values():
            provider.assert_not_called()
        # These four requests reach the fake provider. Each artificial network error
        # proves the normal request path crossed the correct hospital boundary once.
        for response in self.call_scans_and_readers("north"):
            self.assertEqual(response.status_code, 503, response.text)
        for provider in self.providers.values():
            provider.assert_called_once()
            provider.return_value.__enter__.return_value.responses.parse.assert_called_once()
            self.assertEqual(provider.call_args.kwargs["base_url"], OPENAI_BASE)
            self.assertFalse(provider.call_args.kwargs["http_client"].follow_redirects)
        for hospital in self.client.get("/api/hospitals").json()["hospitals"]:
            self.assertEqual(set(hospital), {"name", "slug"})

    def test_fee_reader_cannot_run_nested_ocr_without_ocr_approval(self):
        self.source.return_value = self.scan
        base = "/h/fees/api/discharge/example"
        result = self.client.post(base + "/guarantee-fees", headers={"If-Match": '"1"'},
                                  json={"confirmed":True, "event_id":1})
        self.assertEqual((result.status_code, result.json()["status"]), (200, "needs_review"))
        self.assertEqual(self.client.post(base + "/second-read", headers={"If-Match": '"1"'},
                         json={"confirmed":True, "family":"aia"}).status_code, 403)
        for provider in self.providers.values():
            provider.assert_not_called()

    def test_approved_fee_only_hospital_can_read_a_digital_letter(self):
        provider = self.providers["app.guarantee_fees"]
        parse = provider.return_value.__enter__.return_value.responses.parse
        parse.side_effect = None
        parse.return_value = SimpleNamespace(status="completed", output_parsed=guarantee_fees.Reading(clauses=[]))
        base = "/h/fees/api/discharge/example"
        self.assertEqual(self.client.post(base + "/guarantee-fees", headers={"If-Match": '"1"'},
                         json={"confirmed":False, "event_id":1}).status_code, 422)
        provider.assert_not_called()
        result = self.client.post(base + "/guarantee-fees", headers={"If-Match": '"1"'},
                                  json={"confirmed":True, "event_id":1})
        self.assertEqual((result.status_code, result.json()["status"]), (200, "needs_review"))
        parse.assert_called_once()
        self.assertFalse(parse.call_args.kwargs["store"])

    def test_changed_receiver_or_disabled_service_prevents_disclosure(self):
        for env, expected in [({"OPENAI_BASE_URL":"https://other.example/v1"}, 403),
                              ({"WORKSPACE_ENABLE_OCR":"0", "WORKSPACE_ENABLE_AI_REVIEW":"0"}, 503)]:
            with self.subTest(env=env), patch.dict(os.environ, env):
                for response in self.call_scans_and_readers("north"):
                    self.assertEqual(response.status_code, expected, response.text)
        for provider in self.providers.values():
            provider.assert_not_called()

    def test_legacy_demo_scan_needs_request_and_hospital_approval(self):
        raw = (workspace_api.FIXTURES / "cases/Z002/scanned-estimate.pdf").read_bytes()
        self.enterContext(patch("app.workspace_store.case_detail", return_value={"intake":False, "revision":1}))
        for slug, opt_in, expected in [("north",False,422), ("south",True,403), ("north",True,503)]:
            with self.subTest(slug=slug, opt_in=opt_in):
                result = self.client.post(f"/h/{slug}/api/cases/Z002/estimate",
                    headers={"If-Match": '"1"'}, data={"confirmed":"true","ocr":str(opt_in).lower()},
                    files={"file":("scan.pdf", raw)})
                self.assertEqual(result.status_code, expected, result.text)
        self.providers["app.workspace_api"].assert_called_once()

    def test_rejects_misspelled_uses_and_unsafe_receiver_settings(self):
        for config in [{"approved_openai_uses":"all"}, {"approved_openai_uses":["hosted-ocr"]},
                       {"approved_openai_uses":[{"hosted_ocr":True}]}, {"approved_openai_uses":["hosted_ocr"] * 2},
                       {"approved_openai_base_url":"http://example.test"}, {"approved_openai_base_url":"https://secret@example.test"}]:
            hospital = dict(hospital_name="North", database_url_env="NORTH", **config)
            with self.subTest(config=config), patch.dict(os.environ, WORKSPACE_HOSPITALS=json.dumps({"north":hospital})):
                with self.assertRaises(ValueError):
                    configured_hospitals()
