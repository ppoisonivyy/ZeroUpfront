import copy
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))
from rulebook_lookup import CATALOG, FIXTURES, lookup, read_document


class RulebookLookupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG.read_text())
        cls.document = read_document(FIXTURES / "us-policy.pdf")

    def resolve(self, catalog=None, document=None, task="review_accident_notice"):
        return lookup(self.catalog if catalog is None else catalog, "NQ-26B", task,
                      self.document if document is None else document)

    def test_rider_dependencies_and_provenance(self):
        rows = self.resolve()["exhibits"]
        self.assertEqual({(r["page"], r["clause"]) for r in rows},
                         {(3, "NQ-3.2"), (7, "NQ-7.1"), (7, "NQ-7.2")})
        self.assertTrue(all(r["sha256"] == self.document.sha256 for r in rows))

    def test_wrong_pdf_bytes_or_edition(self):
        with self.assertRaisesRegex(ValueError, "digest or edition"):
            self.resolve(document=replace(self.document, sha256="0" * 64))
        catalog = copy.deepcopy(self.catalog)
        catalog["policies"]["NQ-27B"] = catalog["policies"]["NQ-26B"]
        with self.assertRaisesRegex(ValueError, "digest or edition"):
            lookup(catalog, "NQ-27B", "review_accident_notice", self.document)

    def test_wrong_or_clipped_quote_and_page(self):
        for replacements in ({"quote": "A different quote."}, {"page": 3},
                             {"quote": "Rider M6 applied to earlier admissions and allowed 60 hours."}):
            with self.subTest(replacements):
                catalog = copy.deepcopy(self.catalog)
                catalog["policies"]["NQ-26B"]["clauses"]["NQ-7.2"].update(replacements)
                with self.assertRaises(ValueError):
                    self.resolve(catalog)

    def test_missing_and_cyclic_dependencies(self):
        for invalid in ("NQ-99.9", "NQ-7.1"):
            with self.subTest(invalid):
                catalog = copy.deepcopy(self.catalog)
                catalog["policies"]["NQ-26B"]["clauses"]["NQ-3.2"]["requires"] = [invalid]
                with self.assertRaisesRegex(ValueError, "dependency"):
                    self.resolve(catalog)

    def test_unsupported_task(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            self.resolve(task="unlisted_workflow")


if __name__ == "__main__":
    unittest.main()
