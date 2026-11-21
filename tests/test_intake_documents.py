"""Adversarial intake inputs and source-grounded human clarification on generated PDFs."""
import copy
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from app.document_text import Transcript
from app.intake_documents import evaluate_intake, manual_evidence
from app.workspace_documents import _pdf_fonts, clarification_bytes, packet_bytes

ROOT = Path(__file__).resolve().parents[1]
NAMES = {"policy": "schedule.pdf", "estimate": "new estimate.pdf", "plan": "new plan.pdf"}
META = {"id": "CASE-NEW", "insurer": "Alder Transit Cover", "policy_edition": "AT-2026.1",
        "member": "INT-4002", "procedure": "Arthroscopy", "admission_date": "2026-12-11"}
IDENTITY = ["Member ID: INT-4002", "Policy edition: AT-2026.1", "Encounter ID: ENC-845"]
PLAN = ["Inpatient treatment plan", *IDENTITY, "Admission date: 2026-12-11", "Planned procedure: Arthroscopy",
        "Purpose recorded by provider: Repair of an accidental fracture."]
ESTIMATE = ["Cost estimate", *IDENTITY, "Hospital services: THB 65,200", "Operating team: THB 14,800",
            "Total estimated charges: THB 80,000"]


def pdf(*pages):
    stream = io.BytesIO()
    c = Canvas(stream, invariant=1)
    for lines in pages:
        t = c.beginText(45, 770)
        for line in lines:
            t.textLine(line)
        c.drawText(t)
        c.showPage()
    c.save()
    return stream.getvalue()


def files(plan=None, estimate=None, policy=None):
    return {"policy": policy or (ROOT / "fixtures/policies/alder.pdf").read_bytes(),
            "plan": pdf(PLAN if plan is None else plan), "estimate": pdf(ESTIMATE if estimate is None else estimate)}


def case(raw, metadata=META):
    return evaluate_intake(metadata, raw, NAMES)


def history(case, status):
    return {**case, "status": status, "revision": 1, "reviewer": "Coordinator", "insurer_status": "not_sent",
            "history": [{"revision": 1, "status": status, "total": case["total"]}]}


def ref(role, quote, page=1):
    return {"role": role, "page": page, "quote": quote}


def check(rule, support, result="met"):
    return {"requirement": rule, "result": result, "policy": ref("policy", rule), "support": support}


