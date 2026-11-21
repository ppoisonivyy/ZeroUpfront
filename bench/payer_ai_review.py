"""Paired, read-only multimodal review of fictional cases on official payer forms."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from time import perf_counter
import sys

from openai import OpenAI
from PIL import Image
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.payer_ai_reader import INSTRUCTIONS, ROLES, RUBRICS, Review, request_input

# Predeclared targets. Only the benchmark scorer reads the expected states and citation roles/pages.
CASES = {
    "th-aligned": ("aia", None), "en-aligned": ("aia", None),
    "th-wrong-admission": ("aia", ("admission", "conflict")),
    "th-amount-mismatch": ("aia", ("expense", "conflict")),
    "en-unsigned-patient": ("aia", ("consent", "absent")),
    "th-unsigned-physician": ("aia", ("certification", "absent")),
    "en-missing-letter": ("aia", ("letter", "absent")),
    "cms_aligned": ("cms", None), "cms_wrong_member": ("cms", ("member", "conflict")),
    "cms_disposition": ("cms", ("disposition", "conflict")),
    "cms_replacement": ("cms", ("replacement", "absent")), "cms_total": ("cms", ("expense", "conflict")),
    "fep_assigned": ("fep", None), "fep_member": ("fep", ("payee", "member")),
    "fep_unsigned": ("fep", ("payee", "unsigned")), "fep_total": ("fep", ("expense", "conflict")),
}


def expected(case, family):
    if family == "aia":
        a, b = (2, 3) if case.startswith("th-") else (1, 2)
        gold = {"admission": ("match", {("records", b)}), "expense": ("match", {("records", a), ("bill", 1)}),
                "consent": ("present", {("records", a)}), "certification": ("present", {("records", b)}),
                "letter": ("present", {("letter", 1)})}
    elif family == "cms":
        gold = {"member": ("match", {("bill", 1)}), "disposition": ("match", {("bill", 1), ("summary", 1)}),
                "replacement": ("original", {("bill", 1)}), "expense": ("match", {("bill", 1), ("bill", 3)})}
    else:
        gold = {"payee": ("hospital", {("records", 1)}), "expense": ("match", {("records", 1), ("bill", 1)})}
    change = CASES[case][1]
    if change:
        field, state = change
        gold[field] = (state, set() if field == "letter" and state == "absent" else gold[field][1])
    return gold


INSPECT = {"type": "function", "name": "inspect_page", "description": "Inspect one case page or half-page magnified to check box placement or fine print.",
           "parameters": {"type": "object", "properties": {
               "role": {"type": "string", "enum": list(ROLES)}, "page": {"type": "integer"},
               "region": {"type": "string", "enum": ["full", "top", "bottom"]}},
               "required": ["role", "page", "region"], "additionalProperties": False}, "strict": True}


def inspect_page(paths, counts, role, page, region):
    if role not in paths or type(page) is not int or not 1 <= page <= counts[role] or region not in ("full", "top", "bottom"):
        return "That page or region is unavailable. Use the supplied manifest."
    with TemporaryDirectory() as temporary:
        stem = Path(temporary) / "page"
        subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", "150", "-singlefile", "-png",
                        str(paths[role]), str(stem)], capture_output=True, check=True, timeout=30)
        with Image.open(stem.with_suffix(".png")) as image:
            if region == "top":
                image = image.crop((0, 0, image.width, image.height * 3 // 5))
            if region == "bottom":
                image = image.crop((0, image.height * 2 // 5, image.width, image.height))
            blob = BytesIO()
            image.convert("RGB").save(blob, format="JPEG", quality=90)
    return [{"type": "input_text", "text": f"{role} physical p. {page}, {region}"},
            {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(blob.getvalue()).decode()}]


def review_case(case, mode, model, output, *, family=None, directory=None, rubric=None):
    if family is None:
        family = CASES[case][0]
    if directory is None:
        directory = ROOT / ".local" / ("th-payer/cases" if family == "aia" else "us-payer/packets") / case
    meta_path = directory / "metadata.json"
    if not meta_path.exists():
        meta_path = directory / "intake.json"
    meta = json.loads(meta_path.read_text())
    paths = {role: directory / (role + ".pdf") for role in ROLES if (directory / (role + ".pdf")).is_file()}
    counts = {role: len(PdfReader(path).pages) for role, path in paths.items()}
    originals = {role: path.read_bytes() for role, path in paths.items()}
    inputs_hash = sha256()
    for role, raw in originals.items():
        inputs_hash.update(role.encode() + raw)
    history = request_input(meta, originals, counts, rubric or RUBRICS[family])
    start = perf_counter()
    trace, tokens, cached = [], [0, 0], 0
    with OpenAI(timeout=180, max_retries=1) as client:
        for turn in range(3):
            allow = mode == "agent" and turn < 2
            extra = {"tools": [INSPECT], "parallel_tool_calls": False, "include": ["reasoning.encrypted_content"]} if allow else {}
            if allow and turn == 0:
                extra["tool_choice"] = "required"
            guidance = (" Inspect at least one self-selected page or region to verify the hardest field. "
                        "Choose any useful page, then return the final checked fields.") if mode == "agent" else ""
            answer = client.responses.parse(model=model, instructions=INSTRUCTIONS + guidance, input=history,
                                            store=False, text_format=Review, **extra)
            tokens[0] += answer.usage.input_tokens
            tokens[1] += answer.usage.output_tokens
            cached += getattr(answer.usage.input_tokens_details, "cached_tokens", 0) or 0
            calls = [item for item in answer.output if item.type == "function_call"]
            if not calls:
                if not answer.output_parsed or answer.status != "completed":
                    raise RuntimeError("No completed structured review")
                checks = [c.model_dump() for c in answer.output_parsed.checks]
                break
            if not allow:
                raise RuntimeError("Unexpected function call")
            history.extend(answer.output)
            for call in calls:
                args = json.loads(call.arguments)
                trace.append(args)
                observation = inspect_page(paths, counts, **args)
                history.append({"type": "function_call_output", "call_id": call.call_id, "output": observation})
    result = {"case": case, "mode": mode, "model": model, "checks": checks, "trace": trace,
              "seconds": round(perf_counter()-start, 2), "input_tokens": tokens[0], "cached_tokens": cached,
              "output_tokens": tokens[1], "manifest": counts, "inputs_sha256": inputs_hash.hexdigest()}
    (output / f"{case}.{mode}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def score(result):
    case = result["case"]
    gold = expected(case, CASES[case][0])
    checks = result["checks"]
    rows = []
    for field, (state, needed) in gold.items():
        matches = [c for c in checks if c["field"] == field]
        item = matches[0] if len(matches) == 1 else {}
        actual = {(c["role"], c["page"]) for c in item.get("pages", [])}
        valid = all(1 <= p <= result["manifest"].get(r, 0) for r, p in actual)
        correct = item.get("state", "").lower().strip() == state
        rows.append((field, correct, correct and valid and needed <= actual))
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true", help="Send fictional packet PDFs to OpenAI.")
    p.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    p.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    p.add_argument("--output", type=Path, default=ROOT / ".local/payer-ai")
    p.add_argument("--resume", action="store_true", help="Use saved case/mode outputs in this directory from the same experiment.")
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if not args.live:
        p.exit(0, f"Prepared {len(args.cases)} case names for paired review. Use --live to run the comparison.\n")
    model = os.getenv("OPENAI_OCR_MODEL") or "gpt-6.2-astra"
    failed = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {}
        for case in args.cases:
            for mode in ("single", "agent"):
                if args.resume and (args.output / f"{case}.{mode}.json").is_file():
                    continue
                pending[pool.submit(review_case, case, mode, model, args.output)] = (case, mode)
        for fut in as_completed(pending):
            case, mode = pending[fut]
            try:
                result = fut.result()
                print(case, mode, score(result), result["seconds"], len(result["trace"]), flush=True)
            except Exception as exc:
                # The provider request contains entire PDFs. Avoid including that request in logs.
                print(case, mode, type(exc).__name__, getattr(exc, "status_code", ""), str(getattr(exc, "message", ""))[:350], flush=True)
                failed.append((case, mode))
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
