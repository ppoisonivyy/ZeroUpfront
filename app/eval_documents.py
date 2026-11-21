"""Evaluate retrieval page recall and the supplied, separate post-extraction text task."""
import argparse
import json
import os
from pathlib import Path

from openai import OpenAI
from policy_rag import ROOT, passages, retrieve
from document_text import read_document
from sample_schemas import Billing, MedicalRecord, GuaranteeRequest


def samples(folder, client):
    seen = set()
    exact_fields = field_count = 0
    for split in ("train", "eval"):
        rows = [json.loads(line)["messages"] for line in (folder/f"{split}.jsonl").read_text().splitlines() if line.strip()]
        for messages in rows:
            if [m["role"] for m in messages] != ["system","user","assistant"]:
                raise ValueError("Unexpected message order")
            case = json.loads(messages[1]["content"])["case"]
            if case in seen:
                raise ValueError(f"Overlapping example: {case}")
            seen.add(case)
            expected = json.loads(messages[2]["content"])
            if split == "eval" and client:
                family = case.removeprefix("SIM-")[0]
                schema = {"B": Billing, "M": MedicalRecord, "G": GuaranteeRequest}[family]
                response = client.responses.parse(model=os.getenv("OPENAI_MODEL") or "gpt-6.2-sol",
                    input=messages[:2], store=False, text_format=schema)
                field_count += len(expected)
                if response.status != "completed" or response.output_parsed is None:
                    print(case, "incomplete response")
                    continue
                actual = response.output_parsed.model_dump()
                fields = [k for k,v in expected.items() if k in actual and actual[k] == v]
                exact_fields += len(fields)
                print(f"{case} exact top-level fields {len(fields)}/{len(expected)}; "
                      f"review {sorted(set(expected)-set(fields))}")
        print(split, len(rows), "distinct labeled rows validated")
    if client:
        print(f"Exact field matches {exact_fields}/{field_count} (strict wording and list ordering).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, help="Supplied folder with train.jsonl and eval.jsonl")
    parser.add_argument("--live", action="store_true", help="Evaluate live hybrid retrieval or held-out sample outputs")
    parser.add_argument("--require-complete", action="store_true", help="Fail if a labeled question lacks an expected source page")
    args = parser.parse_args()
    if args.live and not os.getenv("OPENAI_API_KEY"):
        parser.error("Configure OPENAI_API_KEY in .env")
    client = OpenAI(timeout=100,max_retries=1) if args.live else None
    if args.samples:
        samples(args.samples,client)
        return
    pack = ROOT/"fixtures"/"complex"
    matched = total = complete = 0
    tasks = json.loads((pack/"expected.json").read_text())
    for task in tasks:
        # Only the question and the selected policy enter the retriever.
        doc = read_document(pack/(task["pack"]+"-policy.pdf"),client)
        hits = retrieve(task["question"],passages(doc,"P"),client)
        retrieved = [hit.page for hit in hits]
        gold = set(task["pages"])
        matched += len(gold.intersection(retrieved))
        total += len(gold)
        complete += int(gold.issubset(retrieved))
        print(task["pack"],"retrieved",retrieved,"expected",sorted(gold))
    print(f"Page recall@4 {matched}/{total}. Complete evidence sets {complete}/{len(tasks)}.")
    if args.require_complete and complete != len(tasks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
