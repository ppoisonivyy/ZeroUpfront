"""Grade saved outputs of the paired discharge comparison without making a model call."""
from argparse import ArgumentParser
import json
from pathlib import Path
from statistics import median

from payer_ai_challenge import TARGET
from payer_ai_review import ROOT, CASES, expected
from payer_ai_stress import SPECS


def grade_fields(result, gold):
    by_field = {}
    for check in result["checks"]:
        by_field.setdefault(check["field"], []).append(check)
    scored = {}
    for field, (state, required_pages) in gold.items():
        responses = by_field.get(field, [])
        item = responses[0] if len(responses) == 1 else {}
        actual = {(p["role"], p["page"]) for p in item.get("pages", [])}
        valid_pages = all(1 <= n <= result["manifest"].get(role, 0) for role, n in actual)
        correct = item.get("state", "").strip().lower() == state
        scored[field] = {"state": item.get("state"), "expected": state, "correct": correct,
                         "page_check": correct and valid_pages and required_pages <= actual,
                         "observation": item.get("observation"), "pages": sorted(f"{r}:{n}" for r, n in actual)}
    return scored


def holdout_gold(spec):
    name, family = spec["id"], spec["family"]
    aligned = {"aia-en": "en-aligned", "aia-th": "th-aligned", "cms": "cms_aligned", "fep": "fep_assigned"}[family]
    gold = expected(aligned, family.split("-")[0])
    if "need" in spec:
        field, state = TARGET[spec["need"]]
        gold[field] = (state, gold[field][1] | {(spec["role"], spec["page"])})
    if name == "cms-reference-present":
        gold["replacement"] = ("present", {("bill", 1)})
    return gold


def run_suite(name, directory, specs):
    arms = {}
    for mode in ("single", "agent"):
        records = []
        for case, gold in specs.items():
            r = json.loads((directory / f"{case}.{mode}.json").read_text())
            records.append({"case": case, "model": r["model"], "seconds": r["seconds"], "tool_calls": len(r["trace"]),
                            "input_tokens": r["input_tokens"], "cached_tokens": r["cached_tokens"],
                            "output_tokens": r["output_tokens"], "pdf_digest": r["inputs_sha256"], "inspections": r["trace"],
                            "scores": grade_fields(r, gold)})
        checks = [c for row in records for c in row["scores"].values()]
        arms[mode] = {"packets": len(records), "scored_fields": len(checks),
                      "states_correct": sum(c["correct"] for c in checks),
                      "states_and_required_pages": sum(c["page_check"] for c in checks),
                      "median_seconds": round(median(r["seconds"] for r in records), 2),
                      "tool_calls": sum(r["tool_calls"] for r in records),
                      "input_tokens": sum(r["input_tokens"] for r in records),
                      "output_tokens": sum(r["output_tokens"] for r in records), "observations": records}
    if [r["pdf_digest"] for r in arms["single"]["observations"]] != [r["pdf_digest"] for r in arms["agent"]["observations"]]:
        raise ValueError(f"PDFs differ between methods in {name}.")
    return arms


def main():
    p = ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=ROOT / ".local/payer-ai-comparison.json")
    args = p.parse_args()
    holdouts = json.loads((ROOT / "bench/payer_challenge_cases/gold.json").read_text())["cases"]
    stress_pages = {"contradictory-payees": {("records", 1), ("records", 3)},
                    "image-only-claimed-expense": {("records", 2), ("bill", 1)}}
    suites = {
        "original": ("payer-ai-required", {case: expected(case, family) for case, (family, _) in CASES.items()}),
        "holdout": ("payer-ai-holdout", {s["id"]: holdout_gold(s) for s in holdouts}),
        "stress": ("payer-ai-stress", {case: {field: (state, stress_pages.get(case, set())) for field, state in targets.items()}
                                    for case, (_, _, targets) in SPECS.items()}),
    }
    report = {suite: run_suite(suite, ROOT / ".local" / folder, specs) for suite, (folder, specs) in suites.items()}
    args.output.parent.mkdir(exist_ok=True, parents=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for suite, arms in report.items():
        for mode, result in arms.items():
            print(suite, mode, {k: v for k, v in result.items() if k != "observations"})


if __name__ == "__main__":
    main()
