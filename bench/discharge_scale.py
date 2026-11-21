"""Populate a disposable PostgreSQL database over HTTP and measure verified discharge requests."""

import json
import platform
import random
import subprocess
import sys
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from math import ceil
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

import psycopg
from psycopg.conninfo import make_conninfo
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject
from workspace_http import ROOT, server, temporary_database

sys.path.insert(0, str(ROOT))
from app.discharge_claim import load_discharge_fixture
from app.journey_examples import pdf

BASE = "/api/discharge"
MEMBER = "EXAMPLE-2402"
ENCOUNTER = "EXAMPLE-VISIT-42"
STAGES = (
    "held_duplicate",
    "held_missing",
    "held_currency",
    "ready",
    "corrected",
    "reviewed",
    "submitted",
    "decision",
    "partly_paid",
    "paid",
)


def plain(raw):
    """Flatten compressed content streams once, so equal-width ID substitutions preserve PDF offsets."""
    writer = PdfWriter(clone_from=BytesIO(raw))
    for page in writer.pages:
        stream = DecodedStreamObject()
        stream.set_data(page.get_contents().get_data())
        page.replace_contents(stream)
    out = BytesIO()
    writer.write(out)
    result = out.getvalue()
    if MEMBER.encode() not in result or ENCOUNTER.encode() not in result:
        raise ValueError("Identity is missing from the digital fixture")
    return result


@lru_cache
def template(scenario):
    meta, documents, names = load_discharge_fixture(scenario)
    return meta, {r: plain(b) for r, b in documents.items()}, names


@lru_cache
def letter_template():
    return plain(
        pdf(
            [
                "Synthetic payer decision",
                "Member: " + MEMBER,
                "Encounter: " + ENCOUNTER,
                "THB 80,000 approved for this synthetic packet.",
            ]
        )
    )


def identity(number):
    return f"BEN-{number:08d}", f"SCALE-V-{number:08d}"


def personalize(raw, number):
    member, encounter = identity(number)
    assert len(member) == len(MEMBER) and len(encounter) == len(ENCOUNTER)
    return raw.replace(MEMBER.encode(), member.encode()).replace(
        ENCOUNTER.encode(), encounter.encode()
    )


def ok(response):
    response.raise_for_status()
    return response.json()


@dataclass
class Claim:
    number: int
    ident: str
    revision: int
    status: str
    insurer_status: str
    settlement: str

    @property
    def path(self):
        return BASE + "/" + self.ident


def correct(client, claim):
    raw = personalize(template("aligned")[1]["bill"], claim.number)
    updated = ok(
        client.post(
            claim.path + "/documents",
            data={"confirmed": "true"},
            headers={"If-Match": f'"{claim.revision}"'},
            files={"bill": ("bill.pdf", raw, "application/pdf")},
        )
    )
    assert (
        updated["status"] == "ready_for_review"
        and updated["revision"] == claim.revision + 1
    )
    claim.revision, claim.status = updated["revision"], updated["status"]
    return updated


def seed(client, number):
    stage = STAGES[number % len(STAGES)]
    scenario = {
        "held_duplicate": "duplicate_line",
        "held_missing": "missing_records",
        "held_currency": "mixed_currency",
        "corrected": "duplicate_line",
    }.get(stage, "aligned")
    meta, docs, names = template(scenario)
    member, encounter = identity(number)
    form = {k: v for k, v in meta.items() if k != "id"} | {
        "member": member,
        "encounter": encounter,
        "confirmed": "true",
    }
    row = ok(
        client.post(
            BASE,
            data=form,
            files={
                r: (names[r], personalize(b, number), "application/pdf")
                for r, b in docs.items()
            },
        )
    )
    assert (
        row["member"] == member
        and row["encounter"] == encounter
        and row["payable_minor"] is None
    )
    expected = "ready_for_review" if scenario == "aligned" else "needs_review"
    assert row["status"] == expected, (scenario, row["findings"])
    claim = Claim(number, row["id"], 1, expected, "not_sent", "unpaid")
    if stage == "corrected":
        correct(client, claim)
    if stage in STAGES[5:]:
        headers = {"If-Match": '"1"'}
        row = ok(
            client.post(
                claim.path + "/approve",
                headers=headers,
                json={"reviewer": "Synthetic reviewer"},
            )
        )
        assert row["status"] == "staff_reviewed"
        claim.status = "staff_reviewed"

        def event(action, fields, attachment=None):
            data = {
                "action": action,
                "actor": "Synthetic reviewer",
                "workflow_version": str(row["workflow_version"]),
            } | fields
            return ok(
                client.post(
                    claim.path + "/workflow",
                    headers=headers,
                    data=data,
                    files=attachment,
                )
            )

        if stage in STAGES[6:]:
            row = event(
                "submission", {"reference": f"SUB-{number}", "channel": "Simulation"}
            )
            assert row["insurer_status"] == "submitted"
        if stage in STAGES[7:]:
            row = event(
                "reply",
                {
                    "reference": f"R-{number}",
                    "confirmed": "true",
                    "outcome": "partial",
                    "terms": "THB 80,000 approved for this synthetic packet.",
                    "amount": "80000",
                    "currency": "THB",
                },
                {
                    "file": (
                        "reply.pdf",
                        personalize(letter_template(), number),
                        "application/pdf",
                    )
                },
            )
            assert (
                row["insurer_status"] == "partial"
                and row["settlement_status"] == "unpaid"
            )
        if stage in STAGES[8:]:
            row = event(
                "payment",
                {
                    "reference": f"P-{number}-1",
                    "amount": "50000",
                    "currency": "THB",
                    "notes": "Synthetic receipt",
                },
            )
            assert row["settlement_status"] == "partially_paid"
        if stage == "paid":
            row = event(
                "payment",
                {
                    "reference": f"P-{number}-2",
                    "amount": "30000",
                    "currency": "THB",
                    "notes": "Synthetic receipt",
                },
            )
            assert row["settlement_status"] == "paid" and row[
                "case_paid_by_currency"
            ] == {"THB": 8000000}
        claim.insurer_status, claim.settlement = (
            row["insurer_status"],
            row["settlement_status"],
        )
    return claim


