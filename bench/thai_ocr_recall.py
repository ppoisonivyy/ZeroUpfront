"""Run the project reader on all physical pages of the pinned public Thai policy, then score retrieval."""
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
from types import SimpleNamespace

from openai import APIError, OpenAI
from pypdf import PdfReader

from thai_public_recall import DIGEST, ROOT, compare

sys.path.insert(0, str(ROOT / "app"))
from document_text import read_document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=ROOT / ".local/references/th-allianz-superior.pdf")
    parser.add_argument("--budget", type=float, default=4.0, help="Maximum estimated additional USD for this run")
    parser.add_argument("--retry", action="store_true", help="Retry saved failed transcriptions once")
    args = parser.parse_args()
    if hashlib.sha256(args.pdf.read_bytes()).hexdigest() != DIGEST:
        parser.error("The benchmark requires the published policy edition with the pinned digest")
    if (os.getenv("OPENAI_OCR_MODEL") or "gpt-6.2-astra") != "gpt-6.2-astra":
        parser.error("This budget and benchmark require gpt-6.2-astra")
    directory = ROOT / ".local/benchmark/thai-ocr" / DIGEST
    directory.mkdir(parents=True, exist_ok=True)
    if args.budget < 0.01:
        parser.error("Reserve at least one cent for the final embedding comparison")
    parameters = {
        "pdf_sha256": DIGEST,
        "reader_sha256": hashlib.sha256((ROOT / "app/document_text.py").read_bytes()).hexdigest(),
        "ocr_model": "gpt-6.2-astra",
        "max_output_tokens": 2900,
        "embedding_model": "text-embedding-3-large",
    }
    manifest = directory / "parameters.json"
    if manifest.exists() and json.loads(manifest.read_text()) != parameters:
        parser.error("Cached reader parameters differ. Move the old cache before repeating the experiment.")
    manifest.write_text(json.dumps(parameters, indent=2) + "\n")
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    client = OpenAI(timeout=75, max_retries=0)
    reader = PdfReader(args.pdf)
    page_count = len(reader.pages)
    if page_count != 42:
        parser.error("Expected 42 physical pages")

    def path(n):
        return directory / f"page-{n:02}.json"

    def extract(n):
        usage = [0, 0]

        def parse(**kwargs):
            response = client.responses.parse(max_output_tokens=2900, **kwargs)
            usage[:] = [response.usage.input_tokens, response.usage.output_tokens]
            return response

        try:
            one = read_document(args.pdf, SimpleNamespace(responses=SimpleNamespace(parse=parse)), page_number=n)
            p = one.pages[0]
            info = {"method": "astra" if p.ocr is not None else "native", "text": p.text}
        except (APIError, ValueError) as exc:
            status = getattr(exc, "status_code", None)
            info = {"error": type(exc).__name__, "reason": str(exc) if isinstance(exc, ValueError) else status}
        info["input_tokens"], info["output_tokens"] = usage
        if path(n).exists():
            previous = json.loads(path(n).read_text())
            info["prior_attempts"] = previous.get("prior_attempts", []) + [
                {key: previous[key] for key in ("error", "reason", "input_tokens", "output_tokens") if key in previous}
            ]
        temp = path(n).with_suffix(".tmp")
        temp.write_text(json.dumps(info, ensure_ascii=False))
        temp.replace(path(n))
        return info

    todo = [i for i in range(1, page_count + 1) if not path(i).exists() or
            (args.retry and "error" in json.loads(path(i).read_text()))]
    spend = 0.0
    # Reserve 2,900 output tokens and up to 8,000 input tokens per PDF page at the standard Astra price.
    # Unknown usage after a transport error consumes the full reservation. Reserve one cent for scoring.
    reserve = (2900 * 40 + 8000 * 8) / 1_000_000
    with ThreadPoolExecutor(max_workers=5) as pool:
        active = {}
        while todo or active:
            while todo and len(active) < 5 and spend + (len(active) + 1) * reserve + 0.01 <= args.budget:
                n = todo.pop(0)
                active[pool.submit(extract, n)] = n
            if not active:
                break
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for job in done:
                n = active.pop(job)
                info = job.result()
                estimate = (8 * info["input_tokens"] + 40 * info["output_tokens"]) / 1_000_000
                if info.get("error") and not info["input_tokens"]:
                    estimate = reserve
                spend += estimate
                print(f"page {n} {info.get('method') or info.get('reason')} project cost estimate {spend:.3f}", flush=True)

    outcomes = {n: json.loads(path(n).read_text()) for n in range(1, page_count + 1) if path(n).exists()}
    failures = [n for n, info in outcomes.items() if "error" in info]
    ready = sum("text" in info for info in outcomes.values())
    print(f"Reader accepted {ready}/{page_count}. Declined/errors {failures}. Pending {todo}.")
    if ready != page_count:
        print("Exact reader halted. For a diagnostic across all 42 candidates, use native text on unsuccessful pages.")
    pages = [outcomes.get(n, {}).get("text") or " ".join(reader.pages[n - 1].extract_text().split())
             for n in range(1, page_count + 1)]
    if not all(pages):
        raise ValueError("Missing candidate text")
    rows = json.loads(Path(__file__).with_name("thai_public_queries.json").read_text())
    compare(client, "text-embedding-3-large", pages, rows)


if __name__ == "__main__":
    main()
