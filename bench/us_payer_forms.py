"""Exercise two genuine US claim forms over the normal local discharge HTTP surface."""

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import workspace_http
from payer_forms_us.specimens import (
    TH,
    TH_ROWS,
    US,
    US_ROWS,
    get_blanks,
    institutional,
    joined,
    overseas,
    rendered,
    supporting,
)
from pypdf import PdfReader
from workspace_http import ROOT, server, temporary_database

sys.path.insert(0, str(ROOT))
from discharge_journey import exercise

from app.discharge_claim import load_discharge_fixture

# Expected facts independently fixed from the form, invoice arithmetic and discharge account.
# These labels are not based on the app's screening outcomes.
CASES = {
    "cms_aligned": (
        "cms",
        "aligned",
        "Home discharge; USD 11,285 bill; no case-specific authorization supplied.",
    ),
    "cms_wrong_member": (
        "cms",
        "wrong_member",
        "FL 60 ends 0099; encounter and admissions register end 0042.",
    ),
    "cms_disposition": (
        "cms",
        "disposition_conflict",
        "FL 17 is 02 (hospital transfer); discharge note says home.",
    ),
    "cms_replacement": (
        "cms",
        "replacement_missing_reference",
        "FL 4 ends 7 (replacement); FL 64 lacks the original DCN.",
    ),
    "cms_total": (
        "cms",
        "bill_total_disagrees",
        "FL 47 USD 11,785 vs five charge lines and invoice USD 11,285.",
    ),
    "fep_assigned": (
        "fep",
        "aligned",
        "THB 158,050 total; section 5D names the hospital and has a test attestation.",
    ),
    "fep_member": (
        "fep",
        "member_payee",
        "Sections 5A-B select member check; 5D blank. Route for member reimbursement.",
    ),
    "fep_unsigned": (
        "fep",
        "assignment_unsigned",
        "Section 5D names hospital but lacks assignment signature.",
    ),
    "fep_total": (
        "fep",
        "form_total_disagrees",
        "Section 4 states THB 160,000; itemized net is THB 158,050.",
    ),
}


def packet(blanks, family, issue):
    if family == "cms":
        meta = US.copy()
        evidence = supporting(meta, US_ROWS, False)
        form = institutional(blanks[0], blanks[1], issue)
        evidence["bill"] = joined(form, evidence["bill"])
    else:
        meta = TH.copy()
        evidence = supporting(meta, TH_ROWS, True)
        form = overseas(blanks[2], issue)
        evidence["records"] = joined(form, evidence["records"])
        evidence["letter"] = rendered(
            [
                (
                    "Fictional prior admission correspondence",
                    [
                        "Simulation only. This document describes an invented case-specific approval scenario.",
                        f"Insurer {meta['insurer']}; patient Casey Example; member {meta['member']}.",
                        f"To {meta['facility']}, reference {meta['encounter']}; issued October 30, 2026.",
                        "Approval scenario: inpatient fixation 31 October through 3 November. Submit the final itemized account for review.",
                        "This simulation does not confirm a payable amount. The assignment election is on the separate member form.",
                    ],
                )
            ]
        )
    return meta, evidence, form


def files(docs):
    return {role: (role + ".pdf", raw, "application/pdf") for role, raw in docs.items()}


def intake(client, meta, docs, *, ocr=False):
    fields = {key: value for key, value in meta.items() if key != "id"}
    return client.post(
        "/api/discharge",
        data=fields | {"confirmed": "true", "ocr": str(ocr).lower()},
        files=files(docs),
    )


def observe(client, case, docs):
    originals_ok = {}
    for src in case["sources"]:
        role = src["role"]
        restored = client.get(src["url"])
        originals_ok[role] = (
            restored.status_code == 200
            and restored.content == docs[role]
            and src["sha256"] == sha256(docs[role]).hexdigest()
        )
    assert set(originals_ok) == set(docs) and all(originals_ok.values())
    return {
        "status": case["status"],
        "revision": case["revision"],
        "sources": sorted(originals_ok),
        "billed_minor": case["bill_total_minor"],
        "payable_minor": case["payable_minor"],
        "findings": {row["code"]: row["message"] for row in case["findings"]},
        "insurer": case["insurer_status"],
        "settlement": case["settlement_status"],
    }


