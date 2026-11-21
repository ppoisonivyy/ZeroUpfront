"""Score frozen synthetic packets against the current HTTP API."""

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def run_benchmark(output):
    subprocess.run(
        [sys.executable, "bench/payer_challenge.py", "--out", str(output)],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return json.loads((output / "scored.json").read_text())


def main():
    with TemporaryDirectory(prefix="zeroupfront-holdout-") as directory:
        scratch = Path(directory)
        print("Frozen synthetic cases on known AIA, CMS-1450 and FEP forms")
        print("Uploading packets to the current API ...", flush=True)
        current = run_benchmark(scratch / "current")
        scores = current["summary"]
        print(f"Cases evaluated:                  {scores['cases']}")
        print(
            f"Target findings on correct page:  {scores['targets'].get('target-and-page', 0)}/{scores['target_challenges']}"
        )
        print(
            f"Exact printed-value citations:    {scores['printed_values_exact_in_form_citations']}/{scores['printed_value_challenges']}"
        )
        print(
            f"False alerts on aligned fields:   {scores['false_target_alerts']}/{scores['aligned_field_challenges']}"
        )
        print(
            f"Unverified claims held:           {scores['unverified_cases_safely_held']}/{scores['cases']}"
        )
        print(
            f"Regression gate:                  {'PASS' if current['regression_gate']['passed'] else 'FAIL'}"
        )


if __name__ == "__main__":
    main()
