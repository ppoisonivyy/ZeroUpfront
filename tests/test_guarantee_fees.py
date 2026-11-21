from contextlib import ExitStack
import os
import shutil
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import guarantee_fees as fees
from app.workspace_api import app
from bench.case_revision import temporary_database


def item(category, page, quote, payer="insurer"):
    return fees.Clause(category=category, state="explicit", payer=payer, page=page, quote=quote)


class CitationTests(unittest.TestCase):
    def test_checks_each_physical_page_in_its_original_language(self):
        fee = "ผู้ป่วยรับผิดชอบค่าธรรมเนียมธนาคาร"
        difference = "The insurer covers exchange-rate differences."
        reading = fees.Reading(clauses=[item("bank_fees", 2, fee, "patient"), item("exchange_difference", 1, difference)])
        result = fees.verify(reading, [difference, fee])
        self.assertEqual(result["status"], "cited")
        self.assertEqual(result["findings"][0]["page"], 2)
        for invalid in (item("bank_fees", 1, fee, "patient"), item("bank_fees", 2, "Bank fees payable by insurer."),
                        item("bank_fees", 2, fee, "unclear")):
            changed = fees.verify(fees.Reading(clauses=[invalid, reading.clauses[1]]), [difference, fee])
            self.assertEqual(changed["status"], "needs_review")
            self.assertEqual(len(changed["findings"]), 1)

    def test_absence_conflict_and_nonspecific_payment_text(self):
        generic = "Insurer has agreed to pay the hospital bill in full."
        for state in ("silent","conflict","ambiguous"):
            partial = fees.Clause(category="bank_fees", state=state, payer="unclear", page=None, quote="")
            result = fees.verify(fees.Reading(clauses=[partial,item("exchange_difference", 1, generic)]), [generic])
            self.assertEqual((result["status"], result["findings"]), ("needs_review",[]))


@unittest.skipUnless(shutil.which("initdb") and shutil.which("pg_ctl"), "requires PostgreSQL")
class FeeRouteTests(unittest.TestCase):
    def test_consent_event_binding_and_originals(self):
        with ExitStack() as stack:
            dsn = stack.enter_context(temporary_database())
            stack.enter_context(patch.dict(os.environ, DATABASE_URL=dsn,WORKSPACE_AUTH_MODE="local"))
            client = stack.enter_context(TestClient(app))
            claim = client.post("/api/discharge/examples/pattaya_fx").json()
            path = "/api/discharge/" + claim["id"] + "/guarantee-fees"
            event = claim["events"][-1]
            def post(confirmed=True, event_id=event["id"], revision=1):
                return client.post(path, json={"confirmed":confirmed,"event_id":event_id},headers={"If-Match":f'"{revision}"'})
            stack.enter_context(patch("app.payer_ai_reader.enabled", return_value=True))
            reader = stack.enter_context(patch("app.guarantee_fees.read", return_value=fees._review("silent")))
            self.assertEqual(post(False).status_code, 422)
            self.assertEqual(post(event_id=claim["events"][0]["id"]).status_code, 409)
            self.assertEqual(post(revision=2).status_code, 412)
            reader.assert_not_called()
            result = post()
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["source_url"], event["source_url"])
            reader.assert_called_once_with(client.get(event["source_url"]).content)
