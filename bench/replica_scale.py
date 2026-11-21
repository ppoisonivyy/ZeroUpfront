"""Compare one, two and four staff-mode HTTP processes against a restored synthetic discharge database."""

import json
import platform
import random
import secrets
import subprocess
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from hashlib import sha256
from io import BytesIO
from math import ceil
from pathlib import Path
from statistics import median
from threading import Barrier
from time import perf_counter

import psycopg
from discharge_scale import BASE, identity, ok
from pypdf import PdfReader
from workspace_http import ROOT, server, temporary_database

from app.staff_access import provision


def clinic_data(dsn):
    with psycopg.connect(dsn) as db:
        db.execute("SET search_path TO zeroupfront_demo,public")
        rows = db.execute("""
            SELECT c.id, c.head, r.evidence->>'member', s.digest,
                   coalesce(a.actor IS NOT NULL,false) AS approved
            FROM discharge_cases c JOIN discharge_revisions r
              ON r.case_id=c.id AND r.revision=c.head
            JOIN discharge_sources s ON s.case_id=c.id AND s.revision=c.head AND s.role='bill'
            LEFT JOIN discharge_approvals a ON a.case_id=c.id AND a.revision=c.head
            ORDER BY r.evidence->>'member'
        """).fetchall()
        first = db.execute("""
            SELECT c.id FROM discharge_cases c JOIN discharge_revisions r
              ON r.case_id=c.id AND r.revision=c.head
            WHERE r.evidence->>'status'='needs_review'
            ORDER BY r.evidence->>'discharge_date',c.id LIMIT 25
        """).fetchall()
    assert len(rows) == 10000 and len(first) == 25
    return rows, [row[0] for row in first]


def request(client, kind, row, first):
    ident, revision, member, digest, _ = row
    if kind == "worklist":
        result = ok(client.get(BASE + "/worklist"))
        assert result["total"] == result["counts"]["all"] == 10000
        assert [r["id"] for r in result["items"]] == first
    elif kind == "member_search":
        result = ok(
            client.post(
                BASE + "/worklist/search",
                json={
                    "search": member,
                    "queue": "all",
                    "page": 1,
                    "page_size": 25,
                },
            )
        )
        assert result["total"] == 1 and result["counts"]["all"] == 10000
        assert [(r["id"], r["member"]) for r in result["items"]] == [(ident, member)]
    elif kind == "detail":
        result = ok(client.get(f"{BASE}/{ident}"))
        assert (result["id"], result["revision"], result["member"]) == (
            ident,
            revision,
            member,
        )
        assert (
            next(s["sha256"] for s in result["sources"] if s["role"] == "bill")
            == digest
        )
    else:
        response = client.get(f"{BASE}/{ident}/export", params={"revision": revision})
        response.raise_for_status()
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(
            b"%PDF"
        ) and response.content.rstrip().endswith(b"%%EOF")
        return response.content


def batch(clients, kind, inputs, first, workers):
    def one(index_row):
        idx, row = index_row
        start = perf_counter()
        request(clients[idx % len(clients)], kind, row, first)
        return (perf_counter() - start) * 1000

    start = perf_counter()
    with ThreadPoolExecutor(workers) as pool:
        samples = list(pool.map(one, enumerate(inputs)))
    return samples, perf_counter() - start


def stats(samples, seconds):
    values = sorted(samples)
    return {
        "requests": len(values),
        "p50_ms": round(median(values), 2),
        "p95_ms": round(values[ceil(0.95 * len(values)) - 1], 2),
        "requests_per_s": round(len(values) / seconds, 2),
    }


