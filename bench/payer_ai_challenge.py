"""Pair both multimodal approaches on the separately authored, frozen-value challenge."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
import os
from pathlib import Path

from payer_ai_review import ROOT, review_case
from app.payer_ai_reader import STAFF_RUBRICS as RUBRICS

FROZEN_DIGEST = "01180c15d91602f24d4fc3e2ebf82c16d891b0f669483bf7ddada784dd3002ce"
# Same rubric for every case in a family. Outcomes and case IDs never enter the model prompt.
TARGET = {"aia-amount": ("expense", "conflict"), "aia-encounter": ("admission", "conflict"),
          "aia-ink": ("consent", "visual_review"), "aia-clinician": ("certification", "absent"),
          "cms-member": ("member", "conflict"), "cms-total": ("expense", "conflict"),
          "cms-identity-unverified": ("member", "absent"), "fep-provider": ("payee", "other_provider"),
          "fep-signature": ("payee", "unsigned"), "fep-total": ("expense", "conflict"),
          "fep-member-route": ("payee", "member")}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true")
    p.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    p.add_argument("--output", type=Path, default=ROOT / ".local/payer-ai-holdout")
    p.add_argument("--prepared", type=Path, default=ROOT / ".local/payer-challenge/fixtures")
    args = p.parse_args()
    manifest = ROOT / "bench/payer_challenge_cases/gold.json"
    if sha256(manifest.read_bytes()).hexdigest() != FROZEN_DIGEST:
        raise ValueError("Frozen manifest changed.")
    specs = json.loads(manifest.read_text())["cases"]
    if not args.live:
        p.exit(0, "Run bench/payer_challenge.py --prepare-only, then use --live for the funded paired evaluation.\n")
    if not all((args.prepared / spec["id"] / "metadata.json").is_file() for spec in specs):
        raise SystemExit("Prepare the holdout PDFs using bench/payer_challenge.py --prepare-only.")
    args.output.mkdir(exist_ok=True, parents=True)
    model = os.getenv("OPENAI_OCR_MODEL") or "gpt-6.2-astra"
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {}
        for spec in specs:
            family = spec["family"].split("-")[0]
            for mode in ("single", "agent"):
                pending[pool.submit(review_case, spec["id"], mode, model, args.output,
                                    family=family, directory=args.prepared / spec["id"], rubric=RUBRICS[family])] = (spec["id"], mode)
        for future in as_completed(pending):
            case, mode = pending[future]
            try:
                r = future.result()
                print(case, mode, r["seconds"], len(r["trace"]), flush=True)
            except Exception as exc:
                print(case, mode, type(exc).__name__, getattr(exc, "status_code", ""), flush=True)
                failures += 1
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
