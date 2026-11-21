"""Probe encounter binding, expired worker leases and revision-specific export handles on disposable Postgres."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from threading import Barrier, Event
from time import monotonic, sleep

import psycopg
from psycopg.types.json import Jsonb

from case_revision import (
    ORIGINAL, PATHS, PLAN, POLICY, REVISED, contains_identifier, current,
    precheck, read_fixture, read_page, require, temporary_database, upload,
)

DDL = """
ALTER TABLE cases ADD COLUMN hospital text NOT NULL, ADD COLUMN encounter text NOT NULL;
ALTER TABLE revisions ADD COLUMN lease_until timestamptz;
CREATE TABLE encounter_bindings (
    hospital text NOT NULL, estimate_digest text NOT NULL, encounter text NOT NULL, verified_reference text NOT NULL,
    PRIMARY KEY(hospital, estimate_digest)
);
CREATE TABLE reviews (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, case_id text NOT NULL, rev integer NOT NULL, attempt integer NOT NULL,
    UNIQUE(case_id, rev, attempt), FOREIGN KEY (case_id, rev) REFERENCES revisions
);
CREATE TABLE exports (
    review_id bigint PRIMARY KEY REFERENCES reviews, artifact_digest text NOT NULL
);
"""


def create_case(db, case, encounter, hospital):
    db.execute('INSERT INTO cases(id,member,hospital,encounter) VALUES (%s,%s,%s,%s)',
               (case, 'DEMO-Z002', hospital, encounter))


def record_binding(db, hospital, estimate, encounter):
    # Test input from a simulated verified hospital record. Never derive this link from the selected case alone.
    db.execute('INSERT INTO encounter_bindings VALUES (%s,%s,%s,%s)',
               (hospital, estimate, encounter, 'verified-record-' + encounter))


def claim_guarded(db, case, rev, seconds=10):
    record = db.execute("""
        UPDATE revisions SET state='running', attempt=attempt+1,
            lease_until=clock_timestamp()+(%s * interval '1 second')
        WHERE case_id=%s AND rev=%s AND (state IN ('queued','failed','needs_binding')
                OR (state='running' AND lease_until <= clock_timestamp()))
        RETURNING attempt""", (seconds, case, rev)).fetchone()
    return record[0] if record else None


def assess(db, case, rev):
    member, plan_id, estimate_id = db.execute("""
        SELECT c.member,r.plan,r.estimate FROM revisions r JOIN cases c ON r.case_id=c.id
        WHERE c.id=%s AND r.rev=%s""", (case, rev)).fetchone()
    plan, _ = read_page(db, case, plan_id)
    estimate, _ = read_page(db, case, estimate_id)
    require(all(contains_identifier(d.text, member) and contains_identifier(d.text, POLICY['version'])
                for d in (plan, estimate)), 'unexpected fixture identity')
    facts = read_fixture(plan, estimate)
    outcome, clause = precheck(POLICY, facts)
    return dict(estimate=estimate_id, plan=plan_id, total=facts.total_thb, itemized=facts.itemized,
                outcome=outcome, clause=clause)


def complete(db, case, rev, token, result):
    with db.transaction():
        head, = db.execute('SELECT head FROM cases WHERE id=%s FOR UPDATE', (case,)).fetchone()
        if head != rev:
            return 'stale_revision'
        row = db.execute("""
            UPDATE revisions r SET
                state=CASE WHEN x.bound THEN 'done' ELSE 'needs_binding' END,
                result=CASE WHEN x.bound THEN %s::jsonb ELSE NULL END,
                finished=nextval('finish_order'), lease_until=NULL
            FROM (
                SELECT EXISTS (
                    SELECT 1 FROM cases c JOIN revisions rr ON rr.case_id=c.id AND rr.rev=c.head
                    JOIN encounter_bindings b ON b.hospital=c.hospital AND b.estimate_digest=rr.estimate
                                             AND b.encounter=c.encounter
                    WHERE c.id=%s
                ) AS bound
            ) x
            WHERE r.case_id=%s AND r.rev=%s AND r.attempt=%s AND r.state='running'
                AND r.lease_until > clock_timestamp() AND r.plan=%s AND r.estimate=%s
            RETURNING r.state""", (Jsonb(result), case, case, rev, token, result['plan'], result['estimate'])).fetchone()
        return row[0] if row else 'rejected_attempt'


def approve(db, case, rev, attempt):
    with db.transaction():
        db.execute('SELECT id FROM cases WHERE id=%s FOR UPDATE', (case,)).fetchone()
        review = db.execute("""
            INSERT INTO reviews (case_id,rev,attempt)
            SELECT c.id,r.rev,r.attempt FROM cases c JOIN revisions r ON (r.case_id,r.rev)=(c.id,c.head)
            WHERE c.id=%s AND r.rev=%s AND r.attempt=%s AND r.state='done'
                AND r.result->>'outcome'='ready_for_review'
            ON CONFLICT(case_id,rev,attempt) DO UPDATE SET attempt=excluded.attempt RETURNING id""",
            (case, rev, attempt)).fetchone()
        return review[0] if review else None


def publish(db, case, review_id, artifact_digest):
    with db.transaction():
        db.execute('SELECT id FROM cases WHERE id=%s FOR UPDATE', (case,)).fetchone()
        eligible = db.execute("""
            SELECT a.id FROM cases c JOIN revisions r ON (r.case_id,r.rev)=(c.id,c.head)
            JOIN reviews a ON (a.case_id,a.rev,a.attempt)=(c.id,c.head,r.attempt)
            WHERE c.id=%s AND a.id=%s AND r.state='done' AND r.result->>'outcome'='ready_for_review'""",
            (case, review_id)).fetchone()
        if not eligible:
            return False
        db.execute('INSERT INTO exports VALUES (%s,%s) ON CONFLICT DO NOTHING', (review_id, artifact_digest))
        return db.execute('SELECT artifact_digest=%s FROM exports WHERE review_id=%s',
                          (artifact_digest, review_id)).fetchone()[0]


def current_export(db, case):
    return db.execute("""
        SELECT e.artifact_digest FROM cases c JOIN revisions r ON (r.case_id,r.rev)=(c.id,c.head)
        JOIN reviews a ON (a.case_id,a.rev,a.attempt)=(c.id,r.rev,r.attempt)
        JOIN exports e ON e.review_id=a.id
        WHERE c.id=%s AND r.state='done' AND r.result->>'outcome'='ready_for_review'""", (case,)).fetchone()


def historical_export(db, case, rev):
    return db.execute("""
        SELECT e.artifact_digest FROM reviews a JOIN exports e ON e.review_id=a.id
        WHERE a.case_id=%s AND a.rev=%s""", (case, rev)).fetchone()


def guard_run(db, case, rev):
    return complete(db, case, rev, claim_guarded(db, case, rev), assess(db, case, rev))


def test_identity(db, hospital):
    # Same member reference and policy, different hospital encounter numbers.
    a, b = hospital + '-a', hospital + '-b'
    for case, encounter in ((a, 'visit-a'), (b, 'visit-b')):
        create_case(db, case, encounter, hospital)
        upload(db, case, 'estimate', 0, PLAN, REVISED)
        require(guard_run(db, case, 1) == 'needs_binding', 'unbound estimate approved')
        require(current(db, case) == (1, 'needs_binding', None), 'unbound case exposed usable result')
    record_binding(db, hospital, REVISED, 'visit-a')
    require(guard_run(db, a, 1) == 'done' and current(db, a)[2]['outcome'] == 'ready_for_review',
            'verified encounter not recognized')
    require(guard_run(db, b, 1) == 'needs_binding', 'same member reused another encounter binding')
    third = hospital + '-c'
    create_case(db, third, 'visit-a', hospital + '-other')
    upload(db, third, 'estimate', 0, PLAN, REVISED)
    require(guard_run(db, third, 1) == 'needs_binding', 'encounter binding crossed hospitals')


def run_connection(dsn, task):
    with psycopg.connect(dsn, autocommit=True) as db:
        return task(db)


def test_lease(db, dsn, pool, name):
    case = name + '-case'
    create_case(db, case, 'visit', name)
    upload(db, case, 'estimate', 0, PLAN, REVISED)
    record_binding(db, name, REVISED, 'visit')
    result = assess(db, case, 1)
    # The first claim transaction commits. Its worker disconnects before publishing.
    old = pool.submit(run_connection, dsn, lambda conn: claim_guarded(conn, case, 1, .025)).result()
    require(old == 1, 'incorrect initial fence')
    end = monotonic() + 3
    while db.execute("""SELECT lease_until>clock_timestamp() FROM revisions
                        WHERE case_id=%s AND rev=1""", (case,)).fetchone()[0]:
        require(monotonic() < end, 'server lease failed to expire')
        sleep(.001)
    boundary = Barrier(2)
    def recover(conn):
        boundary.wait(timeout=5)
        return claim_guarded(conn, case, 1)
    def zombie(conn):
        boundary.wait(timeout=5)
        return complete(conn, case, 1, old, result)
    reclaimed, callback = (pool.submit(run_connection, dsn, task) for task in (recover, zombie))
    token = reclaimed.result()
    require(token == old + 1 and callback.result() == 'rejected_attempt', 'expired attempt published')
    require(complete(db, case, 1, token, result) == 'done', 'new worker failed to publish')
    require(complete(db, case, 1, old, result) == 'rejected_attempt', 'old callback replaced completed result')
    versions = db.execute('SELECT attempt,state FROM revisions WHERE case_id=%s', (case,)).fetchall()
    require(versions == [(token, 'done')], 'invalid final attempt')
    require(current(db, case) == (1, 'done', result), 'wrong recovered decision')


def test_export(db, dsn, pool, name):
    case = name + '-case'
    create_case(db, case, 'visit', name)
    record_binding(db, name, REVISED, 'visit')
    upload(db, case, 'first', 0, PLAN, REVISED)
    require(guard_run(db, case, 1) == 'done', 'missing checked result')
    first = approve(db, case, 1, 1)
    require(first is not None, 'failed to approve current checked result')
    artifact = sha256(f'fixture artifact {case} {first}'.encode()).hexdigest()
    require(publish(db, case, first, artifact) and current_export(db, case) == (artifact,), 'missing current export')
    require(not publish(db, case, first, 'different-bytes'), 'same review changed existing artifact')
    saw_old = Event()
    release = Event()
    def late_writer(conn):
        require(current_export(conn, case) == (artifact,), 'render started on wrong revision')
        saw_old.set()
        require(release.wait(5), 'render barrier timed out')
        return publish(conn, case, first, artifact)
    pending = pool.submit(run_connection, dsn, late_writer)
    try:
        require(saw_old.wait(5), 'renderer did not start')
        upload(db, case, 'replacement', 1, PLAN, ORIGINAL)
    finally:
        release.set()
    require(not pending.result() and approve(db, case, 1, 1) is None, 'stale approval or export permitted')
    require(current_export(db, case) is None, 'stale artifact visible on current route')
    require(historical_export(db, case, 1) == (artifact,), 'previously issued artifact lost')
    upload(db, case, 'reinstated', 2, PLAN, REVISED)
    require(guard_run(db, case, 3) == 'done' and current_export(db, case) is None,
            'identical bytes accidentally revived an old review')
    third = approve(db, case, 3, 1)
    require(third is not None and first != third, 'latest revision did not get an independent review')
    new_artifact = sha256(f'fixture artifact {case} {third}'.encode()).hexdigest()
    require(publish(db, case, third, new_artifact), 'latest export publication failed')
    require(current_export(db, case) == (new_artifact,) and historical_export(db, case, 1) == (artifact,),
            'historical and active artifact mixed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repetitions', type=int, default=40)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error('repetitions must be positive')
    for digest in (PLAN, ORIGINAL, REVISED):
        require(sha256(PATHS[digest].read_bytes()).hexdigest() == digest, 'fixture changed')
    with temporary_database() as dsn, psycopg.connect(dsn, autocommit=True) as db, ThreadPoolExecutor(max_workers=2) as pool:
        db.execute((Path(__file__).parent / 'case_revision.sql').read_text())
        db.execute(DDL)
        print(db.execute('SHOW server_version').fetchone()[0])
        for i in range(args.repetitions):
            test_identity(db, f'identity-{i}')
            test_lease(db, dsn, pool, f'lease-{i}')
            test_export(db, dsn, pool, f'export-{i}')
        for name in ('same member with multiple encounters and hospital-scoped binding',
                     'expired lease/reclaim racing delayed callback', 'approval and export during replacement'):
            print(f'{name}: {args.repetitions}/{args.repetitions} passed')


if __name__ == '__main__':
    main()
