"""Verify concurrent staff workflows across two hospital databases, two API processes and a full restart."""

import json
import os
import secrets
import socket
import subprocess
import sys
from argparse import ArgumentParser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from io import BytesIO
from math import ceil
from pathlib import Path
from statistics import median
from threading import Barrier, Lock
from time import monotonic, perf_counter, sleep

import httpx
import psycopg
from discharge_scale import ROOT, identity, personalize, template
from psycopg.conninfo import make_conninfo
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject
from workspace_http import temporary_database

from app.journey_examples import pdf
from app.staff_access import provision

HOSPITALS = {"north": "North Bridge Demo Hospital", "south": "South Bridge Demo Hospital"}
USERS = ("coordinator", "supervisor")


@contextmanager
def replica(databases):
    config = {
        slug: {"hospital_name": HOSPITALS[slug], "database_url_env": slug.upper() + "_DATABASE_URL"}
        for slug in databases
    }
    env = os.environ | {config[slug]["database_url_env"]: dsn for slug, dsn in databases.items()}
    env.update(WORKSPACE_HOSPITALS=json.dumps(config), WORKSPACE_AUTH_MODE="staff", WORKSPACE_SEED_DEMO="0")
    env.pop("DATABASE_URL", None)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.workspace_server:app",
                "--fd",
                str(sock.fileno()),
                "--log-level",
                "error",
                "--no-access-log",
            ],
            cwd=ROOT,
            env=env,
            pass_fds=(sock.fileno(),),
        )
        try:
            with httpx.Client(base_url=origin, trust_env=False) as probe:
                deadline = monotonic() + 30
                while monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Hospital server exited during startup")
                    try:
                        if probe.get("/api/hospitals", timeout=1).json().get("mode") == "multi":
                            break
                    except httpx.TransportError:
                        pass
                    sleep(0.1)
                else:
                    raise RuntimeError("Hospital directory did not become ready")
            yield origin
        finally:
            process.terminate()
            try:
                process.wait(15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


class Audit:
    def __init__(self, clients):
        self.clients = clients
        self.origins = []
        self.statuses = Counter()
        self.races = {}
        self.lock = Lock()

    def fetch(self, user, worker, method, path, allowed, **kwargs):
        response = self.clients[user].request(method, self.origins[worker] + path, **kwargs)
        with self.lock:
            self.statuses[response.status_code] += 1
        assert response.status_code in allowed, (method, path, response.status_code, response.text[:200])
        return response

    def login(self, slug, user, password):
        prefix = f"/h/{slug}/api"
        r = self.fetch(
            user, 0, "POST", prefix + "/access/login", [200], json={"username": user, "password": password}
        )
        assert r.json()["actor"] == f"{slug} {user}" and r.json()["hospital_name"] == HOSPITALS[slug]
        assert any(c.path == prefix and c.name == "zu_staff_session" for c in r.cookies.jar)

    def race(self, operation, action, expected):
        barrier = Barrier(2)

        def run(i):
            barrier.wait(10)
            return action(i)

        with ThreadPoolExecutor(2) as lanes:
            replies = list(lanes.map(run, (0, 1)))
        actual = sorted(r.status_code for r in replies)
        assert actual == expected, (operation, actual)
        with self.lock:
            counts = self.races.setdefault(operation, Counter())
            counts["+".join(map(str, actual))] += 1
        return replies


def case_packet(slug, index):
    meta, docs, names = template("duplicate_line")
    n = index * 2 + (slug == "south")
    member, encounter = identity(n)
    form = {k: v.replace("2026-12-", "2025-12-") for k, v in meta.items() if k != "id"}
    form.update(member=member, encounter=encounter, facility=HOSPITALS[slug], confirmed="true")

    def adapt(raw):
        return (
            personalize(raw, n)
            .replace(b"2026-12-", b"2025-12-")
            .replace(b"Canal Bridge Demo Hospital", HOSPITALS[slug].encode())
        )

    uploads = {r: (names[r], adapt(data), "application/pdf") for r, data in docs.items()}
    corrected = adapt(template("aligned")[1]["bill"])
    # The payer requests the signed reissued copy, identified on each page of this example.
    records = uploads["records"][1]
    assert b"DC-RECORDS-42" in records
    reissued = records.replace(b"DC-RECORDS-42", b"DC-RECORDS-43")
    return form, uploads, corrected, reissued


def workflow(audit, slug, index):
    start = perf_counter()
    base = f"/h/{slug}/api/discharge"
    form, uploads, corrected, reissued = case_packet(slug, index)
    key = f"shared-intake-{index}"

    def post(user, worker, path, success, **kwargs):
        return audit.fetch(user, worker, "POST", path, success, **kwargs)

    res = audit.race(
        "keyed_intake",
        lambda i: post(USERS[0], i, base, [201], headers={"Idempotency-Key": key}, data=form, files=uploads),
        [201, 201],
    )
    claim = res[0].json()
    assert claim["id"] == res[1].json()["id"] and claim["status"] == "needs_review"
    ident = claim["id"]
    path = base + "/" + ident

    def replace(user, worker, revision, role, data):
        return post(
            user,
            worker,
            path + "/documents",
            [200, 412],
            headers={"If-Match": f'"{revision}"'},
            data={"confirmed": "true"},
            files={role: (role + ".pdf", data, "application/pdf")},
        )

    def approve(revision, label):
        def review(i):
            return post(USERS[i], i, path + "/approve", [200, 409], headers={"If-Match": f'"{revision}"'}, json={})

        approvals = audit.race(label, review, [200, 409])
        winner = next(i for i, r in enumerate(approvals) if r.status_code == 200)
        assert approvals[winner].json()["reviewer"] == f"{slug} {USERS[winner]}"
        assert review(winner).status_code == 200

    def event(i, rev, version, action, fields, files=None):
        return post(
            USERS[i],
            i,
            path + "/workflow",
            [200, 409],
            headers={"If-Match": f'"{rev}"'},
            data={"action": action, "workflow_version": str(version)} | fields,
            files=files,
        )

    def submit(i, rev):
        return event(i, rev, 0, "submission", {"reference": f"SUB-{index}-{rev}", "channel": "Synthetic portal"})

    def reply(rev, outcome, text):
        raw = pdf(
            [
                "Synthetic payer correspondence",
                "Member: " + form["member"],
                "Encounter: " + form["encounter"],
                text,
            ]
        )
        fields = {"reference": f"R-{index}-{rev}", "outcome": outcome, "confirmed": "true", "terms": text}
        if outcome == "confirmed":
            fields.update(currency="THB", amount="80000")
        response = event(0, rev, 1, "reply", fields, {"file": ("reply.pdf", raw, "application/pdf")})
        assert response.status_code == 200
        return response.json()["events"][-1]["source_url"], raw

    revisions = audit.race("correct_held_bill", lambda i: replace(USERS[i], i, 1, "bill", corrected), [200, 412])
    r2 = next(r.json() for r in revisions if r.status_code == 200)
    assert r2["revision"] == 2 and r2["status"] == "ready_for_review"
    approve(2, "approve_revision_2")
    audit.race("submit_revision_2", lambda i: submit(i, 2), [200, 409])
    query_url, query_pdf = reply(2, "query", "Please supply the signed reissued operative record DC-RECORDS-43.")
    revisions = audit.race(
        "supply_queried_records", lambda i: replace(USERS[i], i, 2, "records", reissued), [200, 412]
    )
    r3 = next(r.json() for r in revisions if r.status_code == 200)
    assert r3["revision"] == 3 and r3["status"] == "ready_for_review" and r3["workflow_version"] == 0
    approve(3, "approve_revision_3")
    audit.race("resubmit_revision_3", lambda i: submit(i, 3), [200, 409])
    letter_url, letter = reply(3, "confirmed", "THB 80,000 confirmed.")
    payment = {"reference": f"PAY-{index}", "currency": "THB", "amount": "80000", "notes": "Synthetic receipt"}
    payments = audit.race("record_payment", lambda i: event(i, 3, 2, "payment", payment), [200, 409])
    settled = next(r.json() for r in payments if r.status_code == 200)
    assert event(0, 3, 3, "payment", payment).status_code == 409
    assert settled["settlement_status"] == "paid" and settled["case_paid_by_currency"] == {"THB": 8000000}
    assert [e["kind"] for e in settled["events"]] == ["submission", "reply", "payment"]
    assert [r["revision"] for r in settled["history"]] == [3, 2, 1]
    assert all(s["url"].startswith(base + "/") for s in settled["sources"])
    archive = settled["events"][0]["source_url"]
    packet = audit.fetch(USERS[0], 1, "GET", archive, [200]).content
    attachments = PdfReader(BytesIO(packet)).attachments
    expected = {r: blob for r, (_, blob, _) in uploads.items()} | {"bill": corrected, "records": reissued}
    assert sorted(sha256(b).hexdigest() for group in attachments.values() for b in group) == sorted(
        sha256(b).hexdigest() for b in expected.values()
    )
    evidence = [
        (claim["sources"][0]["url"], claim["sources"][0]["sha256"]),
        (query_url, sha256(query_pdf).hexdigest()),
        (letter_url, sha256(letter).hexdigest()),
        (archive, sha256(packet).hexdigest()),
    ]
    return {"slug": slug, "id": ident, "path": path, "evidence": evidence, "seconds": perf_counter() - start}


def check_isolation(audit, cases):
    for c in cases:
        slug, path = c["slug"], c["path"]
        other = "south" if slug == "north" else "north"

        def swapped(p, slug=slug, other=other):
            assert p.startswith(f"/h/{slug}/api/")
            return p.replace(f"/h/{slug}/", f"/h/{other}/", 1)

        case = audit.fetch(USERS[0], 1, "GET", path, [200]).json()
        assert case["id"] == c["id"] and case["settlement_status"] == "paid"
        audit.fetch(USERS[0], 1, "GET", swapped(path), [404])
        audit.fetch(USERS[0], 1, "GET", swapped(path) + "/export?revision=3", [404])
        audit.fetch(USERS[1], 0, "POST", swapped(path) + "/approve", [404], headers={"If-Match": '"3"'}, json={})
        for source, digest in c["evidence"]:
            assert sha256(audit.fetch(USERS[0], 0, "GET", source, [200]).content).hexdigest() == digest
            audit.fetch(USERS[0], 1, "GET", swapped(source), [404])
    for slug in HOSPITALS:
        result = audit.fetch(USERS[0], 0, "GET", f"/h/{slug}/api/discharge", [200]).json()
        assert {r["id"] for r in result} == {c["id"] for c in cases if c["slug"] == slug}


def free_text_review(audit, slug, index):
    form, uploads, corrected, _ = case_packet(slug, index)
    uploads["bill"] = ("corrected.pdf", corrected, "application/pdf")
    writer = PdfWriter(clone_from=BytesIO(uploads["records"][1]))
    page = writer.pages[0]
    content = DecodedStreamObject()
    content.set_data(
        page.get_contents().get_data()
        + b"\nBT /F1 9 Tf 42 50 Td (Addendum: operative services were inpatient.) Tj ET\n"
    )
    page.replace_contents(content)
    buffer = BytesIO()
    writer.write(buffer)
    uploads["records"] = ("free-text.pdf", buffer.getvalue(), "application/pdf")
    path = f"/h/{slug}/api/discharge"
    held = audit.fetch(USERS[0], 0, "POST", path, [201], data=form, files=uploads).json()
    assert held["status"] == "needs_review" and "unrecognized_layout" in {f["code"] for f in held["findings"]}
    audit.fetch(
        USERS[1], 1, "POST", path + "/" + held["id"] + "/approve", [409], headers={"If-Match": '"1"'}, json={}
    )
    return {"status": held["status"], "finding": "unrecognized_layout", "approval_http": 409}


def admission_check(audit, slug):
    other = "south" if slug == "north" else "north"
    base = f"/h/{slug}/api/cases"
    fields = {
        "member": "DEMO-Z002",
        "insurer": "Alder Transit Cover",
        "policy_edition": "AT-2026.1",
        "procedure": "Wrist fracture fixation",
        "admission_date": "2026-11-25",
        "confirmed": "true",
    }
    fixture = ROOT / "fixtures"
    paths = {
        "plan": fixture / "cases/Z002/plan.pdf",
        "estimate": fixture / "cases/Z002/estimate.pdf",
        "policy": fixture / "policies/alder.pdf",
    }
    files = {r: (p.name, p.read_bytes(), "application/pdf") for r, p in paths.items()}
    case = audit.fetch(
        USERS[0], 0, "POST", base, [201], data=fields, files=files, headers={"Idempotency-Key": "admission-replay"}
    ).json()
    other_path = f"/h/{other}/api/cases/" + case["id"]
    audit.fetch(USERS[0], 1, "GET", other_path, [404])
    audit.fetch(
        USERS[0],
        1,
        "POST",
        other_path + "/estimate",
        [404],
        headers={"If-Match": '"1"'},
        files={"file": files["estimate"]},
        data={"confirmed": "true"},
    )
    for source in case["sources"]:
        url = source["url"]
        assert url.startswith(base + "/")
        assert audit.fetch(USERS[0], 1, "GET", url, [200]).content == files[source["role"]][1]
        audit.fetch(USERS[1], 0, "GET", url.replace(f"/h/{slug}/", f"/h/{other}/", 1), [404])
    return {"intake": 201, "originals_checked": len(case["sources"]), "foreign_revision": 404}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--cases-per-hospital", type=int, default=50)
    parser.add_argument("--concurrent-cases", type=int, default=8)
    parser.add_argument("--out", type=Path, default=ROOT / ".local/testing-audit/hospital-concurrency.json")
    args = parser.parse_args()
    if min(args.cases_per_hospital, args.concurrent_cases) < 1:
        parser.error("Case counts must be positive")
    with temporary_database() as dsn, ExitStack() as stack:
        databases = {slug: make_conninfo(dsn, dbname=slug) for slug in HOSPITALS}
        with psycopg.connect(dsn, autocommit=True) as db:
            for slug in HOSPITALS:
                db.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(slug)))
        clients = {u: stack.enter_context(httpx.Client(trust_env=False, timeout=60)) for u in USERS}
        audit = Audit(clients)
        passwords = {(s, u): secrets.token_urlsafe(24) for s in HOSPITALS for u in USERS}
        with ExitStack() as run:
            audit.origins = [run.enter_context(replica(databases)) for _ in range(2)]
            for (slug, user), pwd in passwords.items():
                provision(databases[slug], user, f"{slug} {user}", pwd)
            audit.login("north", USERS[0], passwords["north", USERS[0]])
            audit.fetch(USERS[0], 0, "GET", "/h/south/api/discharge", [401])
            audit.fetch(
                USERS[0],
                1,
                "POST",
                "/h/south/api/access/login",
                [401],
                json={"username": USERS[0], "password": passwords["north", USERS[0]]},
            )
            for (slug, user), password in passwords.items():
                if (slug, user) != ("north", USERS[0]):
                    audit.login(slug, user, password)
                assert (
                    audit.fetch(user, 1, "GET", f"/h/{slug}/api/access/session", [200]).json()["actor"]
                    == f"{slug} {user}"
                )
            audit.fetch(USERS[0], 0, "GET", "/api/discharge", [404])
            tasks = [(s, i) for i in range(args.cases_per_hospital) for s in HOSPITALS]
            started = perf_counter()
            with ThreadPoolExecutor(args.concurrent_cases) as jobs:
                cases = list(jobs.map(lambda pair: workflow(audit, *pair), tasks))
            elapsed = perf_counter() - started
            check_isolation(audit, cases)
        with ExitStack() as run:
            audit.origins = [run.enter_context(replica(databases)) for _ in range(2)]
            for slug in HOSPITALS:
                assert (
                    audit.fetch(USERS[0], 1, "GET", f"/h/{slug}/api/access/session", [200]).json()["actor"]
                    == f"{slug} {USERS[0]}"
                )
            audit.fetch(USERS[0], 1, "POST", "/h/north/api/access/logout", [200])
            audit.fetch(USERS[0], 0, "GET", "/h/north/api/discharge", [401])
            assert (
                len(audit.fetch(USERS[0], 0, "GET", "/h/south/api/discharge", [200]).json())
                == args.cases_per_hospital
            )
            audit.login("north", USERS[0], passwords["north", USERS[0]])
            check_isolation(audit, cases)
            free_text = {slug: free_text_review(audit, slug, args.cases_per_hospital) for slug in HOSPITALS}
            admissions = {slug: admission_check(audit, slug) for slug in HOSPITALS}
        expected = {
            "discharge_cases": 1,
            "discharge_revisions": 3,
            "discharge_approvals": 2,
            "discharge_events": 5,
            "discharge_intake_requests": 1,
        }
        inventory = {}
        for slug, dsn in databases.items():
            with psycopg.connect(dsn) as db:
                inventory[slug] = {
                    key: db.execute("SELECT count(*) FROM zeroupfront_demo." + key).fetchone()[0]
                    for key in expected
                }
                assert inventory[slug] == {
                    k: n * args.cases_per_hospital + (k in {"discharge_cases", "discharge_revisions"})
                    for k, n in expected.items()
                }
        durations = sorted(c["seconds"] for c in cases)
        report = {
            "cases_per_hospital": args.cases_per_hospital,
            "concurrent_cases": args.concurrent_cases,
            "workers": 2,
            "post_restart_workers": 2,
            "workflow_seconds": round(elapsed, 3),
            "completed_workflows_per_second": round(len(cases) / elapsed, 2),
            "workflow_p50_seconds": round(median(durations), 3),
            "workflow_p95_seconds": round(durations[ceil(len(durations) * 0.95) - 1], 3),
            "observed_http_status_counts": dict(audit.statuses),
            "race_outcomes": audit.races,
            "additional_free_text_cases": free_text,
            "admissions": admissions,
            "inventory": inventory,
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