def try_stages(client, case, currency="USD"):
    path = "/api/discharge/" + case["id"]
    revision = case["revision"]
    headers = {"If-Match": f'"{revision}"'}

    def event(action, version, args, attachment=None):
        return client.post(
            path + "/workflow",
            headers=headers,
            data={
                "workflow_version": str(version),
                "actor": "Fictional coordinator",
                "action": action,
            }
            | args,
            files=files({"file": attachment}) if attachment else None,
        )

    approved = client.post(
        path + "/approve", headers=headers, json={"reviewer": "Fictional reviewer"}
    )
    export = client.get(path + "/export", params={"revision": revision})
    sent = event(
        "submission", 0, {"reference": "SIM-42", "channel": "Local training portal"}
    )
    version = 1 if sent.is_success else 0
    query = event(
        "reply",
        version,
        {
            "reference": "SIM-Q42",
            "confirmed": "true",
            "outcome": "query",
            "terms": "Supply the final account.",
        },
        rendered([("Simulated payer query", ["Supply the final account."])]),
    )
    version += int(query.is_success)
    reply = event(
        "reply",
        version,
        {
            "reference": "SIM-R42",
            "confirmed": "true",
            "outcome": "partial",
            "terms": "Simulated partial decision.",
            "amount": "2000.00",
            "currency": currency,
        },
        rendered(
            [("Simulated decision", ["Partial decision of " + currency + " 2,000."])]
        ),
    )
    version += int(reply.is_success)
    paid = event(
        "payment",
        version,
        {
            "reference": "SIM-P42",
            "amount": "2000.00",
            "currency": currency,
            "notes": "Simulated remittance.",
        },
    )
    final = client.get(path).json()
    results = {
        label: r.status_code
        for label, r in (
            ("approval", approved),
            ("export", export),
            ("submission", sent),
            ("payer_query", query),
            ("partial_decision", reply),
            ("payment", paid),
        )
    }
    if export.is_success:
        results["export_sha256"] = sorted(
            sha256(b).hexdigest()
            for bufs in PdfReader(BytesIO(export.content)).attachments.values()
            for b in bufs
        )
    results.update(
        final_insurer=final["insurer_status"],
        final_settlement=final["settlement_status"],
    )
    return results


def run_case(client, blanks, cache, item):
    name, (family, issue, gold) = item
    meta, docs, form = packet(blanks, family, issue)
    (cache / (name + ".pdf")).write_bytes(form)
    directory = cache / "packets" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "intake.json").write_text(json.dumps(meta, indent=2) + "\n")
    for role, original in docs.items():
        (directory / (role + ".pdf")).write_bytes(original)
    started = perf_counter()
    response = intake(client, meta, docs)
    elapsed = round(1000 * (perf_counter() - started), 1)
    response.raise_for_status()
    case = response.json()
    outcome = {"gold": gold, "intake_ms": elapsed, **observe(client, case, docs)}
    outcome["stages"] = try_stages(client, case, "USD" if family == "cms" else "THB")
    if name in {"cms_total", "fep_unsigned"}:
        role = "bill" if family == "cms" else "records"
        _, corrected, _ = packet(blanks, family, "aligned")
        path = "/api/discharge/" + case["id"]
        correct = client.post(
            path + "/documents",
            headers={"If-Match": '"1"'},
            data={"confirmed": "true"},
            files=files({role: corrected[role]}),
        )
        correct.raise_for_status()
        outcome["corrected"] = observe(client, correct.json(), corrected)
        outcome["corrected"]["stages"] = try_stages(
            client, correct.json(), "USD" if family == "cms" else "THB"
        )
        old = client.get(path, params={"revision": 1}).json()
        assert (
            observe(client, old, docs)["revision"] == 1
            and outcome["corrected"]["revision"] == 2
        )
    return name, outcome


