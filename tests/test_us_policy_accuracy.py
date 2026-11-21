"""Preserve the difference between a correct answer and correct, verifiable evidence."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))
from us_policy_accuracy import grade, task_spec, value_matches


class AccuracyScoringTests(unittest.TestCase):
    def setUp(self):
        self.pages = {1: "The ordinary filing window applies.", 2: "Only an exception overrides the window."}
        self.row = {
            "id": "sample",
            "en": "Does it apply?",
            "th": "ใช้ไหม",
            "answerable": True,
            "required": [[1], [2]],
            "fields": {"applies": {"type": "boolean", "description": "applicability", "expected": True}},
        }
        self.cell = {
            "status": "completed",
            "selected": [1, 2],
            "output": {
                "answerable": True,
                "fields": [{"key": "applies", "value": True}],
                "citations": [
                    {"page": 1, "quote": "ordinary filing window applies"},
                    {"page": 2, "quote": "exception overrides the window"},
                ],
            },
        }

    def test_gold_stays_out_of_model_spec(self):
        self.assertEqual(
            task_spec(self.row, "th"),
            {"question": "ใช้ไหม", "fields": {"applies": {"type": "boolean", "description": "applicability"}}},
        )

    def test_right_fact_missing_exception_is_not_supported(self):
        self.assertTrue(grade(self.row, self.cell, self.pages)["supported"])
        self.cell["selected"] = [1]
        scores = grade(self.row, self.cell, self.pages)
        self.assertTrue(scores["exact"])
        self.assertFalse(scores["supported"])
        self.assertEqual(scores["covered"], 1)

    def test_wrong_type_or_invented_quote_fails(self):
        self.cell["output"]["citations"][0]["quote"] = "six completely invented words from elsewhere"
        self.assertFalse(grade(self.row, self.cell, self.pages)["supported"])
        self.cell["output"]["fields"][0]["value"] = 1
        self.assertFalse(grade(self.row, self.cell, self.pages)["exact"])

    def test_integer_fields_are_type_strict(self):
        self.assertFalse(value_matches(24.0, 24))
        self.assertFalse(value_matches(True, 1))

    def test_abstention_requires_all_nulls(self):
        self.row.update(answerable=False, required=[])
        self.row["fields"]["applies"]["expected"] = None
        self.cell["output"].update(answerable=False, citations=[])
        self.assertFalse(grade(self.row, self.cell, self.pages)["exact"])
        self.cell["output"]["fields"][0]["value"] = None
        self.assertTrue(grade(self.row, self.cell, self.pages)["supported"])
