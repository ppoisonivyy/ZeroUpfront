"""Rehearse AIA IPD form packets and a local settlement control. No payload goes to a payer."""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from time import perf_counter

from payer_forms_th.packet import (
    DEST,
    FORMS,
    META,
    exhibit,
    exhibits,
    filled_form,
    joined,
    verified_form_bytes,
)
from pypdf import PdfReader
from workspace_http import server, temporary_database

# The gold labels come from the synthetic encounter and printed form fields, not parser outcomes.
CASES = {
    "th-aligned": ("th", "clean", "ready_for_review", None),
    "en-aligned": ("en", "clean", "ready_for_review", None),
    "th-wrong-admission": ("th", "encounter", "needs_review", "same-encounter"),
    "en-unsigned-patient": ("en", "consent", "needs_review", "patient-consent"),
    "th-unsigned-physician": ("th", "certification", "needs_review", "physician-certification"),
    "th-amount-mismatch": ("th", "amount", "needs_review", "submitted-amount"),
    "en-missing-letter": ("en", "missing-letter", "needs_review", "missing_letter"),
}
HEAD = {"If-Match": '"1"'}


def save_case(name, files):
    folder = DEST / "cases" / name
    folder.mkdir(parents=True, exist_ok=True)
    for role, raw in files.items():
        (folder / (role + ".pdf")).write_bytes(raw)
    (folder / "metadata.json").write_text(json.dumps(META, indent=2) + "\n")


def upload(client, files, live=False):
    return client.post(
        "/api/discharge",
        data=META | {"confirmed": "true", "ocr": str(live).lower()},
        files={r: (r + ".pdf", data, "application/pdf") for r, data in files.items()},
    )


def approve(client, path):
    return client.post(path + "/approve", headers=HEAD, json={"reviewer": "Thai rehearsal coordinator"})


def event(client, path, version, action, values, raw=None):
    return client.post(
        path + "/workflow",
        headers=HEAD,
        data={"workflow_version": str(version), "actor": "Thai rehearsal coordinator", "action": action}
        | values,
        files={"file": ("mock-payer-reply.pdf", raw, "application/pdf")} if raw else None,
    )


def submission(client, path):
    return event(
        client, path, 0, "submission", {"reference": "SIM-TH-IPD-01", "channel": "Local portal rehearsal"}
    )


def matches_target(target, findings, edition):
    if not target:
        return None
    if target == "missing_letter":
        return any(f["code"] == target for f in findings)
    form_page = (2 if edition == "th" else 1) + (target in {"same-encounter", "physician-certification"})
    terms = {
        "same-encounter": ["encounter", "admission number"],
        "patient-consent": ["consent", "patient signature"],
        "physician-certification": ["physician signature", "medical certification", "physician certification"],
        "submitted-amount": ["amount claimed", "claim amount", "submitted amount", "amount mismatch"],
    }
    return any(
        any(term in f["message"].lower() for term in terms[target])
        and any(c["role"] == "records" and c["page"] == form_page for c in f["sources"])
        for f in findings
    )


def evaluate(client, name, spec, base, live=False):
    language, defect, gold, target = spec
    form = filled_form(language, defect)
    files = base | {"records": joined(form, base["records"])}
    if defect == "missing-letter":
        del files["letter"]
    directory = DEST / "cases" / name
    save_case(name, files)
    (directory / "aia-form-only.pdf").write_bytes(form)
    start = perf_counter()
    response = upload(client, files, live)
    elapsed = round((perf_counter() - start) * 1000, 1)
    result = {
        "case": name,
        "gold": gold,
        "target": target,
        "edition": language,
        "defect": defect,
        "http": response.status_code,
        "intake_ms": elapsed,
        "ocr_requested": live,
    }
    if not response.is_success:
        return result | {"reason": response.json().get("detail")}, None
    c = response.json()
    checked = {}
    for source in c["sources"]:
        raw = client.get(source["url"])
        raw.raise_for_status()
        role = source["role"]
        assert raw.content == files[role] and sha256(raw.content).hexdigest() == source["sha256"]
        checked[role] = {"sha256": source["sha256"], "pages": len(PdfReader(BytesIO(raw.content)).pages)}
    assert set(checked) == set(files)
    path = "/api/discharge/" + c["id"]
    result.update(
        status=c["status"],
        findings=c["findings"],
        ocr_pages=c["ocr_page_count"],
        target_explained=matches_target(target, c["findings"], language),
        originals=checked,
        payable_minor=c["payable_minor"],
        bill_minor=c["bill_total_minor"],
        reported_share_minor=c["source_reported_patient_share_minor"],
        reported_cap_minor=c["source_reported_cap_minor"],
    )
    if live:
        audit = client.get(path + "/revisions/1/ocr-review")
        audit.raise_for_status()
        pages = audit.json()["pages"]
        transcript = {p["page"]: p["text"] for p in pages if p["role"] == "records"}
        part_a, part_b = (2, 3) if language == "th" else (1, 2)
        probes = [
            (part_a, META["member"], True),
            (part_a, "92,750.00" if defect == "amount" else "87,500.00", True),
            (part_a, "TEST PATIENT MARK", defect != "consent"),
            (part_b, "AN-QA999" if defect == "encounter" else META["encounter"], True),
            (part_b, "HN-QA017", True),
            (part_b, "TEST CLINICIAN MARK", defect != "certification"),
        ]
        if language == "th":
            probes.append((part_a, "มือซ้าย", True))
        result["ocr_exact_probes"] = [
            {
                "page": page,
                "literal": literal,
                "expected_present": present,
                "present": literal in transcript.get(page, ""),
                "transcript_returned": page in transcript,
            }
            for page, literal, present in probes
        ]
    if c["status"] == "needs_review":
        result["guards"] = {
            "approve": approve(client, path).status_code,
            "export": client.get(path + "/export?revision=1").status_code,
            "submission": submission(client, path).status_code,
        }
    return result, c


