"""Offline regression checks using the preserved HTTP evidence from the frozen holdout."""
from contextlib import nullcontext, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

BENCH = Path(__file__).resolve().parents[1] / "bench"
sys.path.insert(0, str(BENCH))
import payer_challenge
from payer_challenge_cases.scoring import regression_failures, score


class PayerChallengeGateTests(unittest.TestCase):
    def setUp(self):
        self.specs = payer_challenge.cases()
        self.fixtures = BENCH / "payer_challenge_cases"
        self.saved = json.loads((self.fixtures / "retest-observations.json").read_text())
        self.observations = self.saved["observations"]
        self.by_id = {row["id"]: row for row in self.observations}

    def test_wrong_form_page_fails_the_live_command_with_all_cases_held(self):
        self.assertEqual(regression_failures(score(self.specs, self.observations)["rows"]), [])
        mismatch = next(row for row in self.by_id["cms-member"]["findings"] if row["code"] == "cms_member_mismatch")
        mismatch["sources"][0]["page"] = 3  # Correct value on the wrong sheet in the original upload.
        with (
            TemporaryDirectory() as out,
            patch.object(sys, "argv", ["payer_challenge", "--out", out]),
            patch.object(payer_challenge, "prepare", return_value=self.observations),
            patch.object(payer_challenge, "temporary_database", return_value=nullcontext("isolated")),
            patch.object(payer_challenge, "server", return_value=nullcontext(None)),
            patch.object(payer_challenge, "evaluate", side_effect=lambda _, row: row),
            redirect_stdout(StringIO()),
            self.assertRaisesRegex(SystemExit, "regression gate failed"),
        ):
            payer_challenge.main()
        # The historical two-boolean gate would let these observations pass.
        self.assertTrue(all(o["safe"] and o["originals_intact"] for o in self.observations))
        result = score(self.specs, self.observations)
        self.assertEqual(result["summary"]["targets"], {"target-and-page": 10, "wrong-page": 1})
        self.assertEqual([failure["id"] for failure in regression_failures(result["rows"])], ["cms-member"])

    def test_changed_cents_and_prefixed_identifier_each_fail_exact_evidence(self):
        cms = next(row for row in self.by_id["cms-cents"]["findings"] if row["code"] == "cms_total_mismatch")
        cms["sources"][1]["quote"] += "0"
        member = next(row for row in self.by_id["cms-member"]["findings"] if row["code"] == "cms_member_mismatch")
        member["message"] = member["message"].replace("HM0130891", "XHM0130891")
        result = score(self.specs, self.observations)
        self.assertEqual(result["summary"]["targets"], {"target-and-page": 11})
        self.assertEqual(result["summary"]["printed_values_exact_in_form_citations"], 5)
        self.assertEqual(result["summary"]["printed_values_exact_in_messages"], 5)
        self.assertEqual({row["id"] for row in regression_failures(result["rows"])}, {"cms-cents", "cms-member"})

    def test_false_alert_unheld_case_and_missing_original_fail_independently(self):
        self.by_id["fep-aligned"]["findings"].append({"code": "fep_assignment_signature", "sources": []})
        self.by_id["aia-th-aligned"]["safety"]["approve_http"] = 200
        del self.by_id["cms-reference-present"]["pages"]["summary"]
        failures = regression_failures(score(self.specs, self.observations)["rows"])
        self.assertEqual({row["id"] for row in failures}, {"fep-aligned", "aia-th-aligned", "cms-reference-present"})

    def test_missing_duplicate_and_unexpected_observations_are_rejected(self):
        self.observations[0] = self.observations[1]
        self.observations.append({"id": "unexpected-case"})
        with self.assertRaisesRegex(ValueError, "14 cases.*missing aia-th-cents.*unexpected unexpected-case.*duplicate aia-en-id-decoy"):
            score(self.specs, self.observations)

    def test_historical_rescore_remains_readable_and_strict_replay_exits_unsuccessfully(self):
        with TemporaryDirectory() as out:
            argv = ["payer_challenge", "--score-observed", str(self.fixtures / "first-observations.json"), "--out", out]
            with patch.object(sys, "argv", argv), redirect_stdout(StringIO()):
                payer_challenge.main()
            result = json.loads((Path(out) / "scored.json").read_text())
            self.assertEqual(result["mode"], "historical rescore")
            self.assertNotIn("regression_gate", result)
            self.assertEqual(result["summary"]["targets"]["target-and-page"], 10)
            self.assertEqual(result["summary"]["target_challenges"], 11)
            with patch.object(sys, "argv", [*argv, "--require-current"]), redirect_stdout(StringIO()):
                with self.assertRaisesRegex(SystemExit, "regression gate failed"):
                    payer_challenge.main()


if __name__ == "__main__":
    unittest.main()
