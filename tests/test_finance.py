import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from finance import ReviewRequired, billing_fields, gop_fields, money, reconcile_gop
from finance_eval import evaluate, financial_fields


def bill():
    return {
        "B p1 header": "Hospital | Final | demo | THB | Page 1 of 1",
        "B p1 columns": "Item List | Total Amount | Discount | Total Net",
        "B p1 subtotal": "Subtotal | 1,001.13 | 0.03 | 1,001.10",
        "B p1 row 1": "Room | 1,000.01 | 0.01 | 1,000.00",
        "B p1 row 2": "Test | 1.12 | 0.02 | 1.10",
    }


def gop():
    return {
        "S p1": "Mock River schedule | member demo | 2026-02-01 to 2026-03-03 | no deductible, co-pay or waiting period | available THB 1,000.02",
        "P §1": "Planned inpatient procedures in Thailand are covered during the membership period up to the available inpatient balance.",
        "P §2": "Attach an itemized estimate and a signed treatment plan.",
        "P §3": "Guest accommodation is excluded.",
        "N p1": "demo | Sample Clinic, Thailand | 2026-03-03 | inpatient | planned procedure | clinician signature: present",
        "Q p1": "demo | same provider and admission | estimate THB: procedure 1000.03, bed 50, Guest accommodation 60 | total 1,110.03",
    }


class FinancialRegressionTests(unittest.TestCase):
    def test_currency_precision(self):
        self.assertEqual(money("1,000.01"), Decimal("1000.01"))
        for bad in ("1.001", "1,00.00", "NaN", "-1", "12O0", "THB 1", "1e6"):
            with self.subTest(raw=bad), self.assertRaises(ReviewRequired):
                money(bad)

    def test_structured_amounts_are_checked_at_boundary(self):
        for invalid in (Decimal("-0.01"), Decimal("NaN"), Decimal("1.123"), Decimal("Infinity")):
            with self.subTest(value=invalid), self.assertRaises(ReviewRequired):
                reconcile_gop(Decimal("1"), [("bed", Decimal("1"))], set(), invalid, True)

    def test_receipt_is_independent_evidence(self):
        exhibits = bill()
        self.assertIsNone(billing_fields("demo", exhibits)["balance_due"])
        exhibits["R p1"] = "ใบเสร็จรับเงิน | demo | ยอดชำระ 0 THB | all payments to date"
        self.assertEqual(billing_fields("demo", exhibits)["balance_due"], Decimal("1001.10"))
        exhibits["R p1"] = exhibits["R p1"].replace("0 THB", "1,001.10 THB")
        self.assertEqual(billing_fields("demo", exhibits)["balance_due"], 0)

    def test_unattributable_receipt(self):
        for receipt in ("ใบเสร็จรับเงิน | someone-else | ยอดชำระ 0 THB | all payments to date",
                        "ใบเสร็จรับเงิน | demo | ยอดชำระ 0 THB | deposit only",
                        "ใบเสร็จรับเงิน | demo | ยอดชำระ 0 USD | all payments to date"):
            with self.subTest(receipt=receipt), self.assertRaises(ReviewRequired):
                billing_fields("demo", bill() | {"R p1": receipt})

    def test_missing_sheet_blocks_reconciled_balance(self):
        exhibits = bill()
        exhibits["B p1 header"] = exhibits["B p1 header"].replace("1 of 1", "1 of 2")
        result = billing_fields("demo", exhibits)
        self.assertEqual(result["reconciliation"], "incomplete_pages")
        self.assertIsNone(result["delta_reported_minus_detail"])
        self.assertIsNone(result["balance_due"])

    def test_wrong_detail_with_matching_net(self):
        exhibits = bill()
        exhibits["B p1 row 2"] = "Test | 2.12 | 1.02 | 1.10"
        result = billing_fields("demo", exhibits)
        self.assertEqual(result["reconciliation"], "amount_mismatch")
        self.assertIsNone(result["balance_due"])

    def test_multipage_subtotals_not_counted_twice(self):
        exhibits = bill()
        exhibits["B p1 header"] = exhibits["B p1 header"].replace("1 of 1", "1 of 2")
        exhibits.update({"B p2 header": "Hospital | Final | demo | THB | Page 2 of 2",
                         "B p2 row 1": "Additional test | 11.12 | 1.12 | 10.00",
                         "B p2 subtotal": "Subtotal | 11.12 | 1.12 | 10.00",
                         "B p2 total": "Total | 1,012.25 | 1.15 | 1,011.10"})
        result = billing_fields("demo", exhibits)
        self.assertEqual(result["reconciliation"], "matches")
        self.assertEqual(result["visible_detail_net"], Decimal("1011.10"))
        exhibits["B p2 subtotal"] = "Subtotal | 100 | 0 | 100"
        with self.assertRaises(ReviewRequired):
            billing_fields("demo", exhibits)

    def test_gop_order_of_operations(self):
        result = gop_fields("demo", gop())
        self.assertEqual(result["excluded_thb"], 60)
        self.assertEqual(result["above_balance_thb"], Decimal("50.01"))
        self.assertEqual(result["draft_request_thb"], Decimal("1000.02"))
        self.assertEqual(result["status"], "READY FOR IPD REVIEW")

    def test_missing_signature_or_balance(self):
        exhibits = gop()
        exhibits["N p1"] = exhibits["N p1"].replace("present", "blank")
        held = gop_fields("demo", exhibits)
        self.assertEqual(held["provisional_eligible_thb"], Decimal("1000.02"))
        self.assertIsNone(held["draft_request_thb"])
        self.assertEqual(held["status"], "HOLD")
        exhibits["S p1"] = exhibits["S p1"].replace("1,000.02", "[unreadable]")
        held = gop_fields("demo", exhibits)
        self.assertIsNone(held["above_balance_thb"])
        self.assertIsNone(held["provisional_eligible_thb"])

    def test_rejects_wrong_scope_and_money(self):
        changes = [
            ("Q p1", "1,110.03", "1,110.04"), ("Q p1", "demo", "other"),
            ("N p1", "2026-03-03", "2026-03-04"), ("N p1", "Thailand", "France"),
            ("S p1", "no deductible", "has deductible"), ("S p1", "Mock River", "Mock Lotus"),
            ("S p1", "available THB", "available USD"), ("P §3", "is excluded", "is sometimes excluded"),
            ("Q p1", "Guest accommodation", "unclassified charge"),
        ]
        for key, old, new in changes:
            exhibits = gop()
            exhibits[key] = exhibits[key].replace(old, new)
            with self.subTest(change=(key,new)), self.assertRaises(ReviewRequired):
                gop_fields("demo", exhibits)

    def test_eval_uses_gold_only_after_inference(self):
        exhibits = gop()
        packet = {"case": "demo", "exhibits": exhibits}
        calculated = financial_fields(packet)
        self.assertEqual(calculated["draft_request_thb"], Decimal("1000.02"))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for split in ("train", "eval"):
                case = f"demo-{split}"
                packet = {"case": case, "exhibits": {k: v.replace("demo",case) for k,v in exhibits.items()}}
                gold = {k:float(v) if isinstance(v, Decimal) else v for k,v in calculated.items()}
                if split == "eval":
                    gold["draft_request_thb"] = 0
                messages = [{"role":"system","content":""},{"role":"user","content":json.dumps(packet)},
                            {"role":"assistant","content":json.dumps(gold)}]
                (root / f"{split}.jsonl").write_text(json.dumps({"messages":messages})+"\n")
            with redirect_stdout(StringIO()):
                self.assertFalse(evaluate(root))