def revision(client, first, base):
    path = "/api/discharge/" + first["id"]
    raw = joined(filled_form("th"), base["records"])
    r = client.post(
        path + "/documents",
        headers=HEAD,
        data={"confirmed": "true"},
        files={"records": ("corrected-thai-records.pdf", raw, "application/pdf")},
    )
    r.raise_for_status()
    second = r.json()
    assert second["revision"] == 2
    hashes = []
    for obj, expected in [(first, joined(filled_form("th", "encounter"), base["records"])), (second, raw)]:
        source = next(s for s in obj["sources"] if s["role"] == "records")
        exact = client.get(source["url"])
        exact.raise_for_status()
        assert exact.content == expected and sha256(expected).hexdigest() == source["sha256"]
        hashes.append(source["sha256"])
    assert hashes[0] != hashes[1]
    return {
        "prior_source_sha256": hashes[0],
        "corrected_source_sha256": hashes[1],
        "prior_status": first["status"],
        "corrected_status": second["status"],
        "prior_revision_retrieved": client.get(path, params={"revision": 1}).json()["revision"],
        "stale_approval_http": approve(client, path).status_code,
    }


def control(client, base):
    # Uses the same synthetic encounter/costs. No carrier form in this internal-format positive control.
    save_case("supported-control", base)
    response = upload(client, base)
    response.raise_for_status()
    c = response.json()
    assert c["status"] == "ready_for_review", c["findings"]
    assert c["bill_total_minor"] == 8750000 and c["source_reported_patient_share_minor"] == 500000
    assert c["source_reported_cap_minor"] == 9000000 and c["payable_minor"] is None
    path = "/api/discharge/" + c["id"]
    stages = {"intake": c["status"]}
    a = approve(client, path)
    a.raise_for_status()
    stages["approval"] = a.json()["status"]
    packet = client.get(path + "/export?revision=1")
    packet.raise_for_status()
    parts = PdfReader(BytesIO(packet.content)).attachments
    assert sorted(sha256(v).hexdigest() for vals in parts.values() for v in vals) == sorted(
        sha256(v).hexdigest() for v in base.values()
    )
    (DEST / "cases/supported-control/reviewed-discharge.pdf").write_bytes(packet.content)
    stages["export_verified_originals"] = len(parts)
    sent = submission(client, path)
    sent.raise_for_status()
    stages["submission"] = sent.json()["insurer_status"]
    for version, outcome, terms in [
        (1, "query", "Provide the unused sterile pack credit."),
        (2, "partial", "Synthetic payer confirms THB 80,000 after its own review."),
    ]:
        values = {
            "outcome": outcome,
            "reference": "TEST-RESP-" + str(version),
            "terms": terms,
            "confirmed": "true",
        }
        if outcome == "partial":
            values.update(amount="80000.00", currency="THB")
        raw = exhibit("Synthetic test payer reply", "SIM-RESP-" + str(version), [[terms]])
        res = event(client, path, version, "reply", values, raw)
        res.raise_for_status()
        stages[outcome] = res.json()["insurer_status"]
        assert res.json()["settlement_status"] == "unpaid"
    for version, amount in [(3, "50000.00"), (4, "30000.00")]:
        rec = event(
            client,
            path,
            version,
            "payment",
            {
                "reference": "SIM-REMIT-" + str(version),
                "amount": amount,
                "currency": "THB",
                "notes": "Local fictional remittance",
            },
        )
        rec.raise_for_status()
        stages["remittance_" + str(version - 2)] = rec.json()["settlement_status"]
    assert stages["remittance_2"] == "paid"
    return stages


def run(args):
    DEST.mkdir(exist_ok=True, parents=True)
    selected = {k: CASES[k] for k in args.live_cases} if args.live_cases else CASES
    for edition in sorted({entry[0] for entry in selected.values()}):
        verified_form_bytes(edition)
    base = exhibits()
    with temporary_database() as dsn, server(dsn, args.live) as client:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            observations = list(pool.map(lambda kv: evaluate(client, *kv, base, args.live), selected.items()))
        output = {
            "sources": {k: {"url": v[0], "sha256": v[1]} for k, v in FORMS.items()},
            "results": [r for r, _ in observations],
        }
        if not args.live:
            results = {name: c for name, (_, c) in zip(selected, observations, strict=True)}
            output["revision"] = revision(client, results["th-wrong-admission"], base)
            output["supported_control"] = control(client, base)
            with_extra = upload(client, base | {"payer_form": filled_form("th", "consent")})
            output["extra_form"] = {"http": with_extra.status_code}
            if with_extra.is_success:
                body = with_extra.json()
                output["extra_form"].update(
                    status=body["status"], retained_roles=[s["role"] for s in body["sources"]]
                )
            else:
                output["extra_form"]["detail"] = with_extra.json().get("detail")
    suffix = "-" + "_".join(args.live_cases) if args.live_cases else ""
    target = DEST / (f"live{suffix}.json" if args.live else "results.json")
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    for line in output["results"]:
        print(
            line["case"],
            line["http"],
            line.get("status") or line.get("reason"),
            line.get("target_explained"),
            line["intake_ms"],
            flush=True,
        )
    print(target)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Enable cloud OCR for synthetic packets on public payer forms."
    )
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 9))
    parser.add_argument(
        "--live-cases", nargs="+", choices=list(CASES), help="Limit the live test to named synthetic cases."
    )
    options = parser.parse_args()
    if options.live_cases and not options.live:
        parser.error("--live-cases needs --live")
    run(options)
