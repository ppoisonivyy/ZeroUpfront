"""Blind-value field and safety holdout against the normal discharge HTTP API."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from time import perf_counter

from pypdf import PdfReader
from workspace_http import ROOT, server, temporary_database
from payer_challenge_cases import packets
from payer_forms_us.specimens import get_blanks

MANIFEST = ROOT / "bench/payer_challenge_cases/gold.json"
EXPECTED_DIGEST = "01180c15d91602f24d4fc3e2ebf82c16d891b0f669483bf7ddada784dd3002ce"


def cases():
    if sha256(MANIFEST.read_bytes()).hexdigest() != EXPECTED_DIGEST:
        raise ValueError("The frozen challenge manifest digest has changed.")
    return json.loads(MANIFEST.read_text())["cases"]


def prepare(out):
    blanks = get_blanks(ROOT / ".local/us-payer")
    prepared = []
    for spec in cases():
        if spec["family"].startswith("aia"):
            meta, docs = packets.thai(spec)
        elif spec["family"] == "cms":
            meta, docs = packets.cms(spec, blanks)
        else:
            meta, docs = packets.fep(spec, blanks)
        folder = out / "fixtures" / spec["id"]
        folder.mkdir(parents=True, exist_ok=True)
        for role, raw in docs.items():
            (folder / (role + ".pdf")).write_bytes(raw)
        (folder / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
        prepared.append((spec, meta, docs))
    return prepared


def evaluate(client, item):
    spec, meta, docs = item
    start = perf_counter()
    response = client.post("/api/discharge", data={**meta, "confirmed": "true", "ocr": "false"},
                           files={r: (r + ".pdf", b, "application/pdf") for r, b in docs.items()})
    intake_ms = round((perf_counter() - start) * 1000, 1)
    response.raise_for_status()
    case = response.json()
    path = "/api/discharge/" + case["id"]
    serial = client.get(path)
    serial.raise_for_status()
    case = serial.json()
    family = spec["family"].split("-")[0] + "_"
    findings = [f for f in case["findings"] if f["code"].startswith(family)]
    checks = [c for c in case.get("checks", []) if c["code"].startswith(family)]
    pages = {r: len(PdfReader(BytesIO(d)).pages) for r, d in docs.items()}
    sources = case["sources"]
    intact = sorted(s["role"] for s in sources) == sorted(docs)
    if intact:
        for source in sources:
            raw = docs[source["role"]]
            original = client.get(source["url"])
            if source["sha256"] != sha256(raw).hexdigest() or original.status_code != 200 or original.content != raw:
                intact = False
    approve = client.post(path + "/approve", headers={"If-Match": '"1"'}, json={"reviewer": "Synthetic holdout reviewer"})
    export = client.get(path + "/export", params={"revision": 1})
    safety = {"status": case["status"], "payable_minor": case["payable_minor"], "approve_http": approve.status_code,
              "export_http": export.status_code, "allowed_actions": case["allowed_actions"]}
    safe = (case["status"] == "needs_review" and case["payable_minor"] is None
            and approve.status_code == 409 and export.status_code == 409 and not case["allowed_actions"])
    return {"id": spec["id"], "intake_ms": intake_ms, "safe": safe, "safety": safety, "pages": pages,
            "originals_intact": intact,
            "findings": findings, "checks": checks, "all_finding_codes": [f["code"] for f in case["findings"]]}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--out", type=Path, default=ROOT / ".local/payer-challenge")
    source = cli.add_mutually_exclusive_group()
    source.add_argument("--prepare-only", action="store_true", help="Render the frozen cases without calling the application.")
    source.add_argument("--score-observed", type=Path, help="Rescore a saved HTTP observation file without building or uploading PDFs.")
    cli.add_argument("--require-current", action="store_true", help="Apply the current regression gate to saved observations.")
    cli.add_argument("--workers", type=int, default=4)
    args = cli.parse_args()
    if args.workers < 1:
        cli.error("Choose a positive worker count.")
    if args.require_current and not args.score_observed:
        cli.error("--require-current applies only to --score-observed. Live HTTP runs always enforce the gate.")
    from payer_challenge_cases.scoring import regression_failures, score
    if args.score_observed:
        raw = json.loads(args.score_observed.read_text())
        if raw["gold_sha256"] != EXPECTED_DIGEST:
            cli.error("The saved observations use different challenge expectations.")
        observations = raw["observations"]
        args.out.mkdir(parents=True, exist_ok=True)
    else:
        prepared = prepare(args.out)
        if args.prepare_only:
            print(f"Prepared {len(prepared)} synthetic packets in {args.out / 'fixtures'}")
            return
        with temporary_database() as dsn, server(dsn, False) as client, ThreadPoolExecutor(args.workers) as pool:
            observations = list(pool.map(lambda p: evaluate(client, p), prepared))
        raw = {"gold_sha256": EXPECTED_DIGEST, "workers": args.workers, "observations": observations}
        (args.out / "observed.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    try:
        result = score(cases(), observations)
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Invalid HTTP observations: {exc}") from exc
    strict = not args.score_observed or args.require_current
    mode = "live HTTP regression" if not args.score_observed else (
        "saved observations against current gate" if strict else "historical rescore")
    result["mode"] = mode
    if strict:
        failures = regression_failures(result["rows"])
        result["regression_gate"] = {"passed": not failures, "failures": failures}
    (args.out / "scored.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, indent=2))
    if strict and failures:
        raise SystemExit("Payer-form regression gate failed.")


if __name__ == "__main__":
    main()