def measured(fn, inputs, workers):
    def once(arg):
        start = perf_counter()
        size = fn(arg)
        return (perf_counter() - start) * 1000, size

    start = perf_counter()
    with ThreadPoolExecutor(workers) as pool:
        rows = list(pool.map(once, inputs))
    duration = perf_counter() - start
    times = sorted(row[0] for row in rows)
    return {
        "requests": len(rows),
        "workers": workers,
        "p50_ms": round(median(times), 2),
        "p95_ms": round(times[ceil(0.95 * len(times)) - 1], 2),
        "max_ms": round(times[-1], 2),
        "requests_per_s": round(len(times) / duration, 2),
        "median_response_bytes": int(median(s for _, s in rows)),
    }


def profile(client, claims, count, workers):
    expected = {
        c.ident: (c.revision, c.status, c.insurer_status, *identity(c.number))
        for c in claims
    }
    chosen = random.Random(20261121).choices(claims, k=count)
    # The source fixtures share one discharge date, so ID breaks ties inside each priority.
    ordered = sorted(
        claims,
        key=lambda c: (
            0
            if c.status == "needs_review" or c.insurer_status == "query"
            else 1
            if c.status == "ready_for_review"
            else 2,
            c.ident,
        ),
    )
    groups = {
        "all": ordered,
        "needs": [c for c in ordered if c.status == "needs_review"],
        "ready": [c for c in ordered if c.status == "ready_for_review"],
        "payer": [c for c in ordered if c.insurer_status != "not_sent"],
    }
    group_counts = {key: len(items) for key, items in groups.items()}

    def worklist(group, page, search="", selected=None):
        page_size = 25
        response = client.get(
            BASE + "/worklist",
            params={
                "page": page,
                "page_size": page_size,
                "queue": group,
                "search": search,
            },
        )
        result = ok(response)
        selection = groups[group] if selected is None else selected
        batch = selection[(page - 1) * page_size : page * page_size]
        assert result["counts"] == group_counts and result["total"] == len(selection)
        assert result["page"] == page and result["page_size"] == page_size
        assert [r["id"] for r in result["items"]] == [c.ident for c in batch]
        for row in result["items"]:
            assert expected[row["id"]] == (
                row["revision"],
                row["status"],
                row["insurer_status"],
                row["member"],
                row["encounter"],
            )
        return len(response.content)

    def first_page(_):
        return worklist("all", 1)

    def needs_page(c):
        pages = max(1, ceil(len(groups["needs"]) / 25))
        return worklist("needs", 1 + c.number % pages)

    def member_search(c):
        return worklist("all", 1, identity(c.number)[0], [c])

    def queue(_):
        response = client.get(BASE)
        rows = ok(response)
        assert len(rows) == len(expected)
        assert {
            r["id"]: (
                r["revision"],
                r["status"],
                r["insurer_status"],
                r["member"],
                r["encounter"],
            )
            for r in rows
        } == expected
        return len(response.content)

    def detail(c):
        response = client.get(c.path)
        row = ok(response)
        assert (
            row["id"],
            row["revision"],
            row["status"],
            row["insurer_status"],
            row["settlement_status"],
        ) == (c.ident, c.revision, c.status, c.insurer_status, c.settlement)
        return len(response.content)

    def original(c):
        response = client.get(c.path + f"/revisions/{c.revision}/sources/bill")
        response.raise_for_status()
        scenario = STAGES[c.number % len(STAGES)]
        source = (
            "duplicate_line"
            if scenario == "held_duplicate" and c.revision == 1
            else ("mixed_currency" if scenario == "held_currency" else "aligned")
        )
        assert response.content == personalize(template(source)[1]["bill"], c.number)
        return len(response.content)

    def change(c):
        updated = correct(client, c)
        assert updated["history"][-1]["status"] == "needs_review"
        return len(json.dumps(updated, separators=(",", ":")).encode())

    result = {}
    operations = [
        ("queue", queue),
        ("page", first_page),
        ("needs_page", needs_page),
        ("member_search", member_search),
        ("detail", detail),
        ("source", original),
    ]
    for _, fn in operations:
        fn(chosen[0])
    for concurrency in sorted({1, workers}):
        for label, fn in operations:
            result[f"{label}_{concurrency}"] = measured(fn, chosen, concurrency)
    eligible = [c for c in claims if c.number % 10 == 0 and c.revision == 1]
    if eligible:
        result["correction_" + str(workers)] = measured(
            change, eligible[:count], workers
        )
    return result


