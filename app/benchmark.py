"""Measure warm end-to-end local pre-check service time with fixed concurrency."""
import argparse
import json
import math
from concurrent.futures import ProcessPoolExecutor
from statistics import median
from time import perf_counter

from check_fixtures import ROOT, evaluate


def batch(count, corpus):
    scenarios = json.loads((ROOT / corpus).read_text())
    rules = json.loads((ROOT / "rulebooks.json").read_text())
    start = perf_counter()
    samples = []
    for index in range(count):
        case = scenarios[index % len(scenarios)]
        tick = perf_counter()
        evidence, status, citation = evaluate(case, rules)
        clause = citation["clause"] if citation else None
        samples.append((perf_counter() - tick) * 1000)
        if (evidence.total_thb, status, clause) != (case["total_thb"], case["result"], case["flag_clause"]):
            raise ValueError(f"Fixture mismatch at {case['case']}")
    return start, perf_counter(), samples


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--cases-per-worker", type=int, default=100)
    args = parser.parse_args()
    corpus = "expected.json"
    size = len(json.loads((ROOT / corpus).read_text()))
    if args.workers < 1 or args.cases_per_worker < size or args.cases_per_worker % size:
        parser.error(f"Use positive workers and a positive multiple of {size} cases per worker")
    corpora = [corpus] * args.workers
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(batch, [size] * args.workers, corpora))
        results = list(pool.map(batch, [args.cases_per_worker] * args.workers, corpora))
    ms = sorted(t for _, _, samples in results for t in samples)
    duration = max(end for _, end, _ in results) - min(start for start, _, _ in results)
    print(json.dumps(dict(workers=args.workers, cases=len(ms), seconds=round(duration, 3),
                          cases_per_second=round(len(ms)/duration, 2), p50_ms=round(median(ms), 2),
                          p95_ms=round(ms[math.ceil(.95*len(ms))-1], 2)), indent=2))
