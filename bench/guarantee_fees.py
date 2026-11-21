"""Run a live, synthetic benchmark of the English and Thai guarantee reader."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import subprocess
from time import perf_counter

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.guarantee_fees import read

CATEGORIES = ("exchange_difference", "bank_fees")
EN_FX = "The insurer bears all exchange-rate differences."
EN_FEE = "The insurer pays all bank transfer fees."
EN_PATIENT_FEE = "The patient pays all bank transfer fees."
TH_FX = "บริษัทประกันภัยรับผิดชอบส่วนต่างอัตราแลกเปลี่ยนทั้งหมด"
TH_FEE = "โรงพยาบาลเป็นผู้ชำระค่าธรรมเนียมการโอนเงินทั้งหมด"
# The distinguishing words must occur in the cited passage. Payer and page alone
# would allow the negated sentence immediately above an affirmative one to pass.
GOLD_PASSAGES = {
    ("exchange_difference", "insurer"): ("insurer bears all exchange-rate differences", TH_FX.removesuffix("ทั้งหมด")),
    ("bank_fees", "insurer"): ("insurer pays all bank transfer fees", "underwriter is liable for all transfer fees",
                             "blue willow ltd shall pay all bank fees"),
    ("bank_fees", "patient"): ("patient pays all bank transfer fees",),
    ("bank_fees", "hospital"): (TH_FEE.removesuffix("ทั้งหมด"),),
    ("exchange_difference", "patient"): ("insured member shall fund all foreign exchange losses",),
}
NEUTRAL = "The insurer guarantees the principal of THB 239,000 for this fictional admission."


@dataclass(frozen=True)
class Example:
    name: str
    pages: tuple[tuple[str, ...], ...]
    # A null payer means staff must review the category and no accepted citation is expected.
    expected: tuple[tuple[str, int] | None, tuple[str, int] | None]
    scan: bool = False


CASES = (
    Example("english_positive", ((NEUTRAL, EN_FX, EN_FEE),), (("insurer", 1), ("insurer", 1))),
    Example("thai_split_pages", ((TH_FX,), (TH_FEE,)), (("insurer", 1), ("hospital", 2))),
    Example("english_silent", ((NEUTRAL, "The patient copayment is zero.", "Please arrange payment in THB."),),
            (None, None)),
    Example("thai_conditional", ((TH_FX, "หากได้รับอนุมัติเพิ่มเติม บริษัทประกันภัยอาจชำระค่าธรรมเนียมการโอนเงิน"),),
            (("insurer", 1), None)),
    Example("negated_without_assignee", ((NEUTRAL, "The patient shall not pay exchange-rate differences.",
            "The hospital shall not bear bank transfer fees. The payer has yet to be agreed."),), (None, None)),
    Example("negation_and_named_payer", ((NEUTRAL, "The insurer does not pay bank transfer fees.",
            EN_PATIENT_FEE), (EN_FX,)), (("insurer", 2), ("patient", 1))),
    Example("conflicting_bank_fee_pages", ((EN_FX, EN_FEE), (EN_PATIENT_FEE,
            "Both schedules apply to the same admission. Neither takes precedence.")), (("insurer", 1), None)),
    Example("defined_english_roles", (("The insured member shall fund all foreign exchange losses.",
            "The underwriter is liable for all transfer fees."),), (("patient", 1), ("insurer", 1))),
    Example("named_insurer_across_pages", (("Blue Willow Ltd is the insurer under this guarantee.", EN_FX),
            ("Blue Willow Ltd shall pay all bank fees.",)), (("insurer", 1), ("insurer", 2))),
    Example("thai_image_scan", ((TH_FX, TH_FEE),), (("insurer", 1), ("hospital", 1)), scan=True),
)


def render(case):
    stream = BytesIO()
    out = Canvas(stream, pagesize=A4, invariant=True)
    out.setTitle("Fictional payment guarantee")
    for i, lines in enumerate(case.pages, 1):
        out.setFont("Helvetica-Bold", 20)
        out.drawString(42, 765, "Fictional payment guarantee")
        out.setFont("Helvetica", 10)
        out.drawString(42, 739, f"Demonstration insurer | Settlement terms | Page {i} of {len(case.pages)}")
        y = 681
        for line in lines:
            font = "FeeBenchThai" if re.search(r"[\u0e00-\u0e7f]", line) else "Helvetica"
            size = 13 if font == "FeeBenchThai" else 11
            out.setFont(font, size)
            if pdfmetrics.stringWidth(line, font, size) > A4[0] - 84:
                raise ValueError(f"Benchmark line exceeds the page width in {case.name}")
            out.drawString(42, y, line)
            y -= 33
        out.showPage()
    out.save()
    if not case.scan:
        return stream.getvalue()
    with TemporaryDirectory() as folder:
        source = Path(folder) / "original.pdf"
        source.write_bytes(stream.getvalue())
        png = Path(folder) / "scan"
        subprocess.run(["pdftoppm", "-r", "170", "-singlefile", "-png", str(source), str(png)], check=True)
        scanned = BytesIO()
        out = Canvas(scanned, pagesize=A4, invariant=True)
        out.drawImage(ImageReader(png.with_suffix(".png")), 0, 0, *A4)
        out.save()
        assert not PdfReader(BytesIO(scanned.getvalue())).pages[0].extract_text().strip()
        return scanned.getvalue()


def evaluate(case, document):
    started = perf_counter()
    try:
        result = read(document)
    except Exception as error:
        return {"case": case.name, "status": "error", "error_type": type(error).__name__,
                "http_status": getattr(error, "status_code", None), "passed": False, "categories": {}}
    expected_status = "cited" if all(case.expected) else "needs_review"
    found = {f["category"]: f for f in result["findings"]}
    details = {}
    for category, target in zip(CATEGORIES, case.expected):
        finding = found.get(category)
        observed = (finding["payer"], finding["page"]) if finding else None
        supported = None
        if target and finding:
            words = " ".join(finding["quote"].casefold().split())
            supported = any(fragment in words for fragment in GOLD_PASSAGES[category, target[0]])
        definition_supported = None
        if case.name == "named_insurer_across_pages" and category == "bank_fees":
            link = (finding or {}).get("definition") or {}
            definition_supported = (link.get("page") == 1 and link.get("name", "").casefold() == "blue willow ltd"
                                    and "blue willow ltd is the insurer" in link.get("quote", "").casefold())
        details[category] = {"expected": target, "observed": observed, "cites_expected_clause": supported,
                             "passed": observed == target and (target is None or supported is True)
                                       and definition_supported is not False}
        if definition_supported is not None:
            details[category]["cites_expected_role_definition"] = definition_supported
    return {"case": case.name, "status": result["status"], "expected_status": expected_status,
            "passed": result["status"] == expected_status and all(d["passed"] for d in details.values()),
            "categories": details, "seconds": round(perf_counter() - started, 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send the synthetic documents to the configured models")
    parser.add_argument("--case", action="append", choices=[c.name for c in CASES], help="Run one or more cases")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, help="Write aggregate results and scored categories without raw model output")
    parser.add_argument("--exhibits", type=Path, help="Save the synthetic PDFs for visual inspection")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    pdfmetrics.registerFont(TTFont("FeeBenchThai", ROOT / "app/fonts/NotoSansThai-Regular.ttf"))
    selected = [case for case in CASES if not args.case or case.name in args.case]
    docs = {case.name: render(case) for case in selected}
    if args.exhibits:
        args.exhibits.mkdir(parents=True, exist_ok=True)
        for name, contents in docs.items():
            (args.exhibits / (name + ".pdf")).write_bytes(contents)
    if not args.live:
        print(f"Rendered {len(docs)} synthetic PDFs. Use --live to score the configured reader.")
        return
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY to run the live benchmark")
    if any(c.scan for c in selected) and os.getenv("WORKSPACE_ENABLE_OCR") != "1":
        parser.error("Set WORKSPACE_ENABLE_OCR=1 to include the synthetic scan")
    start = perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(evaluate, case, docs[case.name]) for case in selected]
        results = []
        for job in as_completed(jobs):
            row = job.result()
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    results.sort(key=lambda row: row["case"])
    summary = {"model": os.getenv("OPENAI_MODEL") or "gpt-6.2-sol",
               "ocr_model": os.getenv("OPENAI_OCR_MODEL") or "gpt-6.2-astra",
               "cases": len(results), "cases_passed": sum(r["passed"] for r in results),
               "categories": len(results) * 2,
               "categories_passed": sum(c["passed"] for r in results for c in r["categories"].values()),
               "elapsed_seconds": round(perf_counter() - start, 2), "workers": args.workers, "results": results}
    if args.out:
        args.out.parent.mkdir(exist_ok=True, parents=True)
        args.out.write_text(json.dumps(summary, indent=2) + "\n")
    print(f'{summary["cases_passed"]}/{summary["cases"]} cases; {summary["categories_passed"]}/{summary["categories"]} fee categories.')
    if not all(r["passed"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
