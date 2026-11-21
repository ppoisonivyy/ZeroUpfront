"""Exercise the independent discharge and payment workflows through their public API."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from contextlib import ExitStack
from io import BytesIO
import json
import hashlib
import os
import secrets
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader
from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
import httpx
from openai import AuthenticationError, APIConnectionError, RateLimitError

from app.discharge_claim import load_discharge_fixture
from app.journey_examples import pdf
from app.workspace_api import app
from app.staff_access import provision
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

    def test_worklist_pagination_search_counts_and_current_revision(self):
        def worklist(**params):
            response = (self.client.post(ROOT + "/worklist/search", json=params) if "search" in params
                        else self.client.get(ROOT + "/worklist", params=params))
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        prior = worklist()["counts"]
        held, _ = self.new("duplicate_line")
        ready, _ = self.new("aligned")
        reviewed, _ = self.new("aligned")
        self.assertEqual(self.approve(reviewed, 1).status_code, 200)
        self.event(reviewed, 1, 0, "submission", {"reference": "W-1", "channel": "Portal"}).raise_for_status()
        self.event(reviewed, 1, 1, "reply", {"reference": "Q-1", "terms": "More evidence required.",
                   "outcome": "query", "confirmed": "true"}, pdf(["Synthetic query."])).raise_for_status()
        counts = worklist()["counts"]
        self.assertEqual(counts, {k: prior[k] + v for k, v in {"all": 3, "needs": 1, "ready": 1, "payer": 1}.items()})
        for path, queue in [(held, "needs"), (ready, "ready"), (reviewed, "payer")]:
            ident = path.split("/")[-1]
            item = worklist(queue=queue, search="  " + ident.lower() + "  ")
            self.assertEqual((item["total"], [r["id"] for r in item["items"]], item["counts"]), (1, [ident], counts))

        legacy = self.client.get(ROOT).json()
        def priority(row):
            if row["status"] == "needs_review" or row["insurer_status"] == "query":
                return 0
            return 1 if row["status"] in ("ready_for_review", "ready_for_staff_review") else 2

        expected = sorted(legacy, key=lambda r: (priority(r), r["discharge_date"], r["id"]))
        for page in range(1, len(expected) // 3 + 3):
            result = worklist(page=page, page_size=3)
            self.assertEqual((result["page"], result["page_size"], result["total"]), (page, 3, len(expected)))
            self.assertEqual(result["items"], expected[(page - 1) * 3:page * 3])

        self.client.post(held + "/documents", headers=match(1),
                         data={"sample_bill": "true", "confirmed": "true"}).raise_for_status()
        ident = held.split("/")[-1]
        self.assertEqual(worklist(queue="needs", search=ident)["total"], 0)
        corrected = worklist(queue="ready", search=ident)
        self.assertEqual(corrected["items"][0]["revision"], 2)
        self.assertEqual(corrected["counts"]["needs"], counts["needs"] - 1)
        self.assertEqual(corrected["counts"]["ready"], counts["ready"] + 1)

    def test_worklist_distinguishes_matching_pattaya_cases_with_existing_receipts(self):
        import psycopg
        from app import discharge_store as store

        cases = [self.new("pattaya_fx")[1] for _ in range(3)]
        # Recreate receipts saved by the original rehearsal, before advice files existed.
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            for case, receipts in zip(cases, [[], [23_870_000], [23_870_000, 30_000]]):
                for version, amount in enumerate(receipts, start=case["workflow_version"]):
                    event = {"reference": f"old-{version}", "amount_minor": amount, "currency": "THB"}
                    store.append_event(db, dict(case, workflow_version=version), "payment", event, "Fixture finance")
        result = self.client.post(ROOT + "/worklist/search", json={"search": cases[0]["encounter"], "page_size": 100})
        self.assertEqual(result.status_code, 200, result.text)
        rows = {item["id"]: item for item in result.json()["items"]}
        self.assertEqual([rows[case["id"]]["pattaya_settlement"] for case in cases], [
            {"status": "unpaid", "outstanding_minor": 23_900_000},
            {"status": "partially_paid", "outstanding_minor": 30_000},
            {"status": "paid", "outstanding_minor": 0},
        ])
        _, ordinary = self.new("aligned")
        item = self.client.post(ROOT + "/worklist/search", json={"search": ordinary["id"]}).json()["items"][0]
        self.assertNotIn("pattaya_settlement", item)

    def test_worklist_literal_substrings_thai_search_and_limits(self):
        meta, raw, names = load_discharge_fixture("aligned")
        fields = dict(meta, confirmed="true", member="สมาชิก_Q77", encounter="บิล%77",
                      procedure="หัตถการใหม่", insurer="กองทุนไทย")
        case = self.client.post(ROOT, data=fields, files={"bill": (names["bill"], raw["bill"], "application/pdf")})
        case.raise_for_status()
        endpoint = ROOT + "/worklist"
        for term in ("ชิก_q7", "บิล%7", "ถการให", "ทุนไท"):
            data = self.client.post(endpoint + "/search", json={"search": term}).json()
            self.assertEqual([row["id"] for row in data["items"]], [case.json()["id"]])
        for term in ("ชิก%77", "บิล_77", "Wrist%fixation"):
            self.assertEqual(self.client.post(endpoint + "/search", json={"search": term}).json()["total"], 0)
        for invalid in ({"page": 0}, {"page_size": 0}, {"page_size": 101}, {"queue": "missing"}):
            self.assertEqual(self.client.get(endpoint, params=invalid).status_code, 422)

        self.assertEqual(self.client.post(endpoint + "/search", json={"search": "a" * 251}).status_code, 422)
        self.assertEqual(self.client.get(endpoint, params={"search": "fictional-member"}).status_code, 422)

    def test_worklists_preserve_large_integer_minor_units_from_stored_revisions(self):
        import psycopg

        _, case = self.new("aligned")
        amount = 10**30 + 7
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            db.execute("""UPDATE zeroupfront_demo.discharge_revisions
                          SET evidence=jsonb_set(evidence, '{bill_total_minor}', to_jsonb(%s::numeric))
                          WHERE case_id=%s AND revision=1""", (str(amount), case["id"]))
        legacy = next(row for row in self.client.get(ROOT).json() if row["id"] == case["id"])
        result = self.client.post(ROOT + "/worklist/search", json={"search": case["id"]}).json()
        for row in (legacy, result["items"][0]):
            self.assertIs(type(row["bill_total_minor"]), int)
            self.assertEqual(row["bill_total_minor"], amount)

    def test_unrecognized_or_repeated_pdfs_never_disappear_from_intake_or_replacement(self):
        meta, raw, names = load_discharge_fixture("aligned")
        supplied = [(k, (names[k], v, "application/pdf")) for k, v in raw.items()]
        form = dict(meta, confirmed="true")
        before = len(self.client.get(ROOT).json())
        for extra in [("unsigned_mandate", supplied[0][1]), supplied[0]]:
            resp = self.client.post(ROOT, data=form, files=[*supplied, extra])
            self.assertEqual(resp.status_code, 422, resp.text)
        self.assertEqual(len(self.client.get(ROOT).json()), before)
        path, original = self.new("aligned")
        for extra in [("unsigned_mandate", supplied[0][1]), supplied[0]]:
            resp = self.client.post(path + "/documents", data={"confirmed": "true"}, headers=match(1),
                                    files=[supplied[0], extra])
            self.assertEqual(resp.status_code, 422, resp.text)
        self.assertEqual(self.client.get(path).json()["revision"], original["revision"])

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

    def test_recheck_reuses_cached_transcripts_and_requires_current_held_revision(self):
        path, case, _, _, _ = self.scanned()
        originals = {s["role"]: self.client.get(s["url"]).content for s in case["sources"]}
        prior_pages = self.client.get(path + "/revisions/1/ocr-review").json()["pages"]
        self.assertEqual(self.client.post(path + "/recheck").status_code, 428)
        with (
            patch("app.discharge_api.OpenAI", side_effect=AssertionError("new OCR client")),
            patch("app.intake_documents.ocr_page", side_effect=AssertionError("new transcription")),
        ):
            replay = self.client.post(path + "/recheck", headers=match(1))
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), case)
        self.assertEqual(self.client.get(path + "/revisions/1/ocr-review").json()["pages"], prior_pages)
        self.assertEqual(originals, {s["role"]: self.client.get(s["url"]).content for s in replay.json()["sources"]})
        self.assertEqual(self.client.post(path + "/recheck", headers=match(1),
                                         files={"bill": ("extra.pdf", originals["bill"])}).status_code, 422)
        ready, _ = self.new("aligned")
        self.assertEqual(self.client.post(ready + "/recheck", headers=match(1)).status_code, 409)
        self.assertEqual(self.approve(ready, 1).status_code, 200)
        self.assertEqual(self.client.post(ready + "/recheck", headers=match(1)).status_code, 409)
        self.assertEqual(self.client.get(ready).json()["revision"], 1)

    def test_recheck_of_legacy_facts_publishes_one_revision_and_keeps_the_prior_report(self):
        from app.discharge_api import _evaluate

        def legacy_reader(*args, **kwargs):
            evidence = _evaluate(*args, **kwargs)
            evidence["checks"] = []
            return evidence

        # This stored reader version had the same findings but did not publish checked facts.
        with patch("app.discharge_api._evaluate", side_effect=legacy_reader):
            path, prior = self.new("member_mismatch")
        self.assertEqual(prior["checks"], [])
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: self.client.post(path + "/recheck", headers=match(1)), range(2)))
        self.assertEqual(sorted(r.status_code for r in replies), [200, 412])
        current = next(r.json() for r in replies if r.is_success)
        self.assertEqual(current["revision"], 2)
        self.assertIn("total_reconciled", {c["code"] for c in current["checks"]})
        self.assertEqual(current["findings"], prior["findings"])
        self.assertEqual(self.client.get(path + "?revision=1").json()["checks"], [])
        self.assertEqual(self.client.post(path + "/recheck", headers=match(1)).status_code, 412)
        self.assertEqual(self.client.post(path + "/recheck", headers=match(2)).json()["revision"], 2)
        for old, new in zip(prior["sources"], current["sources"], strict=True):
            self.assertEqual(old["sha256"], new["sha256"])
            self.assertEqual(self.client.get(old["url"]).content, self.client.get(new["url"]).content)

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

    def test_follow_up_is_bound_to_written_decision_and_uploaded_revision(self):
        path, _ = self.new("aligned")
        self.approve(path, 1).raise_for_status()
        self.event(path, 1, 0, "submission", {"reference": "S-1", "channel": "Portal"}).raise_for_status()
        written = {"confirmed": "true", "terms": "Please review the attached terms.", "reference": "Q-1",
                   "owner": "Evening coordinator", "follow_up_date": "2026-11-26"}
        attachment = pdf(["Synthetic outbound packet, page 1."])
        outgoing = {"confirmed": "true", "reference": "OUT-1", "channel": "Payer portal",
                    "owner": "Weekend desk", "follow_up_date": "2026-11-27"}
        self.assertEqual(self.event(path, 1, 1, "supplement", outgoing, attachment).status_code, 409)
        query = self.event(path, 1, 1, "reply", written | {"outcome": "query"}, pdf(["Query."])).json()
        self.assertEqual(query["payer_decision"]["owner"], written["owner"])
        self.assertEqual(self.event(path, 1, 2, "supplement", outgoing).status_code, 422)
        self.assertEqual(self.event(path, 1, 2, "supplement", outgoing | {"follow_up_date": "2026-02-31"}, attachment).status_code, 422)
        sent = self.event(path, 1, 2, "supplement", outgoing, attachment).json()
        recorded = sent["events"][-1]
        self.assertEqual(sent["insurer_status"], "supplement_sent")
        listing = self.client.post(ROOT + "/worklist/search", json={"search": sent["id"]}).json()["items"]
        self.assertEqual(listing[0]["insurer_status"], "supplement_sent")
        self.assertEqual((recorded["data"]["payer_event_id"], recorded["data"]["source_revision"]),
                         (query["events"][-1]["id"], 1))
        self.assertEqual(recorded["data"]["owner"], "Weekend desk")
        self.assertEqual(self.client.get(recorded["source_url"]).content, attachment)
        self.assertEqual(self.event(path, 1, 2, "supplement", outgoing, attachment).status_code, 409)
        self.assertEqual(self.event(path, 1, 3, "supplement", outgoing, attachment).status_code, 409)
        partial = self.event(path, 1, 3, "reply", written | {"outcome": "partial", "amount": "1200", "currency": "THB"},
                             pdf(["Partial approval."])).json()
        self.assertIn("supplement", partial["allowed_actions"])
        appeal = self.event(path, 1, 4, "supplement", outgoing | {"reference": "OUT-2"}, attachment).json()
        self.assertEqual(appeal["events"][-1]["data"]["response_kind"], "Appeal")
        self.assertEqual(appeal["insurer_status"], "appeal_sent")
        self.assertEqual(appeal["payer_decision"]["amount_minor"], 120000)
        self.assertIn("payment", appeal["allowed_actions"])
        approved = self.event(path, 1, 5, "reply", written | {"outcome": "confirmed", "amount": "1500", "currency": "THB"},
                              pdf(["Revised approval."])).json()
        self.assertNotIn("supplement", approved["allowed_actions"])
        self.assertEqual([e["data"]["outcome"] for e in approved["events"] if e["kind"] == "reply"],
                         ["query", "partial", "confirmed"])

    def test_statement_requires_human_and_preserves_unknowns_and_reviewed_snapshot(self):
        path, case = self.new("aligned")
        confirmation = {"confirmed": "true", "contact": "Hospital billing desk", "next_update": "2026-11-27"}
        self.assertIsNone(case["patient_statement_facts"])
        self.assertEqual(self.event(path, 1, 0, "patient_statement", confirmation).status_code, 409)
        self.approve(path, 1).raise_for_status()
        self.assertEqual(self.event(path, 1, 0, "patient_statement", confirmation | {"confirmed": "false"}).status_code, 422)
        verified = self.event(path, 1, 0, "patient_statement", confirmation).json()
        original = verified["events"][-1]["data"]
        self.assertIsNone(original["approved_minor"])
        self.assertIsNone(original["patient_fx_minor"])
        self.assertEqual(verified["reviewed_patient_statement"]["reviewer"], "Hospital finance")
        self.assertFalse({"member", "encounter", "procedure", "terms", "sources"} & original.keys())
        self.assertEqual(self.event(path, 1, 0, "patient_statement", confirmation).status_code, 409)
        sent = self.event(path, 1, 1, "submission", {"reference": "S-1", "channel": "Portal"}).json()
        self.assertIsNone(sent["reviewed_patient_statement"])
        self.assertEqual(sent["events"][0]["data"], original)

    def test_pattaya_statement_preserves_insurer_shortfall_and_invalidates_after_topup(self):
        path, case = self.new("pattaya_fx")
        quotes = self.client.get(path + "/pattaya?revision=1").json()["quotes"]
        def action(kind, case, **fields):
            res = self.client.post(path + "/pattaya/actions", headers=match(1), json={"action": kind,
                                   "confirmed": True, "workflow_version": case["workflow_version"], **fields})
            self.assertEqual(res.status_code, 200, res.text)
            return res.json()
        case = action("book_spot", case, quote_id=next(q["quote_id"] for q in quotes if q["instrument"] == "spot"))
        case = action("record_short_credit", case, bank_document="initial_credit")
        response = self.event(path, 1, case["workflow_version"], "patient_statement",
                              {"confirmed": "true", "contact": "Hospital billing desk", "next_update": "2026-12-02"})
        self.assertEqual(response.status_code, 200, response.text)
        reviewed = response.json()
        facts = reviewed["reviewed_patient_statement"]
        self.assertEqual((facts["patient_fx_minor"], facts["patient_share_minor"], facts["insurer_outstanding_minor"]),
                         (0, 0, 30000))
        final = action("record_topup", reviewed, bank_document="topup_credit")
        self.assertIsNone(final["reviewed_patient_statement"])
        self.assertEqual(final["patient_statement_facts"]["insurer_outstanding_minor"], 0)
        self.assertEqual(final["events"][-2]["data"]["insurer_outstanding_minor"], 30000)

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

    def scanned(self, scenario="aligned", *, first_with_ocr=True):
        meta, raw, names = load_discharge_fixture(scenario)
        transcripts = [page.extract_text() for page in PdfReader(BytesIO(raw["summary"])).pages]
        out = BytesIO()
        writer = Canvas(out, invariant=1)
        for text in transcripts:
            image = Image.new("L", (900, 1200), "white")
            ImageDraw.Draw(image).multiline_text((15, 15), text, fill="black", spacing=6)
            writer.drawImage(ImageReader(image), 0, 0, width=575, height=790)
            writer.showPage()
        writer.save()
        raw["summary"] = out.getvalue()
        files = {role: (names[role], content, "application/pdf") for role, content in raw.items()}
        data = {k: v for k, v in meta.items() if k != "id"} | {
            "confirmed": "true",
            "ocr": str(first_with_ocr).lower(),
        }
        with (
            patch.dict(os.environ, WORKSPACE_ENABLE_OCR="1", OPENAI_API_KEY="mock-test-value"),
            patch("app.discharge_api.OpenAI"),
            patch("app.intake_documents.ocr_page", side_effect=lambda source, page, client: transcripts[page - 1]),
        ):
            response = self.client.post(ROOT, data=data, files=files)
        self.assertEqual(response.status_code, 201, response.text)
        return ROOT + "/" + response.json()["id"], response.json(), raw, names, transcripts

    def test_ocr_attestation_verifies_each_exact_original_and_creates_a_new_reviewable_revision(self):
        path, case, raw, names, transcripts = self.scanned()
        self.assertTrue(case["ocr_review_available"])
        self.assertEqual(case["ocr_page_count"], len(transcripts))
        for key in ("ocr_pages", "ocr_review_pages"):
            self.assertNotIn(key, case)
            self.assertNotIn(key, self.client.get(ROOT).json()[-1])
        source = self.client.get(path + "/revisions/1/ocr-review").json()
        self.assertTrue(source["eligible"])
        for item in source["pages"]:
            self.assertEqual(item["text"], transcripts[item["page"] - 1])
            self.assertEqual(
                hashlib.sha256(self.client.get(item["source_url"]).content).hexdigest(), item["sha256"]
            )
        keys = ("role", "page", "sha256", "transcript_sha256")
        pages = [{key: item[key] for key in keys} for item in source["pages"]]

        def verify(entries):
            return self.client.post(
                path + "/verify-ocr", headers=match(1), json={"reviewer": "OCR coordinator", "pages": entries}
            )

        for invalid in (pages[:1], pages + pages[:1], [pages[0] | {"transcript_sha256": "0" * 64}, *pages[1:]]):
            self.assertEqual(verify(invalid).status_code, 422)
        with ThreadPoolExecutor(2) as pool:
            replay = [
                future.result(timeout=15) for future in [pool.submit(verify, pages), pool.submit(verify, pages)]
            ]
        self.assertEqual(sorted(r.status_code for r in replay), [200, 412])
        current = self.client.get(path).json()
        self.assertEqual((current["revision"], current["status"]), (2, "ready_for_review"))
        self.assertEqual(current["ocr_attestation"]["source_revision"], 1)
        self.assertFalse(self.client.get(path + "/revisions/1/ocr-review").json()["eligible"])
        self.assertEqual(self.client.get(path + "?revision=1").json()["status"], "needs_review")
        self.assertEqual(self.client.get(path + "/export?revision=2").status_code, 409)
        self.assertEqual(self.approve(path, 2).status_code, 200)
        packet = self.client.get(path + "/export?revision=2")
        self.assertEqual(packet.status_code, 200, packet.text[:200])
        self.assertEqual(PdfReader(BytesIO(packet.content)).attachments[names["summary"]], [raw["summary"]])
        unchanged = self.client.post(
            path + "/documents",
            headers=match(2),
            data={"confirmed": "true"},
            files={"summary": (names["summary"], raw["summary"])},
        )
        self.assertEqual(
            (unchanged.json()["revision"], unchanged.json()["status"]), (2, "staff_reviewed"), unchanged.text
        )
        _, changed, corrected_names = load_discharge_fixture("duplicate_line")
        amended = self.client.post(
            path + "/documents",
            headers=match(2),
            data={"confirmed": "true"},
            files={"bill": (corrected_names["bill"], changed["bill"])},
        )
        self.assertEqual((amended.json()["revision"], amended.json()["status"]), (3, "needs_review"))
        self.assertIsNone(amended.json()["ocr_attestation"])
        self.assertFalse(amended.json()["ocr_review_available"])
        barred = self.client.post(
            path + "/verify-ocr", headers=match(3), json={"reviewer": "Reviewer", "pages": pages}
        )
        self.assertEqual(barred.status_code, 409)
        self.assertEqual(self.client.get(path + "/export?revision=2").status_code, 412)
        _, blank, blank_names = load_discharge_fixture("unreadable_summary")
        invalidated = self.client.post(
            path + "/documents",
            headers=match(3),
            data={"confirmed": "true"},
            files={"summary": (blank_names["summary"], blank["summary"])},
        )
        self.assertEqual(invalidated.json()["ocr_page_count"], 0)
        self.assertIn("unreadable_summary", {f["code"] for f in invalidated.json()["findings"]})
        self.assertEqual(self.client.get(path + "/revisions/4/ocr-review").json()["pages"], [])

    def test_staff_transcripts_require_session_and_attestation_binds_real_actor(self):
        path, *_ = self.scanned()
        with patch.dict(os.environ, WORKSPACE_AUTH_MODE="staff", WORKSPACE_COOKIE_SECURE="0"):
            self.client.cookies.clear()
            self.addCleanup(self.client.cookies.clear)
            url = path + "/revisions/1/ocr-review"
            self.assertEqual(self.client.get(url).status_code, 401)
            password = secrets.token_urlsafe(32)
            provision(app.state.dsn, "ocr-quality", "OCR reviewer", password)
            credentials = {"username": "ocr-quality", "password": password}
            self.assertEqual(self.client.post("/api/access/login", json=credentials).status_code, 200)
            shown = self.client.get(url)
            self.assertEqual(shown.status_code, 200, shown.text)
            entries = [
                {k: p[k] for k in ("role", "page", "transcript_sha256", "sha256")} for p in shown.json()["pages"]
            ]
            verified = self.client.post(
                path + "/verify-ocr", headers=match(1), json={"reviewer": "Other name", "pages": entries}
            )
            self.assertEqual(verified.status_code, 200, verified.text)
            self.assertEqual(verified.json()["ocr_attestation"]["username"], "ocr-quality")
            self.assertEqual(verified.json()["ocr_attestation"]["reviewer"], "OCR reviewer")
            meta, raw, names = load_discharge_fixture()
            future = (date.today() + timedelta(days=1)).isoformat()
            invalid = self.client.post(
                ROOT,
                data=meta | {"confirmed": "true", "as_of": future},
                files={role: (names[role], data) for role, data in raw.items()},
            )
            self.assertEqual(invalid.status_code, 422)
            self.assertIn("future", invalid.json()["detail"])

    def test_later_review_date_changes_material_finding_and_preserves_old_result(self):
        meta, raw, names = load_discharge_fixture()
        earlier = (date.fromisoformat(meta["discharge_date"]) - timedelta(days=1)).isoformat()
        files = {k: (names[k], data) for k, data in raw.items()}
        initial = self.client.post(ROOT, data=meta | {"as_of": earlier, "confirmed": "true"}, files=files)
        self.assertEqual(initial.status_code, 201, initial.text)
        self.assertIn("discharge_in_future", {f["code"] for f in initial.json()["findings"]})
        path = ROOT + "/" + initial.json()["id"]
        later = self.client.post(
            path + "/documents",
            headers=match(1),
            data={"confirmed": "true", "as_of": meta["discharge_date"]},
            files={"bill": files["bill"]},
        )
        self.assertEqual(later.status_code, 200, later.text)
        self.assertEqual((later.json()["revision"], later.json()["status"]), (2, "ready_for_review"))
        self.assertEqual(self.client.get(path + "?revision=1").json()["status"], "needs_review")
