"""Compare digital and image-only versions of the committed fictional discharge summary via loopback HTTP."""
import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from workspace_http import ROOT, server, temporary_database
sys.path.insert(0, str(ROOT))
from app.discharge_claim import load_discharge_fixture


def raster_summary(original):
    with TemporaryDirectory() as directory:
        source = Path(directory) / "synthetic-summary.pdf"
        source.write_bytes(original)
        prefix = str(Path(directory) / "page")
        subprocess.run(["pdftoppm", "-q", "-gray", "-png", "-r", "180", str(source), prefix], check=True)
        stream = BytesIO()
        c = Canvas(stream, pagesize=A4, invariant=1)
        c.setTitle("Image-only fictional discharge summary")
        for name in sorted(Path(directory).glob("page-*.png")):
            c.drawImage(ImageReader(str(name)), 0, 0, width=A4[0], height=A4[1])
            c.showPage()
        c.save()
    result = stream.getvalue()
    pdf = PdfReader(BytesIO(result))
    assert len(pdf.pages) == 2 and all(page.images.keys() and not page.extract_text().strip() for page in pdf.pages)
    return result


def blank_last_page(original):
    result = PdfWriter()
    result.add_page(PdfReader(BytesIO(original)).pages[0])
    result.add_blank_page(*A4)
    stream = BytesIO()
    result.write(stream)
    return stream.getvalue()


def post(client, label, metadata, originals, names, summary, live):
    files = {role: (names[role], summary if role == "summary" else data, "application/pdf") for role, data in originals.items()}
    form = {key: value for key, value in metadata.items() if key != "id"}
    form.update(confirmed="true", ocr=str(live).lower())
    start = perf_counter()
    response = client.post("/api/discharge", data=form, files=files, timeout=240)
    elapsed = perf_counter() - start
    if response.status_code != 201:
        raise RuntimeError(f"{label}: HTTP {response.status_code} ({response.json().get('detail')})")
    case = response.json()
    source = next(s for s in case["sources"] if s["role"] == "summary")
    assert client.get(source["url"]).content == summary
    wanted = {"procedure": "Performed procedure: Wrist fracture fixation", "admission": "Admission date: 2026-12-11",
              "discharge": "Discharge date: 2026-12-13", "signoff": "Summary status: Signed final"}
    exact = {name: [{"page": a["page"], "method": a["method"]} for a in source["anchors"] if a["quote"] == quote]
             for name, quote in wanted.items()}
    result = {"input": label, "seconds": round(elapsed, 3), "http_status": response.status_code,
              "case_status": case["status"], "payable_minor": case["payable_minor"],
              "findings": [f["code"] for f in case["findings"]], "exact_source_fields": exact,
              "unreadable_summary_pages": sorted({r["page"] for f in case["findings"] if f["code"] == "unreadable_summary"
                                                   for r in f["sources"]})}
    print(json.dumps(result, ensure_ascii=False), flush=True)
    assert case["payable_minor"] is None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow Astra to receive synthetic summary pages only.")
    args = parser.parse_args()
    if args.live and not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set the project OpenAI key before enabling live OCR.")
    meta, originals, names = load_discharge_fixture("aligned")
    original = originals["summary"]
    raster = raster_summary(original)
    with temporary_database() as dsn, server(dsn, args.live) as client:
        digital = post(client, "digital", meta, originals, names, original, False)
        offline = post(client, "raster_cloud_off", meta, originals, names, raster, False)
        assert digital["case_status"] == "ready_for_review" and all(digital["exact_source_fields"].values())
        assert offline["case_status"] == "needs_review" and offline["unreadable_summary_pages"] == [1, 2]
        if args.live:
            scan = post(client, "raster_astra", meta, originals, names, raster, True)
            partial = post(client, "blank_second_page_astra", meta, originals, names, blank_last_page(original), True)
            assert scan["case_status"] == partial["case_status"] == "needs_review"
            expected_pages = {"procedure": 1, "admission": 1, "discharge": 1, "signoff": 2}
            assert all(scan["exact_source_fields"][key] == [{"page": number, "method": "ocr"}]
                       for key, number in expected_pages.items()), scan
            assert partial["unreadable_summary_pages"] == [2]


if __name__ == "__main__":
    main()