def extra_and_controls(client, blanks):
    meta, good, _ = load_discharge_fixture()
    form = overseas(blanks[2], "assignment_unsigned")
    extra = {"payer_form": form}
    posted = intake(client, meta, good | extra)
    result = {"extra_intake_http": posted.status_code}
    if posted.is_success:
        case = posted.json()
        result["extra_intake_status"] = case["status"]
        result["extra_intake_roles"] = [s["role"] for s in case["sources"]]
        result["stages"] = try_stages(client, case, "THB")
        hashes = result["stages"].get("export_sha256", [])
        result["export_contains_fifth_form"] = sha256(form).hexdigest() in hashes
        result["export_contains_four_control_originals"] = set(hashes) == {
            sha256(b).hexdigest() for b in good.values()
        }
    else:
        result["extra_intake_message"] = posted.json()["detail"]
    valid = intake(client, meta, good)
    valid.raise_for_status()
    ident = valid.json()["id"]
    replace = client.post(
        "/api/discharge/" + ident + "/documents",
        headers={"If-Match": '"1"'},
        data={"confirmed": "true"},
        files=files({"bill": good["bill"]} | extra),
    )
    result["extra_replacement_http"] = replace.status_code
    latest = client.get("/api/discharge/" + ident).json()
    result["extra_replacement_revision"] = latest["revision"]
    result["extra_replacement_roles"] = [s["role"] for s in latest["sources"]]
    if not replace.is_success:
        result["extra_replacement_message"] = replace.json()["detail"]
    dup_meta, dup, _ = load_discharge_fixture("duplicate_line")
    duplicate = intake(client, dup_meta, dup)
    duplicate.raise_for_status()
    held = duplicate.json()
    exercise(client, {"duplicate_line": held})
    control = client.get("/api/discharge/" + held["id"]).json()
    result["template_control"] = {
        "initial_status": held["status"],
        "initial_codes": [x["code"] for x in held["findings"]],
        "final_revision": control["revision"],
        "final_insurer": control["insurer_status"],
        "final_settlement": control["settlement_status"],
        "verified": "correction, original history, stale approval 412, staff approval, four exact exported originals, submission, query, partial decision, split remittances, duplicate rejection",
    }
    return result


def live_comparison(client, blanks, issue):
    meta, docs, _ = packet(blanks, "fep", issue)
    start = perf_counter()
    result = intake(client, meta, docs, ocr=True)
    timing = round(perf_counter() - start, 2)
    if not result.is_success:
        return {
            "http": result.status_code,
            "seconds": timing,
            "detail": result.json().get("detail"),
        }
    case = result.json()
    path = "/api/discharge/" + case["id"] + "/revisions/1/ocr-review"
    review = client.get(path)
    review.raise_for_status()
    pages = review.json()["pages"]
    text = " ".join(" ".join(p["text"].split()).upper() for p in pages)
    witness = {
        "patient": "CASEY EXAMPLE" in text,
        "provider": "LANTERN QUAY HOSPITAL" in text,
        "form_total": bool(re.search(r"158,?050\.00", text)),
        "printed_test_attestation_count": text.count("SYNTHETIC TEST ATTESTATION"),
    }
    summary = observe(client, case, docs)
    summary.update(
        transcript_evidence=witness,
        seconds=timing,
        http=result.status_code,
        pages=case["ocr_page_count"],
        eligible=case["ocr_review_available"],
        stages=try_stages(client, case, "THB"),
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--cache", type=Path, default=ROOT / ".local/us-payer")
    parser.add_argument("--server-root", type=Path, default=ROOT)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".local/us-payer/observations.json"
    )
    parser.add_argument(
        "--live-fep-ocr",
        action="store_true",
        help="Also send the two synthetic FEP assignment examples through the configured OpenAI OCR service.",
    )
    args = parser.parse_args()
    if args.live_fep_ocr and not os.getenv("OPENAI_API_KEY"):
        parser.error("--live-fep-ocr requires OPENAI_API_KEY")
    blanks = get_blanks(args.cache)
    with (
        patch.object(workspace_http, "ROOT", args.server_root.resolve()),
        temporary_database() as dsn,
        server(dsn, args.live_fep_ocr) as client,
    ):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = dict(
                pool.map(
                    lambda item: run_case(client, blanks, args.cache, item),
                    CASES.items(),
                )
            )
        extra = extra_and_controls(client, blanks)
        live = {}
        if args.live_fep_ocr:
            with ThreadPoolExecutor(max_workers=2) as pool:
                issues = ["aligned", "assignment_unsigned"]
                live = dict(
                    zip(
                        issues,
                        pool.map(
                            lambda issue: live_comparison(client, blanks, issue), issues
                        ),
                        strict=True,
                    )
                )
    report = {
        "workers": args.workers,
        "live_fep_ocr": live,
        "cases": rows,
        "controls": extra,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for name, result in rows.items():
        print(
            name,
            result["status"],
            result["intake_ms"],
            result["stages"]["approval"],
            sorted(result["findings"]),
        )
    print(json.dumps(extra, indent=2))


if __name__ == "__main__":
    main()