def verify_replicas(clients, reviewed_row):
    ident, revision, member, digest, _ = reviewed_row
    # Two coordinators racing from the same version should create one submission.
    barrier = Barrier(2)
    path = f"{BASE}/{ident}"

    def submit(i):
        barrier.wait(timeout=10)
        return (
            clients[i]
            .post(
                path + "/workflow",
                headers={"If-Match": f'"{revision}"'},
                data={
                    "action": "submission",
                    "workflow_version": "0",
                    "channel": "Simulation",
                    "reference": f"Replica audit {i}",
                },
            )
            .status_code
        )

    with ThreadPoolExecutor(2) as pool:
        codes = sorted(pool.map(submit, (0, 1)))
    assert codes == [200, 409], codes
    for client in clients:
        row = ok(client.get(path))
        assert (
            row["member"] == member
            and row["insurer_status"] == "submitted"
            and row["workflow_version"] == 1
        )
        source = client.get(path + f"/revisions/{revision}/sources/bill")
        source.raise_for_status()
        assert sha256(source.content).hexdigest() == digest
    ok(clients[-1].post("/api/access/logout"))
    denied = [c.get(path).status_code for c in clients]
    assert denied == [401] * len(clients)
    return {
        "same_version_submission_statuses": codes,
        "consistent_reads": len(clients),
        "logout_denied_statuses": denied,
    }


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dump",
        type=Path,
        default=ROOT / ".local/testing-audit/db-scale/synthetic-discharge.dump",
    )
    parser.add_argument(
        "--requests", type=int, default=96, help="Per workload, replica count and round"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Total client concurrency regardless of replica count",
    )
    parser.add_argument(
        "--out", type=Path, default=ROOT / ".local/testing-audit/replica-scale.json"
    )
    args = parser.parse_args()
    if (
        args.requests < 4
        or args.requests % 4
        or args.concurrency < 1
        or not args.dump.is_file()
    ):
        parser.error(
            "Provide the 10,000-claim dump, positive concurrency, and a request count divisible by four."
        )
    results = {
        "host": platform.platform(),
        "claims": 10000,
        "total_concurrency": args.concurrency,
        "requests_per_cell_per_round": args.requests,
        "rounds": [],
    }
    with temporary_database() as dsn, ExitStack() as stack:
        subprocess.run(
            [
                "pg_restore",
                "--no-acl",
                "--no-owner",
                "--exit-on-error",
                "-d",
                dsn,
                str(args.dump),
            ],
            check=True,
        )
        with psycopg.connect(dsn, autocommit=True) as db:
            db.execute("ANALYZE")
            results["postgres"] = db.execute("SHOW server_version").fetchone()[0]
        rows, first = clinic_data(dsn)
        approved = [r for r in rows if r[4]]
        race_row = next(r for r in approved if r[2] == identity(5)[0])
        clients = [
            stack.enter_context(server(dsn, False, auth_mode="staff")) for _ in range(4)
        ]
        username, password = "replica-audit", secrets.token_urlsafe(32)
        provision(dsn, username, "Synthetic coordinator", password)
        ok(
            clients[0].post(
                "/api/access/login", json={"username": username, "password": password}
            )
        )
        for client in clients[1:]:
            client.cookies.update(clients[0].cookies)
        for client in clients:
            assert ok(client.get("/api/access/session"))["username"] == username
            request(client, "worklist", race_row, first)
            request(client, "member_search", race_row, first)
            request(client, "detail", race_row, first)
            generated = request(client, "export", race_row, first)
            attachments = PdfReader(BytesIO(generated)).attachments
            assert any(
                sha256(blob).hexdigest() == race_row[3]
                for blobs in attachments.values()
                for blob in blobs
            )
        kinds = ("worklist", "member_search", "detail", "export")
        combined = {}
        for index, config in enumerate(((1, 2, 4), (2, 4, 1), (4, 1, 2))):
            rng = random.Random(20261121 + index)
            inputs = {
                k: rng.choices(approved if k == "export" else rows, k=args.requests)
                for k in kinds
            }
            for replicas in config:
                for kind in kinds:
                    times, seconds = batch(
                        clients[:replicas], kind, inputs[kind], first, args.concurrency
                    )
                    cell = stats(times, seconds)
                    results["rounds"].append(
                        dict(round=index + 1, replicas=replicas, workload=kind, **cell)
                    )
                    durations, elapsed = combined.setdefault((replicas, kind), ([], []))
                    durations.extend(times)
                    elapsed.append(seconds)
                print(
                    f"Verified round {index + 1} with {replicas} active API processes.",
                    flush=True,
                )
        results["cells"] = [
            dict(replicas=n, workload=k, **stats(t, sum(sec)))
            for (n, k), (t, sec) in sorted(combined.items())
        ]
        results["cross_replica_checks"] = verify_replicas(clients, race_row)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results["cells"]), flush=True)


if __name__ == "__main__":
    main()
