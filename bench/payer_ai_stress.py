"""Challenge paired PDF reviewers with unavailable or contradictory primary evidence."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from PIL import Image
from pypdf import PdfReader, PdfWriter

from payer_ai_challenge import RUBRICS
from payer_ai_review import ROOT, review_case

# Each target was set before calling a model. Both methods see the same four-role manifest.
SPECS = {
    "missing-independent-bill": ("fep", "fep_assigned", {"expense": "unknown"}),
    "missing-invoice-annex": ("cms", "cms_aligned", {"expense": "unknown"}),
    "contradictory-payees": ("fep", "fep_assigned", {"payee": "unknown"}),
    "missing-physician-page": ("aia", "th-aligned", {"admission": "unknown", "certification": "unknown"}),
    "image-only-claimed-expense": ("aia", "th-amount-mismatch", {"expense": "conflict"}),
}


def write_pdf(pages, target):
    pdf = PdfWriter()
    for page in pages:
        pdf.add_page(page)
    with target.open("wb") as dest:
        pdf.write(dest)


def prepare(case, family, base, dest):
    source = ROOT / ".local" / ("th-payer/cases" if family == "aia" else "us-payer/packets") / base
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / ("metadata.json" if family == "aia" else "intake.json"), dest / "metadata.json")
    for role in ("summary", "bill", "letter", "records"):
        path = source / (role + ".pdf")
        if path.exists() and not (case == "missing-independent-bill" and role == "bill"):
            shutil.copyfile(path, dest / path.name)
    if case == "missing-invoice-annex":
        write_pdf(PdfReader(source / "bill.pdf").pages[:2], dest / "bill.pdf")
    elif case == "contradictory-payees":
        assigned = PdfReader(source / "records.pdf").pages
        member = PdfReader(source.parent / "fep_member" / "records.pdf").pages
        write_pdf([*assigned[:2], *member[:2], *assigned[2:]], dest / "records.pdf")
    elif case == "missing-physician-page":
        pages = PdfReader(source / "records.pdf").pages
        write_pdf([*pages[:2], *pages[3:]], dest / "records.pdf")
    elif case == "image-only-claimed-expense":
        with TemporaryDirectory() as td:
            stem = Path(td) / "sheet"
            subprocess.run(["pdftoppm", "-r", "135", "-png", str(source / "records.pdf"), str(stem)],
                           check=True, capture_output=True)
            pages = []
            for image in sorted(stem.parent.glob("sheet-*.png")):
                with Image.open(image) as bitmap:
                    stream = BytesIO()
                    bitmap.convert("RGB").save(stream, format="PDF", resolution=135)
                    pages.append(PdfReader(stream).pages[0])
            write_pdf(pages, dest / "records.pdf")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true")
    p.add_argument("--out", type=Path, default=ROOT / ".local/payer-ai-stress")
    args = p.parse_args()
    for case, (family, base, _) in SPECS.items():
        prepare(case, family, base, args.out / "fixtures" / case)
    if not args.live:
        p.exit(0, "Prepared five synthetic stress packets. Use --live to run the paired model comparison.\n")
    model = os.getenv("OPENAI_OCR_MODEL") or "gpt-6.2-astra"
    errors = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(review_case, case, mode, model, args.out, family=family,
                               directory=args.out / "fixtures" / case, rubric=RUBRICS[family]): (case, mode)
                   for case, (family, _, _) in SPECS.items() for mode in ("single", "agent")}
        for future in as_completed(pending):
            case, mode = pending[future]
            try:
                result = future.result()
                print(case, mode, [(c["field"], c["state"]) for c in result["checks"]
                                   if c["field"] in SPECS[case][2]], flush=True)
            except Exception as exc:
                print(case, mode, type(exc).__name__, getattr(exc, "status_code", ""), flush=True)
                errors.append((case, mode))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
