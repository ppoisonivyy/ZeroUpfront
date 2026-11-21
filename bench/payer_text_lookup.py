"""Paired, one-trial raw model comparison on four synthetic payer packets with a case-scoped literal lookup."""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import monotonic

from openai import APIError, OpenAI
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.payer_ai_reader import (
    INSTRUCTIONS,
    ROLES,
    STAFF_GUIDANCE,
    STAFF_RUBRICS,
    Review,
    request_input,
)

# Case selection and expected values. These are read only by the offline scorer.
CASES = {
    "cms_wrong_member": ("cms", "us-payer/packets/cms_wrong_member"),
    "cms-member": ("cms", "payer-challenge/fixtures/cms-member"),
    "aia-en-ink": ("aia", "payer-challenge/fixtures/aia-en-ink"),
    "fep-affiliation-unknown": ("fep", "payer-confirmation/fep-affiliation-unknown"),
}
GOLD = {
    "cms_wrong_member": (
        "member",
        "conflict",
        "bill",
        1,
        "TEST-MBI-0099",
        "TEST-MBI-0042",
    ),
    "cms-member": ("member", "conflict", "bill", 1, "HM0130891", "HM0130871"),
    "aia-en-ink": ("admission", "match", "records", 2, "AN-HO944", "AN-HO944"),
    "fep-affiliation-unknown": (
        "payee",
        "unknown",
        "records",
        1,
        "Banyan Reach Specialist Centre",
        "VX-5428",
    ),
}
LOOKUP = {
    "type": "function",
    "name": "find_case_text",
    "description": "Find one self-selected exact, case-sensitive string across the supplied case PDFs. Returns role, physical page and native text snippet for each hit. Text matches alone do not establish form field, encounter linkage, or a visible mark. Empty results can occur on scanned pages.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "One literal string, such as an identifier or provider name seen in the case; 3 to 96 characters.",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}
COMMON = INSTRUCTIONS + STAFF_GUIDANCE
LIMIT = 160


def load_case(name):
    family, folder = CASES[name]
    path = ROOT / ".local" / folder
    if family == "fep":
        # This confirmation packet was originally written without a metadata.json.
        # Only intake fields are copied. The altered provider and other encounter stay out of the model input.
        from payer_forms_us.specimens import TH

        panel = json.loads(
            (ROOT / "bench/payer_confirmation_cases/gold.json").read_text()
        )["cases"]
        intake = next(row for row in panel if row["id"] == name)
        meta = TH | {key: intake[key] for key in ("member", "encounter", "facility")}
    else:
        p = next(
            (
                path / f
                for f in ("intake.json", "metadata.json")
                if (path / f).is_file()
            ),
            None,
        )
        if not p:
            raise FileNotFoundError(
                f"Prepare the synthetic case at {path} before running."
            )
        meta = json.loads(p.read_text())
    originals = {
        r: (path / (r + ".pdf")).read_bytes()
        for r in ROLES
        if (path / (r + ".pdf")).is_file()
    }
    if not originals:
        raise FileNotFoundError(path)
    pages = {
        (role, n): " ".join((p.extract_text() or "").split())
        for role, raw in originals.items()
        for n, p in enumerate(PdfReader(BytesIO(raw)).pages, 1)
    }
    counts = {r: sum(role == r for role, _ in pages) for r in originals}
    return meta, originals, pages, counts


def exact_lookup(pages, query):
    query = " ".join(query.split())
    if not 3 <= len(query) <= 96:
        return {"hits": [], "error": "Supply 3 to 96 literal characters."}
    hits = []
    for (role, n), content in pages.items():
        start = content.find(query)
        if start >= 0:
            hits.append(
                {
                    "role": role,
                    "page": n,
                    "snippet": content[max(0, start - 72) : start + len(query) + 72],
                }
            )
    return {"hits": hits[:12], "matching_pages": len(hits)}


def score(case, checks, pages, meta):
    field, state, role, number, printed, comparison = GOLD[case]
    found = [c for c in checks if c["field"] == field]
    if len(found) != 1:
        return {"target_field": field, "complete": False, "missing_or_duplicate": True}
    row = found[0]
    first = (role, number)
    cited = {(p["role"], p["page"]) for p in row["pages"]}
    source_hits = []
    for r, n in sorted(cited - {first}):
        content = pages.get((r, n), "")
        if r not in {"bill", "records", "summary"} or comparison not in content:
            continue
        if case.startswith("cms"):
            if meta["encounter"] not in content or not (
                "Member " + comparison in content or "Member: " + comparison in content
            ):
                continue
        elif (
            case == "aia-en-ink"
            and "Encounter: " + comparison not in content
            or case == "fep-affiliation-unknown"
            and meta["facility"] not in content
        ):
            continue
        source_hits.append([r, n])
    details = row["observation"]
    result = {
        "target_field": field,
        "expected_state": state,
        "exact_state": row["state"] == state,
        "form_page_supported": first in cited and printed in pages[first],
        "valid_independent_pages": source_hits,
        "printed_value_named": printed in details,
        "comparison_value_named": comparison in details,
        "all_citations_exist": all(k in pages for k in cited),
    }
    if case == "fep-affiliation-unknown":
        result["registered_encounter_named"] = meta["encounter"] in details
        result["intake_facility_named"] = meta["facility"] in details
    result["complete"] = all(
        result[k]
        for k in (
            "exact_state",
            "form_page_supported",
            "valid_independent_pages",
            "printed_value_named",
            "comparison_value_named",
            "all_citations_exist",
        )
    )
    return result


def trial(case, arm, model, packet, out):
    meta, originals, pages, counts = packet
    family, _ = CASES[case]
    history = request_input(meta, originals, counts, STAFF_RUBRICS[family])
    manifest = sha256(
        json.dumps(history, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    start = monotonic()
    result = {
        "case": case,
        "arm": arm,
        "input_sha256": manifest,
        "instructions_sha256": sha256(COMMON.encode()).hexdigest(),
        "model_requested": model,
        "models_returned": [],
        "requests": 0,
        "trace": [],
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
    }
    try:
        with OpenAI(timeout=90, max_retries=0) as client:
            for step in range(2 if arm == "lookup" else 1):
                remaining = LIMIT - (monotonic() - start)
                if remaining <= 0:
                    raise TimeoutError("Trial deadline reached.")
                extra = {}
                if arm == "lookup" and step == 0:
                    extra = {
                        "tools": [LOOKUP],
                        "tool_choice": "required",
                        "parallel_tool_calls": False,
                        "include": ["reasoning.encrypted_content"],
                    }
                result["requests"] += 1
                answer = client.responses.parse(
                    model=model,
                    instructions=COMMON,
                    input=history,
                    store=False,
                    text_format=Review,
                    max_output_tokens=2500,
                    timeout=min(90, remaining),
                    **extra,
                )
                result["models_returned"].append(answer.model)
                result["input_tokens"] += answer.usage.input_tokens
                result["output_tokens"] += answer.usage.output_tokens
                result["cached_input_tokens"] += (
                    getattr(answer.usage.input_tokens_details, "cached_tokens", 0) or 0
                )
                calls = [v for v in answer.output if v.type == "function_call"]
                if extra:
                    if len(calls) != 1 or calls[0].name != "find_case_text":
                        raise RuntimeError(
                            "The required single tool call was not returned."
                        )
                    call = calls[0]
                    q = json.loads(call.arguments)["query"]
                    hits = exact_lookup(pages, q)
                    result["trace"].append({"query": q, **hits})
                    history.extend(answer.output)
                    history.append(
                        {
                            "type": "function_call_output",
                            "call_id": call.call_id,
                            "output": json.dumps(hits),
                        }
                    )
                else:
                    if (
                        answer.status != "completed"
                        or calls
                        or not isinstance(answer.output_parsed, Review)
                    ):
                        raise RuntimeError("Incomplete final response.")
                    result["raw_response"] = answer.output_text
                    result["checks"] = answer.output_parsed.model_dump()["checks"]
                    result["score"] = score(case, result["checks"], pages, meta)
    except (
        APIError,
        RuntimeError,
        TimeoutError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        result["error"] = type(exc).__name__
    result["elapsed_seconds"] = round(monotonic() - start, 2)
    (out / (case + "." + arm + ".json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        case,
        arm,
        "time",
        result["elapsed_seconds"],
        "exact",
        result.get("score", {}).get("complete"),
        result.get("error", ""),
        flush=True,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / ".local/payer-text-lookup")
    args = parser.parse_args()
    if not args.live or not os.getenv("OPENAI_API_KEY"):
        parser.error(
            "Running the paired experiment requires --live and OPENAI_API_KEY."
        )
    packets = {k: load_case(k) for k in CASES}
    args.out.mkdir(parents=True, exist_ok=False)
    model = os.getenv("OPENAI_OCR_MODEL") or "gpt-6.2-astra"
    order = [
        (case, arm)
        for i, case in enumerate(CASES)
        for arm in (("pdf", "lookup") if i % 2 == 0 else ("lookup", "pdf"))
    ]
    print(
        "Starting eight one-trial case/arm cells, four workers, no provider retries.",
        flush=True,
    )
    with ThreadPoolExecutor(4) as pool:
        futures = [
            pool.submit(trial, case, arm, model, packets[case], args.out)
            for case, arm in order
        ]
        rows = [f.result() for f in as_completed(futures)]
    for case in CASES:
        pair = [r for r in rows if r["case"] == case]
        assert len(pair) == 2 and len({r["input_sha256"] for r in pair}) == 1
    if any("error" in r for r in rows):
        raise SystemExit(
            "At least one trial failed. Inspect the saved observations; no repeat was attempted."
        )


if __name__ == "__main__":
    main()
