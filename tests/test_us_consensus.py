from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))
from us_policy_consensus import decide, decide_fields


class ConsensusTest(unittest.TestCase):
    def setUp(self):
        self.pages = {1: "The stated dollar limit applies here.", 2: "This is a separate source clause."}
        self.contract = {"amount": {"type": "integer"}}
        self.quote = {"page": 1, "quote": self.pages[1]}
        self.full = {"status": "completed", "selected": [1, 2], "output": {"answerable": True,
                     "fields": [{"key": "amount", "value": 1}], "citations": [self.quote]}}
        self.rag = deepcopy(self.full)

    def test_agreement_and_shared_source(self):
        self.assertEqual(decide(self.full, self.rag, self.contract, self.pages)[0], "release")
        self.rag["output"]["citations"] = [{"page": 2, "quote": self.pages[2]}]
        self.assertEqual(decide(self.full, self.rag, self.contract, self.pages)[0], "review")

    def test_bad_values_or_invented_citation_require_review(self):
        for key, value in (("fields", [{"key": "amount", "value": True}]),
                           ("fields", [{"key": "amount", "value": 2}]),
                           ("citations", [{"page": 1, "quote": "Some other invented source clause."}])):
            with self.subTest(key=key, value=value):
                self.rag["output"] = {**self.full["output"], key: value}
                self.assertEqual(decide(self.full, self.rag, self.contract, self.pages)[0], "review")

    def test_both_explicitly_missing(self):
        missing = {"status": "completed", "selected": [1], "output": {
            "answerable": False, "fields": [{"key": "amount", "value": None}], "citations": []}}
        self.assertEqual(decide(missing, missing, self.contract, self.pages)[0], "missing")
        self.assertEqual(decide(self.full, missing, self.contract, self.pages)[0], "review")

    def test_every_field_needs_its_own_citation(self):
        second = {"status": "completed", "selected": [1], "output": {"fields": [
            {"key": "amount", "value": 1, "citations": [self.quote]}]}}
        self.assertEqual(decide_fields(self.full, second, self.contract, self.pages)[0], "release")
        second["output"]["fields"][0]["citations"] = []
        self.assertEqual(decide_fields(self.full, second, self.contract, self.pages)[0], "review")
