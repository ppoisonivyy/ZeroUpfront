"""Unseen identifiers, cents, routing and edition guards for US administrative form checks."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from app.discharge_claim import Review
from app.payer_pages import CaseOriginals
from app.payer_us import ARTWORK, screen_us

META = {
    "member": "R37910182",
    "encounter": "IP-070902",
    "facility": "Twin Fir Clinic",
    "insurer": "BCBS Federal Employee Program",
    "procedure": "General inpatient evaluation",
    "admission_date": "2026-09-07",
    "discharge_date": "2026-09-09",
    "as_of": "2026-09-10",
}

# Independently authored label geometry for CI, with optional real publisher backgrounds in the local rehearsal.
CMS_LABELS = [
    (43, 734, "4 TYPE OF BILL"),
    (44, 560, "47 TOTAL CHARGES"),
    (243, 217, "64 DOCUMENT CONTROL NUMBER"),
    (42, 58, "UB-04 CMS-1450"),
    (234, 667, "17 STAT"),
    (45, 302, "50 PAYER NAME"),
    (44, 259, "UNIQUE ID"),
]
FEP_LABELS = [
    (325, 747, "OVERSEAS MEDICAL CLAIM FORM"),
    (16, 159, "5D. AUTHORIZATION FOR ASSIGNMENT OF BENEFITS"),
    (16, 269, "5C. COMPLETE FOR ELECTRONIC FUND TRANSFER"),
    (431, 23, "CUT0159-1S 08/23"),
    (107, 19, "Signature of Contract Holder or Patient"),
    (16, 89, "Signature of Contract Holder or Spouse"),
    (15, 315, "5A. CONTRACT HOLDER REIMBURSEMENT INFORMATION"),
    (15, 290, "5B. SELECT TYPE OF REIMBURSEMENT"),
    (450, 731, "IDENTIFICATION NUMBER"),
    (15, 347, "TOTAL CHARGES"),
]


def sheet(runs, stroke=False):
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(612, 792), invariant=1)
    canvas.setFont("Helvetica", 8)
    for x, y, t in runs:
        canvas.drawString(x, y, t)
    if stroke:
        canvas.line(180, 91, 194, 95)
    canvas.showPage()
    canvas.save()
    return stream.getvalue()


def joined(*pdfs):
    writer = PdfWriter()
    for part in pdfs:
        for page in PdfReader(BytesIO(part)).pages:
            writer.add_page(page)
    data = BytesIO()
    writer.write(data)
    return data.getvalue()


def form(family, runs, blanks=None, stroke=False, rotated=False):
    if blanks:
        base = blanks[family]
    else:
        base = sheet(CMS_LABELS if family == "cms" else FEP_LABELS)
    writer = PdfWriter()
    p = writer.add_page(PdfReader(BytesIO(base)).pages[0], excluded_keys=["/Annots"])
    p.merge_page(PdfReader(BytesIO(sheet(runs, stroke))).pages[0])
    if rotated:
        p.rotate(90)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def unfamiliar_case(scenario, blanks=None):
    """Make a new encounter and case-specific controls without importing the original benchmark data."""
    family = scenario.split("_")[0]
    meta = META | {"insurer": "Medicare Part A"} if family == "cms" else META.copy()
    invoice_amount = "USD 7,020.64" if family == "cms" else "EUR 7,020.64"
    wrong_invoice = scenario == "fep_unlinked"
    invoice_header = f"Member {meta['member']}  Visit " + (
        "OTHER-IP" if wrong_invoice else meta["encounter"]
    )
    invoice_rows = [
        (33, 733, "Final itemized invoice"),
        (33, 719, meta["facility"]),
        (33, 706, invoice_header),
        (33, 686, "Ward and theatre: 6,880.10"),
        (33, 666, "Laboratory: 140.54"),
        (33, 640, "Invoice total: " + invoice_amount),
    ]
    if scenario == "fep_ambiguous_totals":
        invoice_rows.append((33, 610, "Grand total: EUR 7,115.55"))
    if scenario == "fep_only_estimate":
        invoice_rows[-1] = (33, 640, "Estimated invoice total: EUR 3,100.22")
    if scenario == "fep_repeat_total":
        invoice_rows.append((33, 615, "Total charges: EUR 7,020.64"))
    invoice = sheet(invoice_rows)
    summary = sheet(
        [
            (36, 729, "Final discharge summary"),
            (36, 715, "Facility: " + meta["facility"]),
            (36, 703, invoice_header),
            (
                36,
                676,
                "Disposition: home with hospice"
                if scenario == "cms_hospice"
                else "Disposition: transfer to a short-term general hospital.",
            ),
        ]
    )
    if scenario == "cms_no_named_member":
        summary = sheet(
            [
                (36, 729, "Final discharge summary"),
                (36, 703, f"Person {meta['member']}. Visit {meta['encounter']}."),
                (36, 676, "Disposition: transfer to a short-term general hospital."),
            ]
        )
    if scenario == "cms_competing_dispositions":
        summary = joined(
            summary, sheet([(36, 703, invoice_header), (36, 676, "Disposition: home.")])
        )
    if family == "cms":
        rows = [
            (
                544,
                722,
                "117"
                if scenario
                in {"cms_replacement", "cms_dcn_present", "cms_pending_reference"}
                else "111",
            ),
            (46, 291, "MEDICARE PART A"),
            (233, 247, "R37910183" if scenario == "cms_identity" else meta["member"]),
            (
                238,
                656,
                "01" if scenario in {"cms_disposition", "cms_hospice"} else "02",
            ),
            (46, 312, "0001"),
            (442, 312, "7020"),
            (477, 312, "63" if scenario == "cms_fraction" else "64"),
        ]
        if scenario in {"cms_dcn_present", "cms_pending_reference"}:
            rows.append(
                (248, 205, "154209993" if scenario == "cms_dcn_present" else "pending")
            )
        docs = {
            "bill": joined(
                sheet([(35, 722, "Packet cover")]), form("cms", rows, blanks), invoice
            ),
            "summary": summary,
        }
    else:
        election = scenario in {
            "fep_member",
            "fep_mixed",
            "fep_two_choices",
            "fep_handwriting",
        }
        has_provider = scenario not in {
            "fep_member",
            "fep_two_choices",
            "fep_handwriting",
        }
        rows = [
            (456, 711, "58288172" if scenario == "fep_wrong_member" else "37910182"),
            (
                372,
                350,
                "USD 7,020.63"
                if scenario == "fep_currency"
                else "EUR 7,020.63"
                if scenario in {"fep_fraction", "fep_wrong_member"}
                else "EUR 7,020.64",
            ),
        ]
        if scenario == "fep_bank_and_assignment":
            rows.append((170, 254, "Harbour Example Account"))
        if scenario != "fep_no_general_signature":
            rows.append((26, 31, "K. Written"))
        if election:
            rows.extend([(362, 310, "X"), (441, 282, "X")])
        if scenario == "fep_two_choices":
            rows.append((362, 282, "X"))
        if has_provider:
            payee = {
                "fep_escrow": "Rainier Hospital Escrow",
                "fep_physician_group": "Summit Physician Partners",
                "fep_matching_provider": "TWIN FIR CLINIC",
            }.get(scenario, meta["facility"])
            rows += [(82, 137, payee), (397, 90, "09/10/2026")]
            if scenario != "fep_no_assignment_signature":
                rows.append(
                    (
                        165,
                        90,
                        "pending" if scenario == "fep_placeholder" else "Kai Written",
                    )
                )
        first = form(
            "fep",
            rows,
            blanks,
            stroke=scenario == "fep_handwriting",
            rotated=scenario == "fep_rotated",
        )
        docs = {
            "bill": invoice,
            "records": joined(sheet([(33, 720, "Admission packet")]), first),
            "summary": summary,
        }
        if scenario == "fep_two_editions":
            docs["records"] = joined(first, first)
    return meta, docs


EXPECTED = {
    "cms_baseline": (
        [],
        [
            "cms_insured_id_agrees",
            "cms_initial_claim_type",
            "cms_disposition_agrees",
            "cms_stated_total_agrees",
        ],
    ),
    "cms_fraction": (
        ["cms_total_mismatch"],
        ["cms_insured_id_agrees", "cms_initial_claim_type", "cms_disposition_agrees"],
    ),
    "cms_identity": (["cms_member_mismatch"], []),
    "cms_disposition": (
        ["cms_disposition_mismatch"],
        ["cms_insured_id_agrees", "cms_initial_claim_type", "cms_stated_total_agrees"],
    ),
    "cms_replacement": (
        ["cms_original_claim_reference"],
        ["cms_insured_id_agrees", "cms_disposition_agrees", "cms_stated_total_agrees"],
    ),
    "cms_dcn_present": (
        [],
        [
            "cms_insured_id_agrees",
            "cms_original_reference_present",
            "cms_disposition_agrees",
            "cms_stated_total_agrees",
        ],
    ),
    "cms_hospice": (
        [],
        ["cms_insured_id_agrees", "cms_initial_claim_type", "cms_stated_total_agrees"],
    ),
    "fep_baseline": ([], ["fep_provider_assignment", "fep_stated_total_agrees"]),
    "fep_member": ([], ["fep_member_reimbursement", "fep_stated_total_agrees"]),
    "fep_escrow": (["fep_assignment_provider"], ["fep_stated_total_agrees"]),
    "fep_physician_group": (["fep_assignment_provider"], ["fep_stated_total_agrees"]),
    "fep_matching_provider": (
        [],
        ["fep_provider_assignment", "fep_stated_total_agrees"],
    ),
    "fep_fraction": (["fep_total_mismatch"], ["fep_provider_assignment"]),
    "fep_currency": (["fep_currency_review"], ["fep_provider_assignment"]),
    "fep_unlinked": (["fep_amount_review"], ["fep_provider_assignment"]),
    "fep_ambiguous_totals": (["fep_amount_review"], ["fep_provider_assignment"]),
    "fep_only_estimate": (["fep_amount_review"], ["fep_provider_assignment"]),
    "fep_bank_and_assignment": (["fep_payee_review"], ["fep_stated_total_agrees"]),
    "fep_mixed": (["fep_payee_review"], ["fep_stated_total_agrees"]),
    "fep_two_choices": (["fep_payee_review"], ["fep_stated_total_agrees"]),
    "fep_handwriting": (["fep_form_visual_review"], []),
    "fep_rotated": (["fep_form_visual_review"], []),
    "fep_two_editions": (["fep_form_version_review"], []),
    "fep_placeholder": (["fep_payee_review"], ["fep_stated_total_agrees"]),
    "fep_wrong_member": (["fep_member_payer_review"], []),
    "fep_no_general_signature": (
        ["fep_general_signature"],
        ["fep_provider_assignment", "fep_stated_total_agrees"],
    ),
    "fep_no_assignment_signature": (
        ["fep_assignment_signature"],
        ["fep_stated_total_agrees"],
    ),
    "cms_no_named_member": (
        [],
        ["cms_initial_claim_type", "cms_disposition_agrees", "cms_stated_total_agrees"],
    ),
    "cms_competing_dispositions": (
        [],
        ["cms_insured_id_agrees", "cms_initial_claim_type", "cms_stated_total_agrees"],
    ),
    "cms_pending_reference": (
        ["cms_original_reference_review"],
        ["cms_insured_id_agrees", "cms_disposition_agrees", "cms_stated_total_agrees"],
    ),
    "fep_repeat_total": (["fep_amount_review"], ["fep_provider_assignment"]),
}


class USPayerFields(TestCase):
    def screen(self, scenario, blanks=None):
        meta, docs = unfamiliar_case(scenario, blanks)
        review = Review()
        screen_us(meta, CaseOriginals(docs), review)
        for row in [*review.findings.values(), *review.checks]:
            self.assertTrue(row["sources"], row)
            for ref in row["sources"]:
                self.assertTrue(ref["quote"], (scenario, row))
                self.assertIn(ref["role"], docs)
        return review

    def setUp(self):
        # The unit canvases have no painted background paths. The real PDF run below uses the actual hashes.
        self.register = patch.dict(
            ARTWORK, dict.fromkeys(("cms", "fep"), sha256(b"").hexdigest())
        )
        self.register.start()
        self.addCleanup(self.register.stop)

    def check_variants(self, blanks=None):
        for name, (warnings, facts) in EXPECTED.items():
            with self.subTest(scenario=name):
                result = self.screen(name, blanks)
                self.assertEqual(set(result.findings), set(warnings))
                self.assertEqual({c["code"] for c in result.checks}, set(facts))
                if name == "cms_baseline":
                    proof = {
                        c["code"]: [
                            (r["role"], r["page"], r["quote"]) for r in c["sources"]
                        ]
                        for c in result.checks
                    }
                    self.assertIn(
                        ("summary", 1, "Member R37910182"),
                        proof["cms_insured_id_agrees"],
                    )
                    self.assertIn(
                        ("bill", 3, "Invoice total: USD 7,020.64"),
                        proof["cms_stated_total_agrees"],
                    )
                    self.assertTrue(
                        any(
                            role == "summary" and "transfer" in text
                            for role, _, text in proof["cms_disposition_agrees"]
                        )
                    )
                if name == "cms_dcn_present":
                    proof = next(
                        c
                        for c in result.checks
                        if c["code"] == "cms_original_reference_present"
                    )
                    self.assertIn("154209993", [r["quote"] for r in proof["sources"]])
                if name in {"fep_escrow", "fep_physician_group"}:
                    refs = result.findings["fep_assignment_provider"]["sources"]
                    self.assertEqual(
                        [(r["role"], r["page"]) for r in refs],
                        [("records", 2), ("summary", 1)],
                    )
                    self.assertEqual(
                        refs[0]["quote"],
                        "Rainier Hospital Escrow"
                        if name == "fep_escrow"
                        else "Summit Physician Partners",
                    )
                    self.assertEqual(refs[1]["quote"], "Facility: Twin Fir Clinic")
                if name in {"cms_fraction", "fep_fraction"}:
                    finding = next(iter(result.findings.values()))
                    if name == "cms_fraction":
                        self.assertEqual(
                            [r["quote"] for r in finding["sources"][:2]], ["7020", "63"]
                        )
                    self.assertIn("7,020.63", finding["message"])
                    self.assertIn("7,020.64", finding["message"])
                    self.assertEqual(
                        [s["page"] for s in finding["sources"]],
                        [2, 2, 3] if name.startswith("cms") else [2, 1],
                    )

    def test_independent_cases_on_ci_canvases(self):
        self.check_variants()

    def test_independent_cases_on_local_publisher_forms(self):
        self.register.stop()
        cache = Path(__file__).resolve().parents[1] / ".local/us-payer"
        if not all((cache / name).is_file() for name in ("official.zip", "fep.pdf")):
            self.skipTest(
                "Populate the two pinned source forms with bench/us_payer_forms.py to run the publisher-paper variants."
            )
        with ZipFile(cache / "official.zip") as pkg:
            cms = pkg.read("CMS-1450 UB04-front.pdf")
        self.check_variants({"cms": cms, "fep": (cache / "fep.pdf").read_bytes()})
