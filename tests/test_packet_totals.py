import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from document_text import read_document
from packet_totals import reconcile_packet


class PacketTotalsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packets = {
            pack: tuple(read_document(ROOT/"fixtures"/"complex"/f"{pack}-{kind}.pdf")
                        for kind in ("policy", "case"))
            for pack in ("th", "us")
        }

    def change(self, pack, old, new):
        policy, case = self.packets[pack]
        self.assertIn(old, case.text)
        pages = [replace(p, native=p.native.replace(old,new)) for p in case.pages]
        return reconcile_packet(pack,policy,replace(case,pages=pages))

    def change_page(self, pack, number, old, new):
        policy, case = self.packets[pack]
        pages = list(case.pages)
        page = pages[number - 1]
        self.assertIn(old, page.native)
        pages[number - 1] = replace(page, native=page.native.replace(old, new))
        return reconcile_packet(pack, policy, replace(case, pages=pages))

    def assert_withheld(self, result):
        for field in ("estimated_total_thb", "member_share_thb", "pending_evidence_thb", "draft_request_thb"):
            self.assertIsNone(result[field], field)
        self.assertTrue(result["review_reason"])

    def test_review_ready_draft_and_unknown_paid(self):
        result = reconcile_packet("th",*self.packets["th"])
        self.assertEqual(result["estimated_total_thb"],144000)
        self.assertEqual(result["member_share_thb"],2200)
        self.assertEqual(result["draft_request_thb"],141800)
        self.assertIsNone(result["paid_to_date_thb"])

    def test_pending_supplier_stays_out_of_draft(self):
        result = reconcile_packet("us",*self.packets["us"])
        self.assertEqual(result["estimated_total_thb"],220000)
        self.assertEqual(result["pending_evidence_thb"],62000)
        self.assertEqual(result["member_share_thb"],1300)
        self.assertIsNone(result["draft_request_thb"])

    def test_fx_is_read_from_evidence(self):
        result = self.change("us","35.00 THB per USD","40.00 THB per USD")
        self.assertEqual(result["member_share_thb"],200)

    def test_th_statement_headers_and_supplement_must_match_exactly(self):
        for page, old, new in [
            (1, "KM-26C Gold / R9", "KM-26C Gold / R90"),
            (3, "HN-DEMO-205", "HN-DEMO-2050"),
            (4, "HN-DEMO-205", "HN-DEMO-205-OLD"),
            (3, "IPD-205", "IPD-2059"),
            (4, "IPD-205", "IPD-2059"),
            (3, "THB", "USD"),
            (4, "All amounts are THB.", "All amounts are USD."),
            (4, "All amounts are THB.", "All amounts are THB. All amounts are USD."),
            (3, "revision R2.", "revision R8."),
            (4, "Hospital statement R2", "Hospital statement R20"),
            (4, "sheet 2 of 2", "sheet 2 of 20"),
        ]:
            with self.subTest(page=page, new=new):
                self.assert_withheld(self.change_page("th", page, old, new))

    def test_us_current_revision_and_currency_must_agree_across_exhibits(self):
        for page, old, new in [
            (1, "NQ-26B / G2 / M7", "NQ-26B / G2 / M70"),
            (3, "Estimate E-118-R2,", "Estimate E-118-R20,"),
            (4, "Revision 2 is the current", "Revision 3 is the current"),
            (3, "this table are THB.", "this table are USD."),
            (3, "Charge Qty Net THB", "Charge Qty Net USD"),
            (4, "THB 62,000", "USD 62,000"),
            (4, "THB 62,000", "THB 60,000"),
            (5, "requested in THB.", "requested in USD."),
        ]:
            with self.subTest(page=page, new=new):
                self.assert_withheld(self.change_page("us", page, old, new))

    def test_case_id_and_dated_clinical_exhibit_are_required(self):
        for pack, ident in (("th", "KM-D205"), ("us", "NQ-D481")):
            with self.subTest(pack=pack):
                self.assert_withheld(self.change_page(pack, 4, ident, ident + "0"))
                original = self.packets[pack][1].pages[1].native
                self.assert_withheld(self.change_page(pack, 2, original, ""))
                header = original.split("Clinical", 1)[0]
                self.assert_withheld(self.change_page(pack, 2, original, header + "Clinical timeline"))

    def test_finance_stops_on_inconsistent_or_unsupported_inputs(self):
        for old,new in [
            ("152,000 8,000 144,000","152,000 8,000 145,000"),
            ("5,800 0 5,800","5,800 0 5,800.80"),
            ("80,000 5,000 75,000","80,000 5,000 70,000"),
            ("KM-26C Gold / R9","KM-26C Silver / R9"),
            ("Admission at facility BKK-17","Admission at facility BKK-71"),
            ("on 21 November 2026","on 21 October 2026"),
            ("second sheet of the same R2","second sheet of the same R3"),
        ]:
            with self.subTest(new=new):
                self.assertIsNone(self.change("th",old,new)["draft_request_thb"])
