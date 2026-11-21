"""Rehearse real multipart discharge uploads and an external decision over loopback HTTP."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
from math import ceil
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

from pypdf import PdfReader

from workspace_http import ROOT, server, temporary_database

sys.path.insert(0, str(ROOT))
from app.discharge_claim import load_discharge_fixture
from app.journey_examples import pdf


def upload(client, scenario, expectation):
    meta, originals, names = load_discharge_fixture(scenario)
    fields = {k: v for k, v in meta.items() if k != "id"} | {"confirmed": "true"}
    files = {role: (names[role], raw, "application/pdf") for role, raw in originals.items()}
    start = perf_counter()
    response = client.post("/api/discharge", data=fields, files=files)
    elapsed = (perf_counter() - start) * 1000
    response.raise_for_status()
    case = response.json()
    assert case["status"] == expectation["status"], (scenario, case)
    assert case["payable_minor"] is None and case["settlement_status"] == "unpaid"
    flags = {f["code"] for f in case["findings"]}
    assert set(expectation["required_findings"]) <= flags, (scenario, flags)
    if scenario in {"wrong_payer", "stay_extension", "unapproved_procedure"}:
        assert case["source_reported_cap_minor"] is None and case["source_reported_patient_share_minor"] is None
    for src in case["sources"]:
        raw = client.get(src["url"]).content
        assert raw == originals[src["role"]] and sha256(raw).hexdigest() == src["sha256"]
    for finding in case["findings"]:
        for cite in finding["sources"]:
            assert 1 <= cite["page"] <= len(PdfReader(BytesIO(originals[cite["role"]])).pages)
    if expectation["status"] == "needs_review":
        res = client.post("/api/discharge/"+case["id"]+"/approve", headers={"If-Match": '"1"'}, json={"reviewer":"Case reviewer"})
        assert res.status_code == 409, (scenario, res.text)
    return scenario, case, elapsed


def exercise(client, cases):
    _, baseline, names = load_discharge_fixture()
    case = cases["duplicate_line"]
    path = "/api/discharge/" + case["id"]
    result = client.post(path+"/documents", data={"confirmed":"true"}, headers={"If-Match": '"1"'},
                         files={"bill": (names["bill"], baseline["bill"], "application/pdf")})
    result.raise_for_status()
    case = result.json()
    assert case["revision"] == 2 and case["status"] == "ready_for_review"
    old = client.get(path, params={"revision":1}).json()
    assert any(f["code"] == "duplicate_line" for f in old["findings"])
    assert client.post(path+"/approve", headers={"If-Match":'"1"'}, json={"reviewer":"Case reviewer"}).status_code == 412
    headers = {"If-Match": '"2"'}
    approved = client.post(path+"/approve", headers=headers, json={"reviewer":"Case reviewer"})
    approved.raise_for_status()
    packet = client.get(path+"/export", params={"revision":2})
    packet.raise_for_status()
    attachments = PdfReader(BytesIO(packet.content)).attachments
    assert {sha256(raw).hexdigest() for group in attachments.values() for raw in group} == {
        sha256(raw).hexdigest() for raw in baseline.values()}

    def event(version, action, fields, attachment=None):
        data = {"workflow_version":str(version), "actor":"Case reviewer", "action":action} | fields
        return client.post(path+"/workflow", headers=headers, data=data,
                           files={"file":("reply.pdf", attachment, "application/pdf")} if attachment else None)

    sent = event(0, "submission", {"reference":"PORTAL-DC-42", "channel":"Payer portal rehearsal"})
    assert sent.json()["insurer_status"] == "submitted", sent.text
    for version, outcome in enumerate(("query", "partial"), 1):
        terms = "Supply proof of patient share" if outcome == "query" else "THB 80,000 is confirmed by the payer for this packet"
        amount = {"amount":"80000.00","currency":"THB"} if outcome == "partial" else {}
        letter = pdf(["Synthetic insurer response", "Member: EXAMPLE-2402", "Encounter: EXAMPLE-VISIT-42", terms])
        reply = event(version,"reply",{"reference":"REPLY-"+str(version),"confirmed":"true","outcome":outcome,"terms":terms} | amount,letter)
        assert reply.json()["insurer_status"] == outcome and reply.json()["settlement_status"] == "unpaid", reply.text
    money = {"reference":"REMIT-1","amount":"50000.00","currency":"THB","notes":"Matched bank remittance"}
    received = event(3,"payment",money)
    assert received.json()["settlement_status"] == "partially_paid", received.text
    assert event(4,"payment",money).status_code == 409
    final = event(4,"payment",money | {"amount":"30000","reference":"REMIT-2"})
    assert final.json()["settlement_status"] == "paid", final.text


def wrong_document(client, path):
    meta, originals, names = load_discharge_fixture()
    originals["letter"] = path.read_bytes()
    names["letter"] = path.name
    pages = len(PdfReader(BytesIO(originals["letter"])).pages)
    fields = {k: v for k, v in meta.items() if k != "id"} | {"confirmed": "true"}
    start = perf_counter()
    response = client.post("/api/discharge", data=fields, files={
        role: (names[role], data, "application/pdf") for role, data in originals.items()
    })
    response.raise_for_status()
    case = response.json()
    assert case["status"] == "needs_review" and case["payable_minor"] is None
    result = client.post("/api/discharge/"+case["id"]+"/approve", headers={"If-Match": '"1"'}, json={"reviewer":"Case reviewer"})
    assert result.status_code == 409
    return path.name, pages, (perf_counter() - start) * 1000


def run(workers, public_brochures):
    expected = json.loads((ROOT/"fixtures/discharge/expected.json").read_text())
    with temporary_database() as dsn, server(dsn, False) as client:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(lambda item: upload(client, *item), expected.items()))
        exercise(client, {scenario: case for scenario, case, _ in rows})
        wrong_docs = [wrong_document(client, path) for path in public_brochures]
    timings = sorted(elapsed for _, _, elapsed in rows)
    held = sum(case["status"] == "needs_review" for _, case, _ in rows)
    lines = ["# Discharge claim rehearsal", "",
             f"On {date.today()}, all {len(rows)} synthetic packet scenarios returned the expected screening status and required findings. "
             f"Staff approval was blocked on all {held} unresolved packets. All uploaded originals were retrieved byte for byte. "
             "The app left the payable amount blank in every case.", "",
             f"Multipart intake and screening over local HTTP with PostgreSQL took {median(timings):.0f} ms median and "
             f"{timings[ceil(.95*len(timings))-1]:.0f} ms p95 with {workers} concurrent workers and one request per example. "
             "This measures small digital PDFs on the development machine. It excludes OCR, staff time and the payer response.", "",
             "| Uploaded example | Expected status | Observed status | Observed issues |",
             "| --- | --- | --- | --- |"]
    for scenario, case, _ in rows:
        codes = ", ".join(f["code"] for f in case["findings"]) or "None"
        lines.append(f"| {scenario} | {expected[scenario]['status']} | {case['status']} | {codes} |")
    lines += ["", "## One case from correction to payment", "",
              "The duplicate-line bill blocked approval. Uploading the original corrected bill produced revision 2. "
              "Revision 1 retained its finding and a stale approval attempt returned HTTP 412. A staff reviewer approved "
              "revision 2 and its downloaded PDF contained all four exact originals.", "",
              "The simulated payer queried the packet and later confirmed THB 80,000 as a partial decision. "
              "The app still showed unpaid. Recording THB 50,000 changed settlement to partially paid. "
              "A duplicate remittance reference returned HTTP 409. A second receipt for THB 30,000 completed settlement "
              "against the written decision. All submissions, responses and remittances here were synthetic.", "",
              "Reproduce from the repo root with `uv run --locked python bench/discharge_journey.py`. "
              "Use `--report PATH` to save the observed results. The role-specific PDFs and scenario definitions are in "
              "[the discharge fixtures](../fixtures/discharge/expected.json). The [workflow research](discharge-workflow.md) "
              "describes the external steps and manual checks.",""]
    if wrong_docs:
        lines += ["## Public policy in the wrong document slot", "",
                  "We uploaded each complete public plan brochure in place of the member-specific payer letter, "
                  "keeping the three other exhibits synthetic. Cloud OCR was disabled. Both status and approval guards were exercised.", "",
                  "| Uploaded brochure | Physical pages | Observed result | Time including approval attempt |",
                  "| --- | --- | --- | --- |"]
        for name, pages, elapsed in wrong_docs:
            lines.append(f"| {name} | {pages} | Needs investigation, payable blank, approval HTTP 409 | {elapsed:.0f} ms |")
        lines += ["", "Use one `--policy-as-letter PATH` per local brochure to reproduce this check. "
                  "It tests document-role confusion. Clause-level question accuracy has a separate [US](us-hybrid-decision.md) "
                  "and [Thai](thai-public-eval.md) evaluation.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, choices=range(1,9), default=4)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--policy-as-letter", type=Path, action="append", default=[])
    args = parser.parse_args()
    report = run(args.workers, args.policy_as_letter)
    if args.report:
        args.report.write_text(report)
    print(report)
