"""No network requests: exercise opt-in, immutable evidence, and advisory validation."""

import base64
import json
import os
import shutil
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import payer_ai_reader as reader
from app.journey_examples import pdf
from app.workspace_api import app
from bench.case_revision import temporary_database


def cite(role, page=1):
    return {"role": role, "page": page}


def observation(field, state, *pages):
    return {
        "field": field,
        "state": state,
        "observation": "Administrative field on original.",
        "pages": list(pages),
    }


def aia():
    return [
        observation("admission", "match", cite("records", 2)),
        observation("expense", "match", cite("records"), cite("bill")),
        observation("consent", "visual_review", cite("records")),
        observation("certification", "unknown"),
        observation("letter", "present", cite("letter")),
    ]


class AIReadValidation(unittest.TestCase):
    def test_omissions_unknown_and_wrong_role_state_or_page(self):
        counts = {"bill": 2, "summary": 2, "records": 2}
        fields = aia()[:-1] + [observation("letter", "absent")]
        self.assertEqual(len(reader.validated_checks(reader.Review(checks=fields), "aia", counts)), 5)
        cited_others = fields[:-1] + [observation("letter", "absent", cite("summary", 1))]
        omitted = reader.validated_checks(reader.Review(checks=cited_others), "aia", counts)[-1]
        self.assertEqual(omitted.pages, [])
        self.assertIn("payer-letter role", omitted.observation)
        invalid = [
            fields[:-1],
            fields[:-1] + [fields[0]],
            fields[:-1] + [observation("letter", "confirmed")],
            fields[:-1] + [observation("letter", "present", cite("letter", 1))],
            [observation("admission", "conflict", cite("records", 3)), *fields[1:]],
            [observation("admission", "match"), *fields[1:]],
            [fields[0], observation("expense", "match", cite("records")), *fields[2:]],
            [
                fields[0],
                observation("expense", "match", cite("records"), cite("records")),
                *fields[2:],
            ],
        ]
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(reader.InvalidReview):
                reader.validated_checks(reader.Review(checks=rows), "aia", counts)

    def test_form_only_conflict_becomes_unknown_without_losing_other_fields(self):
        # The observed failure was an accurate FL60 ID plus the reference ID in the
        # narrative, but only a citation to the form.
        rows = [
            observation("member", "conflict", cite("bill")),
            observation("disposition", "unknown"),
            observation("replacement", "original", cite("bill")),
            observation("expense", "unknown"),
        ]
        account = pdf(["Final itemized hospital invoice", "Member: MBI-728"])
        originals = {"summary": account}
        case = {
            "member": "MBI-728",
            "sources": [{"role": "summary", "sha256": reader.sha256(account).hexdigest()}],
        }
        lookup = reader._reference_on_page(case, originals)

        def check():
            return reader.validated_checks(
                reader.Review(checks=rows), "cms", {"bill": 2, "summary": 1}, lookup
            )

        verdict = check()
        self.assertEqual([c.state for c in verdict], ["unknown", "unknown", "original", "unknown"])
        self.assertIn("separate hospital page", verdict[0].observation)
        rows[0]["pages"].append(cite("summary"))
        self.assertEqual(check()[0].state, "conflict")
        case["member"] = "MBI-7280"
        self.assertEqual(check()[0].state, "unknown")

    def test_verified_pages_repair_form_only_response_without_repeating_model_values(
        self,
    ):
        rows = [
            observation("member", "conflict", cite("bill")),
            observation("disposition", "unknown"),
            observation("replacement", "original", cite("bill")),
            observation("expense", "unknown"),
        ]
        rows[0]["observation"] = "Wrong digit in AI transcript: MBI-739."
        sources = [
            dict(cite("bill"), quote="MBI-738"),
            dict(cite("bill", 3), quote="Member MBI-728"),
        ]
        fact = {
            "message": "The form shows MBI-738. The invoice shows MBI-728.",
            "sources": sources,
        }
        counts = {"bill": 3}

        def check():
            return reader.validated_checks(
                reader.Review(checks=rows),
                "cms",
                counts,
                field_evidence={"cms_member_mismatch": fact},
            )[0]

        repaired = check()
        self.assertEqual(repaired.state, "conflict")
        self.assertEqual([(c.role, c.page) for c in repaired.pages], [("bill", 1), ("bill", 3)])
        self.assertNotIn("MBI-739", repaired.observation)
        self.assertIn("MBI-728", repaired.observation)
        rows[0]["state"] = "match"
        self.assertEqual(check().state, "unknown")
        rows[0]["state"] = "conflict"
        fact["sources"] = sources[:1]
        self.assertEqual(check().state, "unknown")

    def test_corroboration_for_aia_encounter_and_third_party_fep_assignment(self):
        fields = aia()
        fields[0] = observation("admission", "conflict", cite("records", 2))
        checks = reader.validated_checks(
            reader.Review(checks=fields), "aia", {"records": 2, "bill": 1, "letter": 1}
        )
        self.assertEqual((checks[0].state, checks[1].state), ("unknown", "match"))
        fields = [
            observation("payee", "other_provider", cite("records")),
            observation("expense", "unknown"),
        ]
        checks = reader.validated_checks(reader.Review(checks=fields), "fep", {"records": 2})
        self.assertEqual(checks[0].state, "unknown")

    def test_well_cited_advice_still_has_to_agree_with_the_observed_fields(self):
        cms = [
            observation("member", "absent", cite("bill")),
            observation("disposition", "unknown"),
            observation("replacement", "original", cite("bill")),
            observation("expense", "match", cite("bill"), cite("bill", 3)),
        ]
        fields = reader.validated_checks(
            reader.Review(checks=cms),
            "cms",
            {"bill": 3},
            field_evidence={
                "cms_member_mismatch": {},
                "cms_initial_claim_type": {},
                "cms_total_mismatch": {},
            },
        )
        self.assertEqual([f.state for f in fields], ["unknown", "unknown", "original", "unknown"])
        self.assertIn("conflicts", fields[0].observation)

        fep = [observation("payee", "member", cite("records")), observation("expense", "unknown")]
        for verified, expected in [
            ("fep_provider_assignment", "unknown"),
            ("fep_member_reimbursement", "member"),
            ("fep_assignment_provider", "unknown"),
        ]:
            with self.subTest(verified=verified):
                fields = reader.validated_checks(
                    reader.Review(checks=fep), "fep", {"records": 1}, field_evidence={verified: {}}
                )
                self.assertEqual(fields[0].state, expected)

    def test_independent_document_cannot_establish_a_route_when_elections_conflict(self):
        fields = [observation("payee", "hospital", cite("records")), observation("expense", "unknown")]
        review = reader.Review(checks=fields)
        facts = {"fep_payee_review": {"message": "Confirm the mutually exclusive elections on section 5."}}
        payee, _ = reader.validated_checks(review, "fep", {"records": 2}, field_evidence=facts)
        self.assertEqual(payee.state, "unknown")
        self.assertIn("elections", payee.observation)

    def test_cms_total_has_two_independent_source_pages(self):
        fields = [
            observation("member", "absent", cite("bill")),
            observation("disposition", "unknown"),
            observation("replacement", "unknown"),
            observation("expense", "match", cite("bill"), cite("letter")),
        ]
        with self.assertRaises(reader.InvalidReview):
            reader.validated_checks(reader.Review(checks=fields), "cms", {"bill": 2, "letter": 1})


@unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires disposable PostgreSQL")
class AIReadApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resources = ExitStack()
        cls.addClassCleanup(resources.close)
        dsn = resources.enter_context(temporary_database())
        resources.enter_context(
            patch.dict(
                os.environ,
                DATABASE_URL=dsn,
                WORKSPACE_AUTH_MODE="local",
                WORKSPACE_ENABLE_AI_REVIEW="1",
                OPENAI_API_KEY="mock-only",
            )
        )
        cls.client = resources.enter_context(TestClient(app))

    def setUp(self):
        created = self.client.post("/api/discharge/examples/duplicate_line")
        self.assertEqual(created.status_code, 201)
        self.case = created.json()
        self.path = "/api/discharge/" + self.case["id"]
        self.provider = self.enterContext(patch("app.payer_ai_reader.OpenAI"))
        self.parse = self.provider.return_value.__enter__.return_value.responses.parse
        self.parse.return_value = SimpleNamespace(
            status="completed",
            model="test-model-snapshot",
            output_parsed=reader.Review(checks=aia()),
        )

    def post(self, *, family="aia", confirmed=True, revision=1):
        headers = {} if revision is None else {"If-Match": f'"{revision}"'}
        return self.client.post(
            self.path + "/second-read",
            json={"family": family, "confirmed": confirmed},
            headers=headers,
        )

    def test_opt_in_and_budgets_precede_every_model_call(self):
        for setting in [{"WORKSPACE_ENABLE_AI_REVIEW": "0"}, {"OPENAI_API_KEY": ""}]:
            with patch.dict(os.environ, setting):
                self.assertFalse(self.client.get(self.path).json()["ai_review_enabled"])
                self.assertEqual(self.post().status_code, 503)
        self.assertTrue(self.client.get(self.path).json()["ai_review_enabled"])
        self.assertNotIn("ai_review_enabled", self.client.get("/api/discharge").json()[0])
        for value in [False, "true"]:
            self.assertEqual(self.post(confirmed=value).status_code, 422)
        self.assertEqual(self.post(family="other").status_code, 422)
        self.assertEqual(self.post(revision=None).status_code, 428)
        self.assertEqual(self.post(revision=33).status_code, 412)
        with patch.object(reader, "MAX_TOTAL_PAGES", 1):
            self.assertEqual(self.post().status_code, 422)
        with patch.object(reader, "MAX_TOTAL_BYTES", 2):
            self.assertEqual(self.post().status_code, 422)
        with self.assertRaises(reader.UnsupportedPacket):
            reader.second_read(dict(self.case, checks=[{"code": "cms_member_mismatch"}]), {}, "aia")
        self.provider.assert_not_called()

    def test_returns_provisional_observations_only_for_the_requested_revision(self):
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("no-store", response.headers["Cache-Control"])
        body = response.json()
        self.assertEqual(set(body), {"revision", "family", "model", "checks"})
        self.assertEqual(body["revision"], 1)
        self.assertEqual(body["checks"][0]["state"], "unknown")
        self.assertEqual(body["checks"][1:], aia()[1:])
        self.assertEqual(body["model"], "test-model-snapshot")
        options = self.parse.call_args.kwargs
        self.assertIs(options["store"], False)
        self.assertNotIn("tools", options)
        content = options["input"][0]["content"]
        manifest = json.loads(content[0]["text"])
        self.assertEqual(manifest["checks"], reader.STAFF_RUBRICS["aia"])
        self.assertEqual(set(manifest["encounter"]), set(reader.ENCOUNTER_FIELDS))
        originals = {src["role"]: self.client.get(src["url"]).content for src in self.case["sources"]}
        for part, role in zip(content[1:], reader.ROLES, strict=True):
            self.assertEqual(part["filename"], role + ".pdf")
            self.assertEqual(base64.b64decode(part["file_data"].split(",")[1]), originals[role])
        self.assertEqual(self.client.get(self.path).json(), self.case)
        self.assertEqual(self.client.get(self.path + "/export?revision=1").status_code, 409)

    def test_incomplete_or_unverifiable_output_never_returns_a_partial_review(self):
        for reply in [
            SimpleNamespace(status="incomplete", output_parsed=reader.Review(checks=aia())),
            SimpleNamespace(status="completed", output_parsed=reader.Review(checks=aia()[:-1])),
            SimpleNamespace(status="completed", output_parsed=None),
        ]:
            self.parse.return_value = reply
            self.assertEqual(self.post().status_code, 502)
        self.assertEqual(self.client.get(self.path).json(), self.case)

    def test_changed_revision_discards_returned_observations(self):
        def replacement(**_):
            changed = self.client.post(
                self.path + "/documents",
                headers={"If-Match": '"1"'},
                data={"sample_bill": "true", "confirmed": "true"},
            )
            self.assertEqual(changed.json()["revision"], 2)
            return SimpleNamespace(status="completed", output_parsed=reader.Review(checks=aia()))

        self.parse.side_effect = replacement
        response = self.post()
        self.assertEqual(response.status_code, 412)
        self.assertNotIn("checks", response.json())
        current = self.client.get(self.path).json()
        self.assertEqual(current["events"], [])
        self.assertNotIn("second_read", current)
