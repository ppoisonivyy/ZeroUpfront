from dataclasses import replace
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace as S
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"app"))
from cloud_policy import cloud_retrieve
from policy_rag import Passage


def metadata(p):
    return dict(edition="KM",sha256=p.digest,page=p.page,ref=p.ref)


class HostedSearchTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.pages = [Passage("P1.1","th.pdf","digest",1,"digital","base"),
                      Passage("P2.1","th.pdf","digest",2,"digital","rider")]
        self.client.vector_stores.search.return_value = S(data=[])
        self.client.vector_stores.files.list.return_value = [S(attributes=metadata(p)) for p in self.pages]
        self.store = patch("cloud_policy.store_id",return_value="test-store")
        self.store.start()
        self.addCleanup(self.store.stop)

    @patch("cloud_policy.embed",return_value=[[1,0],[0,1],[1,0]])
    def test_empty_managed_result_falls_back_to_indexed_pages(self, embed):
        self.assertEqual(cloud_retrieve(self.client,"สิทธิ","KM",self.pages,1),[self.pages[1]])
        filters = self.client.vector_stores.search.call_args.kwargs["filters"]["filters"]
        self.assertEqual({f["key"]:f["value"] for f in filters},{"edition":"KM","sha256":"digest"})

    def test_wrong_document_revision_cannot_supply_candidates(self):
        self.client.vector_stores.files.list.return_value = [S(attributes=metadata(replace(self.pages[0],digest="other")))]
        with self.assertRaisesRegex(ValueError,"No indexed evidence"):
            cloud_retrieve(self.client,"question","KM",self.pages)

    def test_result_must_match_physical_page(self):
        self.client.vector_stores.search.return_value = S(data=[S(attributes={**metadata(self.pages[0]),"page":8})])
        with self.assertRaisesRegex(ValueError,"pinned policy"):
            cloud_retrieve(self.client,"question","KM",self.pages)
