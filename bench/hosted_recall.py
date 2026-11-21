"""Measure page recall and latency for OpenAI search on paired staff questions."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from cloud_policy import cloud_retrieve, hosted_candidates
from document_text import read_document
from policy_rag import PACKS, passages


@dataclass
class Result:
    method: str
    language: str
    query_id: str
    required: set[int]
    pages: list[int]
    seconds: float


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare", action="store_true",
                        help="Also score hosted search with its ranker disabled and enabled")
    args = parser.parse_args()
    client = OpenAI(timeout=60, max_retries=1)
    queries = json.loads((ROOT / "bench/bilingual_queries.json").read_text())["queries"]
    editions = {
        pack: passages(read_document(ROOT / f"fixtures/complex/{pack}-policy.pdf"), "P")
        for pack in PACKS
    }
    methods = ["none", "auto", "demo"] if args.compare else ["demo"]

    def score(job):
        method, query, language = job
        pack = query["pack"]
        search_args = (client, query[language], PACKS[pack][1], editions[pack])
        start = perf_counter()
        if method == "demo":
            hits = cloud_retrieve(*search_args)
        else:
            hits = hosted_candidates(*search_args, ranker=method)[:4]
        return Result(method, language, query["id"], set(query["pages"]),
                      [p.page for p in hits], perf_counter() - start)

    # Rotate method order so each appears early and late across queries.
    jobs = [(method, q, lang) for i, q in enumerate(queries) for lang in ("en", "th")
            for method in methods[i % len(methods):] + methods[:i % len(methods)]]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(score, jobs))
    for method in methods:
        for lang in ("en", "th"):
            split = [r for r in rows if r.method == method and r.language == lang]
            missed = [r.query_id for r in split if not r.required.issubset(r.pages)]
            found = sum(len(r.required.intersection(r.pages)) for r in split)
            count = sum(len(r.required) for r in split)
            first = sum(bool(r.pages and r.pages[0] in r.required) for r in split)
            seconds = median(r.seconds for r in split)
            print(f"{method} {lang} complete {len(split)-len(missed)}/{len(split)} "
                  f"page recall {found}/{count} top-1 {first}/{len(split)} "
                  f"median {seconds:.2f}s incomplete {missed}")


if __name__ == "__main__":
    main()