def inventory(dsn):
    with psycopg.connect(dsn) as db:
        db.execute("SET search_path TO zeroupfront_demo,public")
        return {
            table: db.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in (
                "discharge_cases",
                "discharge_revisions",
                "discharge_sources",
                "discharge_approvals",
                "discharge_events",
                "documents",
            )
        } | {
            "database_bytes": db.execute(
                "SELECT pg_database_size(current_database())"
            ).fetchone()[0],
            "unique_members": db.execute(
                "SELECT count(DISTINCT evidence->>'member') FROM discharge_revisions"
            ).fetchone()[0],
            "unique_encounters": db.execute(
                "SELECT count(DISTINCT evidence->>'encounter') FROM discharge_revisions"
            ).fetchone()[0],
            "postgres_version": db.execute("SHOW server_version").fetchone()[0],
        }


def main():
    p = ArgumentParser(description=__doc__)
    p.add_argument("--sizes", type=int, nargs="+", default=[100, 10000])
    p.add_argument("--requests", type=int, default=30)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--seed-servers", type=int, default=6)
    p.add_argument("--out", type=Path, default=ROOT / ".local/testing-audit/db-scale")
    args = p.parse_args()
    if (
        args.sizes != sorted(set(args.sizes))
        or min(args.sizes) < 10
        or max(args.sizes) > 99999999
        or min(args.requests, args.workers, args.seed_servers) < 1
    ):
        p.error("Use increasing sizes >=10 and positive request and worker counts.")
    args.out.mkdir(parents=True, exist_ok=True)
    with temporary_database() as dsn, ExitStack() as stack:
        clients = [
            stack.enter_context(server(dsn, False)) for _ in range(args.seed_servers)
        ]
        claims = []
        report = {
            "platform": platform.platform(),
            "cpu": platform.machine(),
            "runs": [],
        }
        for size in args.sizes:
            start = perf_counter()
            with ThreadPoolExecutor(args.seed_servers * 2) as pool:
                for claim in pool.map(
                    lambda i: seed(clients[i % len(clients)], i),
                    range(len(claims), size),
                ):
                    claims.append(claim)
                    if len(claims) % 1000 == 0:
                        print("Seeded", len(claims), flush=True)
            seconds = round(perf_counter() - start, 2)
            with psycopg.connect(dsn, autocommit=True) as db:
                db.execute("ANALYZE")
            metrics = profile(clients[0], claims, args.requests, args.workers)
            counts = inventory(dsn)
            assert counts["unique_members"] == size == counts["unique_encounters"]
            report["runs"].append(
                {
                    "claims": size,
                    "seed_increment_seconds": seconds,
                    "metrics": metrics,
                    "inventory": counts,
                }
            )
            print(json.dumps(report["runs"][-1]), flush=True)
        pending = Path(stack.enter_context(TemporaryDirectory(dir=args.out)))
        dump = pending / "synthetic-discharge.dump"
        subprocess.run(
            [
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--file",
                str(dump),
                "--dbname",
                dsn,
            ],
            check=True,
        )
        with psycopg.connect(dsn, autocommit=True) as db:
            db.execute("CREATE DATABASE scale_restore")
        restored = make_conninfo(dsn, dbname="scale_restore")
        subprocess.run(
            [
                "pg_restore",
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                "--dbname",
                restored,
                str(dump),
            ],
            check=True,
        )
        restored_inventory = inventory(restored)
        assert all(
            restored_inventory[k] == v
            for k, v in counts.items()
            if k != "database_bytes"
        )
        with server(restored, False) as restored_client:
            for stage in ("corrected", "paid", "held_missing"):
                sample = next(c for c in claims if STAGES[c.number % 10] == stage)
                row = ok(restored_client.get(sample.path))
                assert (
                    row["settlement_status"] == sample.settlement
                    and row["id"] == sample.ident
                )
                for source in row["sources"]:
                    response = restored_client.get(source["url"])
                    response.raise_for_status()
                    assert sha256(response.content).hexdigest() == source["sha256"]
        report["restored_inventory"] = restored_inventory
        report["dump_bytes"] = dump.stat().st_size
        results = pending / "results.json"
        results.write_text(json.dumps(report, indent=2) + "\n")
        dump.replace(args.out / dump.name)
        results.replace(args.out / results.name)
        print("Verified restore:", args.out / dump.name, flush=True)


if __name__ == "__main__":
    main()
