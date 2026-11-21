"""Export the US experiment's predictions, page references and timings without source text."""

import argparse
import json
from pathlib import Path

from us_field_verifier import INSTRUCTIONS
from us_policy_accuracy import GOLD, MODEL, digest


def field_values(fields):
    return {field["key"]: field["value"] for field in fields}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    scored = json.loads((args.run_dir / "reviewed-scores.json").read_text())
    if scored["suite_sha256"] != digest(GOLD.read_text()):
        parser.error("Mismatched US question suite")
    field_dir = args.run_dir / ("field-verifier-" + digest(INSTRUCTIONS + MODEL)[:12])
    rows = {}
    for cell in scored["cells"]:
        key = (cell["id"], cell["lang"])
        row = rows.setdefault(key, {"id": key[0], "language": key[1]})
        if cell["arm"] in row:
            raise ValueError("Duplicate experiment arm")
        row[cell["arm"]] = {
            "model": cell["model"],
            "answerable": cell["output"]["answerable"],
            "values": field_values(cell["output"]["fields"]),
            "cited_pages": cell["scores"]["cited"],
            "page_rubric_pass": cell["scores"]["supported"],
            "seconds": round(cell["seconds"], 3),
        }
        if cell["arm"] == "rag":
            row["retrieved_pages"] = cell["selected"]
    for (scenario, lang), row in rows.items():
        check = json.loads((field_dir / f"{scenario}-{lang}.json").read_text())
        if (
            set(row) != {"id", "language", "full", "rag", "retrieved_pages"}
            or check["status"] != "completed"
        ):
            raise ValueError("Incomplete experiment arms")
        fields = check["output"]["fields"]
        row["verifier"] = {
            "model": check["model"],
            "values": field_values(fields),
            "cited_pages_by_field": {
                f["key"]: sorted({c["page"] for c in f["citations"]}) for f in fields
            },
            "seconds": round(check["seconds"], 3),
        }
    report = {
        "suite_sha256": scored["suite_sha256"],
        "run_id": args.run_dir.name,
        "cells": [rows[key] for key in sorted(rows)],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