class IntakeTests(unittest.TestCase):
    def test_new_nonfixture_encounter_supports_reconciled_export(self):
        raw = files()
        result = case(raw)
        self.assertEqual((result["status"], result["currency"], result["total"]), ("ready_for_review", "THB", 80000))
        self.assertEqual([r["amount"] for r in result["lines"]], [65200, 14800])
        output = PdfReader(io.BytesIO(packet_bytes(history(result, "staff_reviewed"), raw)))
        self.assertEqual(len(output.pages), 2)
        self.assertIn("Arthroscopy", output.pages[0].extract_text())
        for role in raw:
            self.assertEqual(list(output.attachments[NAMES[role]]), [raw[role]])
        raw["estimate"] = pdf(ESTIMATE[:-1] + ["Total estimated charges: THB 80,010"])
        with self.assertRaisesRegex(ValueError, "digest"):
            packet_bytes(history(result, "staff_reviewed"), raw)

    def test_conflicting_member_edition_encounter_and_procedure(self):
        for original, different in (("INT-4002", "INT-40020"), ("AT-2026.1", "AT-2026.1-OLD"), ("ENC-845", "ENC-8452")):
            with self.subTest(different=different), self.assertRaisesRegex(ValueError, "encounter|conflicting"):
                case(files(estimate=[line.replace(original, different) for line in ESTIMATE]))
        with self.assertRaisesRegex(ValueError, "procedure"):
            case(files(), {**META, "procedure": "Appendectomy"})
        self.assertEqual(case(files(estimate=[line for line in ESTIMATE if "Encounter" not in line]))["status"], "needs_review")
        self.assertEqual(case(files(estimate=[line for line in ESTIMATE if "Member ID" not in line]))["status"], "needs_review")
        for setting in ([*PLAN, "Care setting: Outpatient"], ["Treatment plan", *PLAN[1:]]):
            with self.subTest(setting=setting[0]):
                self.assertEqual(case(files(plan=setting))["status"], "needs_review")

    def test_unknown_or_contradictory_money_is_unavailable(self):
        cases = (([line.replace("THB", "USD") for line in ESTIMATE], "USD"),
                 ([*ESTIMATE[:-1], "Total estimated charges: USD 80,000"], None),
                 ([*ESTIMATE[:-1], "Total estimated charges: THB 80,100"], "THB"),
                 ([*ESTIMATE, "Excluded item THB 6,500"], "THB"),
                 ([*ESTIMATE, ESTIMATE[-1]], "THB"),
                 ([*ESTIMATE[:-1], "Total estimated charges: THB 80,000.05"], "THB"))
        for lines, currency in cases:
            with self.subTest(lines=lines[-1]):
                result = case(files(estimate=lines))
                self.assertEqual((result["status"], result["currency"], result["total"], result["lines"]),
                                 ("needs_review", currency, None, []))
        no_rows = case(files(estimate=[*IDENTITY, ESTIMATE[-1]]))
        self.assertEqual((no_rows["status"], no_rows["clause"]), ("needs_itemization", "AT-2"))
        small = files(estimate=[*IDENTITY, "Total estimated charges: THB 20,000"])
        packet = PdfReader(io.BytesIO(packet_bytes(history(case(small), "staff_reviewed"), small)))
        self.assertIn("total only", packet.pages[0].extract_text())

    def test_offline_scan_stays_pending_and_completed_ocr_can_be_replayed_without_network(self):
        scanner = pdf([])  # An empty physical page requires the same OCR path as a scanned page.
        raw = {**files(), "estimate": scanner}
        held = case(raw)
        self.assertIsNone(held["total"])
        self.assertEqual(held["status"], "needs_review")
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(status="completed",
            output_parsed=Transcript(legibility="complete", text="\n".join(ESTIMATE)))
        reviewed = evaluate_intake(META, raw, NAMES, ocr_client=client)
        self.assertEqual(reviewed["status"], "needs_review")
        self.assertEqual(reviewed["total"], 80000)
        estimate = next(s for s in reviewed["sources"] if s["role"] == "estimate")
        self.assertEqual(estimate["method"], "ocr")
        saved = manual_evidence(reviewed, raw, {"fields": {"estimated_total_thb": ref("estimate", ESTIMATE[-1])}})
        self.assertTrue(saved["clarification_available"])
        client.responses.parse.assert_called_once()

    def test_unknown_edition_uses_only_verified_manual_evidence_and_separate_clarification(self):
        wording = "Prior authorization requires the hospital plan and individual service prices."
        raw = files(policy=pdf(["Other policy", "AT-2026.1"], [wording]))
        result = case(raw)
        self.assertEqual(result["status"], "needs_review")
        c = check(wording, ref("estimate", ESTIMATE[-1]))
        c["policy"]["page"] = 2
        reviewed = manual_evidence(result, raw, {"fields": {"member": ref("plan", IDENTITY[0])}, "checks": [c]})
        self.assertEqual(reviewed["status"], "needs_review")
        print_case = history(reviewed, "needs_review")
        report = PdfReader(io.BytesIO(clarification_bytes(print_case, raw)))
        text = " ".join(page.extract_text() for page in report.pages)
        self.assertIn("Insurance clarification request", text)
        self.assertIn("Coverage and payment remain unconfirmed", text)
        self.assertIn("schedule.pdf / p. 2", text)
        self.assertEqual(set(report.attachments), set(NAMES.values()))
        with self.assertRaises(ValueError):
            packet_bytes(history(reviewed, "staff_reviewed"), raw)
        for bad in (ref("policy", wording, 1), ref("estimate", wording), ref("policy", "invented text", 2)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                manual_evidence(result, raw, {"checks": [{**c, "policy": bad}]})
        with self.assertRaisesRegex(ValueError, "revision"):
            clarification_bytes({**print_case, "history": [*print_case["history"], {"revision": 2}]}, raw)
        different = copy.copy(raw)
        different["plan"] = pdf(["Different patient's plan"])
        with self.assertRaises(ValueError):
            clarification_bytes(print_case, different)

    def test_full_known_rulebook_and_all_fields_required_to_resolve_layout(self):
        raw = files(plan=[*PLAN, "Clinical department received the signed original."])
        result = case(raw)
        self.assertEqual(result["status"], "needs_review")
        fields = {"member": ref("plan", IDENTITY[0]), "procedure": ref("plan", PLAN[-2]),
                  "admission_date": ref("plan", PLAN[-3]), "estimated_total_thb": ref("estimate", ESTIMATE[-1])}
        policy = next(s for s in result["sources"] if s["role"] == "policy")
        support = {"AT-1": ref("estimate", ESTIMATE[-1]), "AT-2": ref("estimate", ESTIMATE[-3]), "AT-3": ref("plan", PLAN[-2])}
        checks = [check(c["quote"], support[c["clause"]]) for c in policy["anchors"]]
        self.assertEqual(manual_evidence(result, raw, {"fields": fields, "checks": checks[:-1]})["status"], "needs_review")
        unsuitable = [{**check, "support": ref("estimate", IDENTITY[0])} if check["requirement"] == checks[1]["requirement"]
                      else check for check in checks]
        self.assertEqual(manual_evidence(result, raw, {"fields": fields, "checks": unsuitable})["status"], "needs_review")
        cleared = manual_evidence(result, raw, {"fields": fields, "checks": checks})
        self.assertEqual(cleared["status"], "ready_for_review")
        self.assertEqual(len(PdfReader(io.BytesIO(packet_bytes(history(cleared, "staff_reviewed"), raw))).pages), 2)
        checks[1]["result"] = "possible_exclusion"
        self.assertEqual(manual_evidence(result, raw, {"fields": fields, "checks": checks})["status"], "possible_exclusion")

    def test_thai_procedure_and_staff_name_are_embedded_as_source_unicode(self):
        procedure = "ผ่าตัดข้อมือ"
        reviewer = "วันที่เข้ารักษา"
        font = _pdf_fonts()
        source = io.BytesIO()
        canvas = Canvas(source, invariant=1)
        for n, line in enumerate([*PLAN[:-2], "Planned procedure:", procedure, PLAN[-1]]):
            canvas.setFont(font.fontName if line == procedure else "Helvetica", 12)
            canvas.drawString(45, 770-18*n, line)
        canvas.save()
        raw = {**files(), "plan": source.getvalue()}
        result = case(raw, {**META, "procedure": procedure})
        self.assertEqual(result["status"], "ready_for_review")
        approved = {**history(result, "staff_reviewed"), "reviewer": reviewer}
        pdf = PdfReader(io.BytesIO(packet_bytes(approved, raw)))
        page = pdf.pages[0]
        self.assertIn(procedure, page.extract_text())
        for value in (procedure, reviewer):
            encoded = (b"\xfe\xff" + value.encode("utf-16be")).hex().encode()
            self.assertIn(b"/ActualText <" + encoded + b">", page.get_contents().get_data())
        self.assertTrue(any("NotoSansThai" in str(font_info.get_object().get("/BaseFont"))
                            for font_info in page["/Resources"]["/Font"].values()))
        with self.assertRaisesRegex(ValueError, "cannot be rendered"):
            packet_bytes({**approved, "reviewer": "🌏"}, raw)

    def test_non_pdf_encrypted_too_many_pages_and_missing_roles_rejected(self):
        oversized = PdfWriter()
        for _ in range(201):
            oversized.add_blank_page(20, 20)
        stream = io.BytesIO()
        oversized.write(stream)
        for data in (b"not a pdf", stream.getvalue()):
            with self.assertRaises(ValueError):
                case({**files(), "estimate": data})
        encrypted = PdfWriter()
        encrypted.add_blank_page(40, 40)
        encrypted.encrypt("secret")
        stream = io.BytesIO()
        encrypted.write(stream)
        with self.assertRaisesRegex(ValueError, "unlocked"):
            case({**files(), "estimate": stream.getvalue()})
        with self.assertRaisesRegex(ValueError, "exactly one"):
            case({"estimate": pdf(ESTIMATE)})

    def test_unseen_negative_language_extra_riders_and_unverified_policy_editions_hold(self):
        base = files()
        for label in ("Provider name: Membership inactive", "Source: Policy not in force",
                      "Source: Hospital card expired", "Source: Procedure deferred pending insurer reply",
                      "Hospital name: Amendments to coverage apply",
                      "Source: Updated member ID differs from this referral"):
            with self.subTest(label=label):
                result = case(files(plan=[*PLAN, label]))
                self.assertEqual(result["status"], "needs_review")
        amended = PdfWriter(clone_from=io.BytesIO(base["policy"]))
        amended.append(io.BytesIO(pdf(["Rider AT-X", "This edition excludes this admission."])))
        modified = io.BytesIO()
        amended.write(modified)
        result = case(files(policy=modified.getvalue()))
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("no verified rulebook", result["reason"])
        mismatch = case(files(policy=pdf(["Policy edition: AT-2025.1", "Earlier schedule"])))
        self.assertIn("edition differs", mismatch["reason"])
        attached = PdfWriter(clone_from=io.BytesIO(base["plan"]))
        attached.add_attachment("new-rider.pdf", pdf(["This rider changes the available benefit."]))
        supplement = io.BytesIO()
        attached.write(supplement)
        self.assertIn("attachments", case({**base, "plan": supplement.getvalue()})["reason"])
        nonstructured = files(estimate=["We expect an admission to run around 80,000, maybe with tax.",
                                       "Other encounter ENC-847; member INT-4002"])
        unstructured = case(nonstructured)
        self.assertEqual((unstructured["status"], unstructured["total"]), ("needs_review", None))

    def test_same_member_and_date_do_not_override_independent_encounter_or_financial_scope(self):
        no_id = [line for line in ESTIMATE if "Encounter ID" not in line]
        result = case(files(estimate=[*no_id, PLAN[-3], PLAN[-2]]))
        self.assertEqual(result["status"], "needs_review")
        for key, value in (("admission_date", "2026-12-12"), ("insurer", "Invented payer"),
                           ("member", "UNKNOWN"), ("procedure", "Not specified")):
            with self.subTest(field=key), self.assertRaises(ValueError):
                case(files(), {**META, key: value})
        with self.assertRaisesRegex(ValueError, "conflicting"):
            case(files(plan=[*PLAN, "Admission date: 2027-01-11"]))
        with self.assertRaisesRegex(ValueError, "conflicting"):
            case(files(estimate=[*ESTIMATE, "Planned procedure: Dental surgery"]))
        result = case(files(estimate=[*ESTIMATE, "Source: SAR 20,000"]))
        self.assertEqual((result["status"], result["currency"], result["total"]), ("needs_review", None, None))
        large = files(estimate=[*IDENTITY, "Supplies: THB 180,001", "Total estimated charges: THB 180,001"])
        self.assertEqual((case(large)["status"], case(large)["clause"]), ("needs_review", "AT-1"))


if __name__ == "__main__":
    unittest.main()
