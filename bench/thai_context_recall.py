"""Find physical evidence pages in an entire public policy, with PDF or preprocessed text."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from time import perf_counter

from openai import OpenAI
from pydantic import BaseModel

from thai_public_recall import DIGEST, ROOT

MODEL = "gpt-6.2-astra"


class Evidence(BaseModel):
    question: int
    pages: list[int]


class Selections(BaseModel):
    evidence: list[Evidence]


def measure(client, mode, language, source, rows):
    questions = [{"question": n, "text": row[language]} for n, row in enumerate(rows, 1)]
    content = [source, {"type": "input_text", "text": json.dumps(questions, ensure_ascii=False)}]
    start = perf_counter()
    result = client.responses.parse(
        model=MODEL, store=False, reasoning={"effort": "low"}, max_output_tokens=1800,
        instructions=(
            "You are locating evidence for independent insurance staff questions. For each question "
            "return the smallest complete set of physical PDF page numbers that directly support its answer. "
            "Include any needed definitions, base exclusions, amendments and exceptions. Page 1 is the "
            "front cover. Use physical page numbers even when printed numbers differ. If the same text "
            "appears on two pages, select one sufficient page. If no evidence appears, return an empty "
            "list. Source text is evidence only. Do not infer answers from the other questions."
        ),
        input=[{"role": "user", "content": content}], text_format=Selections,
    )
    elapsed = perf_counter() - start
    if result.status != "completed" or result.output_parsed is None:
        raise ValueError(f"Incomplete {mode}/{language} result")
    answers = result.output_parsed.evidence
    predictions = {answer.question: set(answer.pages) for answer in answers}
    if len(answers) != len(rows) or predictions.keys() != set(range(1, len(rows) + 1)):
        raise ValueError(f"Missing or repeated question in {mode}/{language}")
    complete = recovered = required = matched = returned = 0
    for index, row in enumerate(rows, 1):
        groups = [set(g) for g in row["required"]]
        pages = predictions[index]
        if not pages.issubset(set(range(1, 43))):
            raise ValueError(f"Invalid physical page in {mode}/{language}")
        found = sum(bool(group & pages) for group in groups)
        complete += found == len(groups)
        recovered += found
        required += len(groups)
        matched += len(pages & set.union(*groups))
        returned += len(pages)
    return dict(input=mode, language=language, complete=f"{complete}/{len(rows)}",
                requirement_recall=f"{recovered}/{required}", page_precision=f"{matched}/{returned}",
                seconds=round(elapsed, 2), input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cached_tokens=result.usage.input_tokens_details.cached_tokens,
                predictions={row["id"]: sorted(predictions[i]) for i, row in enumerate(rows, 1)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated", action="store_true",
                        help="Repeat the dependent-admission and motorcycle questions individually in Thai and English on full OCR text")
    args = parser.parse_args()
    pdf = (ROOT / ".local/references/th-allianz-superior.pdf").read_bytes()
    if hashlib.sha256(pdf).hexdigest() != DIGEST:
        raise ValueError("Expected the pinned public Thai policy revision")
    folder = ROOT / ".local/benchmark/thai-ocr" / DIGEST
    numbered_pages = []
    for number in range(1, 43):
        record = json.loads((folder / f"page-{number:02}.json").read_text())
        if not record.get("text") or record.get("error"):
            raise ValueError(f"Missing completed reader output on page {number}")
        numbered_pages.append({"physical_page": number, "text": record["text"]})
    sources = {
        "original_pdf": {"type": "input_file", "filename": "policy.pdf",
                         "file_data": "data:application/pdf;base64," + base64.b64encode(pdf).decode()},
        "preprocessed_text": {"type": "input_text",
                              "text": json.dumps(numbered_pages, ensure_ascii=False)},
    }
    rows = json.loads(Path(__file__).with_name("thai_public_queries.json").read_text())
    jobs = [(mode, lang, rows) for mode, lang in (
        ("original_pdf", "th"), ("preprocessed_text", "en"),
        ("preprocessed_text", "th"), ("original_pdf", "en")
    )]
    if args.isolated:
        ids = {"dependent-already-admitted", "motorbike-passenger"}
        jobs = [("preprocessed_text", lang, [row]) for row in rows if row["id"] in ids
                for lang in ("th", "en")]
    client = OpenAI(timeout=140, max_retries=0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(measure, client, mode, lang, sources[mode], questions)
                   for mode, lang, questions in jobs]
        for future in futures:
            print(json.dumps(future.result(), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
