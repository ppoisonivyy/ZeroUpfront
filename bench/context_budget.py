"""Count representative long-policy requests on Astra without generating a model answer."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import logging
import os
from pathlib import Path
from time import perf_counter

from openai import APIError, OpenAI
from pypdf import PdfReader

from thai_public_recall import DIGEST as THAI_POLICY_DIGEST, ROOT

US_POLICY_DIGEST = "e5b371dbff81c71808da05fb2a4e2bad7b11c39bb3b49fdee1505c043111a7c1"
INSTRUCTIONS = (
    "Prepare an administrative review for a hospital coordinator. Use the supplied policy edition and "
    "case exhibits. Identify any relevant exception and missing evidence. Cite the source document, "
    "physical page and an exact quotation for each material finding. Ask for staff review when the "
    "packet and policy do not establish applicability. Only the insurer issues a guarantee of payment."
)
QUESTION = (
    "Which provisions or exceptions govern the overseas admission, what evidence is missing, "
    "and what should the coordinator verify before requesting direct settlement?"
)
THAI_QUESTION = (
    "Which room and companion charges require staff review before requesting direct settlement, "
    "and what evidence supports that review?"
)


def numbered(name, texts):
    return {"document": name, "pages": [{"page": n, "text": text} for n, text in enumerate(texts, 1)]}


def native_text(path, expected_pages):
    reader = PdfReader(path)
    if len(reader.pages) != expected_pages:
        raise ValueError(f"Unexpected physical page count in {path.name}")
    return numbered(path.name, [" ".join((page.extract_text() or "").split()) for page in reader.pages])


def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def full_request(policy, case, question):
    return {"instructions": INSTRUCTIONS, "input": packed({"policy": policy, "case": case, "question": question})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-thai", action="store_true", help="Also count the previously completed Thai reader cache")
    args = parser.parse_args()
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    path = ROOT / ".local/references/us-opm-2026.pdf"
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != US_POLICY_DIGEST:
        parser.error("The public US policy digest differs from the reviewed edition")
    model = os.getenv("OPENAI_OCR_MODEL") or "gpt-6.2-astra"
    policy = native_text(path, 168)
    encoded = base64.b64encode(data).decode("ascii")
    us_case = native_text(ROOT / "fixtures/complex/us-case.pdf", 5)
    requests = {
        "us_pdf_high": {"input": [{"role": "user", "content": [
            {"type": "input_file", "filename": path.name, "detail": "high",
             "file_data": "data:application/pdf;base64," + encoded}]}]},
        "us_native_text": {"input": packed(policy)},
        "us_staff_request": full_request(policy, us_case, QUESTION),
    }
    if args.include_thai:
        directory = ROOT / ".local/benchmark/thai-ocr" / THAI_POLICY_DIGEST
        parameters = json.loads((directory / "parameters.json").read_text())
        if parameters["pdf_sha256"] != THAI_POLICY_DIGEST:
            parser.error("The Thai policy digest differs from the reviewed edition")
        thai_texts = []
        for n in range(1, 43):
            outcome = json.loads((directory / f"page-{n:02}.json").read_text())
            if outcome.get("method") not in {"native", "astra"} or not outcome.get("text", "").strip():
                parser.error(f"Missing verified reader completion for physical Thai page {n}")
            thai_texts.append(outcome["text"])
        th_policy = numbered("th-allianz-superior.pdf", thai_texts)
        th_case = native_text(ROOT / "fixtures/complex/th-case.pdf", 5)
        requests["th_staff_request"] = full_request(th_policy, th_case, THAI_QUESTION)
    client = OpenAI(timeout=100, max_retries=0)
    print(f"Token counter model {model}", flush=True)

    def count(parameters):
        start = perf_counter()
        result = client.responses.input_tokens.count(model=model, truncation="disabled", **parameters)
        return result.input_tokens, perf_counter() - start

    failures = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(count, params): name for name, params in requests.items()}
        for job in as_completed(jobs):
            name = jobs[job]
            try:
                tokens, seconds = job.result()
                print(f"{name} {tokens:,} input tokens ({seconds:.1f}s)", flush=True)
            except APIError as exc:
                failures.append(name)
                print(f"{name} API failure {exc.status_code if hasattr(exc, 'status_code') else type(exc).__name__}, "
                      f"code {getattr(exc, 'code', None)}", flush=True)
    if failures:
        raise SystemExit(f"Could not count: {', '.join(failures)}")


if __name__ == "__main__":
    main()
