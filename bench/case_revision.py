"""Exercise revisioned Z002 uploads and worker races on an isolated local PostgreSQL cluster."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
import json
import os
from math import ceil
from pathlib import Path
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from time import perf_counter

import psycopg
from psycopg.types.json import Jsonb
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from check_fixtures import precheck, read_fixture
from document_text import Document, Page, contains_identifier, read_document

FOLDER = ROOT / 'fixtures/cases'
SOURCES = {
    'Z002/plan.pdf': '87d64e06e08f19d389e9b09bf2644063059c20d50462ad61818c5af4ffa768ba',
    'Z002/estimate.pdf': '22b3430c23d6f14026ee829062908a4da419ee55c23abf9598a1139a4041a333',
    'Z002/revised-estimate.pdf': '392b30b0dd378077de8828c5b008c6f5b157e7a574fe5f51cd13ea74fea237c7',
    'Z002/scanned-estimate.pdf': '92433f447fdc550bf9b72cf157a896e9f30c59cf563460051d734496af79d704',
    'Z001/plan.pdf': 'd45b5d80ae9100736cecbc510299b5dca083a5901e404907c6c7eed6b99698ab',
    'Z001/estimate.pdf': 'b654872e0438b5b81a829e73aeee74ed085c81365927a7eb319fa8143bece64a',
}
PATHS = {digest: FOLDER / name for name, digest in SOURCES.items()}
PLAN = SOURCES['Z002/plan.pdf']
ORIGINAL = SOURCES['Z002/estimate.pdf']
REVISED = SOURCES['Z002/revised-estimate.pdf']
SCAN = SOURCES['Z002/scanned-estimate.pdf']
OTHER_PLAN = SOURCES['Z001/plan.pdf']
OTHER_ESTIMATE = SOURCES['Z001/estimate.pdf']
READER = 'pinned-fixture-reader-v1'
POLICY = json.loads((ROOT / 'fixtures/rulebooks.json').read_text())['alder']


class Conflict(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AssertionError(message)


@contextmanager
def temporary_database():
    with TemporaryDirectory(prefix='zu-rev-', dir='/tmp') as folder:
        data = f'{folder}/db'
        subprocess.run(['initdb', '-D', data, '-A', 'trust', '-U', 'fixture', '--no-locale', '--encoding=UTF8'],
                       check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['pg_ctl', '-D', data, '-l', f'{folder}/server.log', '-o',
                        f"-k {folder} -c listen_addresses=''", '-w', 'start'], check=True,
                       stdout=subprocess.DEVNULL)
        try:
            yield f'host={folder} user=fixture dbname=postgres'
        finally:
            subprocess.run(['pg_ctl', '-D', data, '-m', 'fast', '-w', 'stop'], check=True,
                           stdout=subprocess.DEVNULL)


def upload(db, case, key, base, plan, estimate):
    # One lock serializes submissions and finalization for this case.
    with db.transaction():
        head, = db.execute('SELECT head FROM cases WHERE id=%s FOR UPDATE', (case,)).fetchone()
        prior = db.execute('SELECT base, plan, estimate, rev FROM uploads WHERE case_id=%s AND request_id=%s',
                           (case, key)).fetchone()
        if prior:
            if prior[:3] != (base, plan, estimate):
                raise Conflict('idempotency key reused with a different payload')
            return prior[3]
        if head != base:
            raise Conflict('case revision changed before upload')
        current = db.execute('SELECT plan, estimate FROM revisions WHERE case_id=%s AND rev=%s',
                             (case, head)).fetchone()
        if current != (plan, estimate):
            head += 1
            db.execute('INSERT INTO revisions (case_id, rev, plan, estimate) VALUES (%s,%s,%s,%s)',
                       (case, head, plan, estimate))
            db.execute('UPDATE cases SET head=%s WHERE id=%s', (head, case))
        db.execute('INSERT INTO uploads VALUES (%s,%s,%s,%s,%s,%s)', (case, key, base, plan, estimate, head))
        return head


def claim(db, case, rev):
    return db.execute("""
        UPDATE revisions SET state='running', attempt=attempt+1
        WHERE case_id=%s AND rev=%s AND state IN ('queued','failed')
        RETURNING attempt, plan, estimate""", (case, rev)).fetchone()


def finish(db, case, rev, token, result=None):
    with db.transaction():
        head, = db.execute('SELECT head FROM cases WHERE id=%s FOR UPDATE', (case,)).fetchone()
        count = db.execute("""
            UPDATE revisions SET state=%s, result=%s, finished=nextval('finish_order')
            WHERE case_id=%s AND rev=%s AND state='running' AND attempt=%s""",
            ('done' if result else 'failed', Jsonb(result) if result else None, case, rev, token)).rowcount
        if not count:
            return 'rejected_attempt'
        return 'current' if rev == head else 'archived'


def read_page(db, case, digest, client=None):
    cached = db.execute('SELECT page FROM extractions WHERE case_id=%s AND digest=%s AND reader=%s',
                        (case, digest, READER)).fetchone()
    if cached:
        return Document(PATHS[digest], digest, [Page(**cached[0])]), True
    doc = read_document(PATHS[digest], client)
    require(doc.sha256 == digest and len(doc.pages) == 1, 'fixture digest/page mismatch')
    db.execute('INSERT INTO extractions VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',
               (case, digest, READER, Jsonb(asdict(doc.pages[0]))))
    return doc, False


def work(db, case, rev, *, held=None, before_finish=None, claimed_job=None, client=None):
    job = claimed_job if claimed_job is not None else claim(db, case, rev)
    require(job is not None, 'expected claimable job')
    token, plan_id, estimate_id = job
    plan, reused = read_page(db, case, plan_id, client)
    if held:
        held[0].set()
        require(held[1].wait(60), 'worker barrier timed out')
    estimate, _ = read_page(db, case, estimate_id, client)
    member, = db.execute('SELECT member FROM cases WHERE id=%s', (case,)).fetchone()
    if any(not contains_identifier(doc.text, member) or not contains_identifier(doc.text, POLICY['version'])
           for doc in (plan, estimate)):
        return finish(db, case, rev, token), reused
    evidence = read_fixture(plan, estimate)
    outcome, clause = precheck(POLICY, evidence)
    result = dict(outcome=outcome, clause=clause, total=evidence.total_thb, itemized=evidence.itemized,
                  plan=plan_id, estimate=estimate_id, page=estimate.pages[0].number,
                  extraction='ocr' if estimate.pages[0].ocr else 'digital')
    if before_finish:
        before_finish.wait(timeout=10)
    return finish(db, case, rev, token, result), reused


def current(db, case):
    return db.execute("""
        SELECT r.rev, r.state, r.result FROM cases c JOIN revisions r ON (r.case_id,r.rev)=(c.id,c.head)
        WHERE c.id=%s""", (case,)).fetchone()


def check_ready(db, case, rev):
    number, state, result = current(db, case)
    require((number, state, result['estimate'], result['plan'], result['total'], result['itemized'],
             result['outcome'], result['clause']) ==
            (rev, 'done', REVISED, PLAN, 82000, True, 'ready_for_review', None), 'incorrect current result')


class Experiment:
    def __init__(self, dsn):
        self.dsn = dsn
        self.db = psycopg.connect(dsn, autocommit=True)
        self.times = defaultdict(list)
        self.counts = Counter()
        self.pool = ThreadPoolExecutor(max_workers=2)

    def close(self):
        self.pool.shutdown()
        self.db.close()

    def thread(self, action, *args, **kwargs):
        def run():
            with psycopg.connect(self.dsn, autocommit=True) as db:
                return action(db, *args, **kwargs)
        return self.pool.submit(run)

    def new(self, name, member='DEMO-Z002'):
        self.db.execute('INSERT INTO cases (id,member) VALUES (%s,%s)', (name, member))

    def ordered(self, case):
        upload(self.db, case, 'first', 0, PLAN, ORIGINAL)
        work(self.db, case, 1)
        first = current(self.db, case)[2]
        require((first['outcome'], first['clause'], first['total'], first['itemized'], first['estimate']) ==
                ('missing_evidence', 'AT-2', 82000, False, ORIGINAL), 'original estimate facts')
        start = perf_counter()
        upload(self.db, case, 'replacement', 1, PLAN, REVISED)
        self.times['replacement upload transaction'].append(perf_counter()-start)
        require(current(self.db, case) == (2, 'queued', None), 'previous result visible on replacement')
        start = perf_counter()
        _, reused = work(self.db, case, 2)
        self.times['replacement native worker'].append(perf_counter()-start)
        require(reused, 'unchanged plan was reprocessed')
        check_ready(self.db, case, 2)

    def late(self, case, client=None):
        held = (Event(), Event())
        upload(self.db, case, 'first', 0, PLAN, SCAN if client else ORIGINAL)
        old = self.thread(work, case, 1, held=held, client=client)
        try:
            require(held[0].wait(10), 'old worker did not reach barrier')
            upload(self.db, case, 'replacement', 1, PLAN, REVISED)
            outcome, reused = work(self.db, case, 2)
            require(outcome == 'current' and reused, 'revision 2 publication or extraction reuse')
            check_ready(self.db, case, 2)
        finally:
            held[1].set()
        require(old.result()[0] == 'archived', 'late result published')
        check_ready(self.db, case, 2)
        naive_rev, naive = self.db.execute("""
            SELECT rev, result FROM revisions WHERE case_id=%s AND state='done'
            ORDER BY finished DESC LIMIT 1""", (case,)).fetchone()
        require(naive_rev == 1 and naive['outcome'] == 'missing_evidence' and naive['total'] == 82000
                and naive['extraction'] == ('ocr' if client else 'digital'),
                'last-completed negative control did not reproduce stale result')
        self.counts['last-completed control served stale revision'] += 1

    def repeats(self, case):
        require(upload(self.db, case, 'first', 0, PLAN, ORIGINAL) == 1, 'first upload')
        upload(self.db, case, 'replacement', 1, PLAN, REVISED)
        require(upload(self.db, case, 'replacement', 1, PLAN, REVISED) == 2, 'retry created new version')
        require(upload(self.db, case, 'repeat-bytes', 2, PLAN, REVISED) == 2, 'duplicate bytes created version')
        try:
            upload(self.db, case, 'replacement', 1, PLAN, ORIGINAL)
        except Conflict:
            pass
        else:
            raise AssertionError('reused request key accepted a changed file')
        release = Barrier(2)
        def compete(db):
            release.wait(timeout=10)
            return claim(db, case, 2)
        contenders = [self.thread(compete) for _ in range(2)]
        jobs = [future.result() for future in contenders]
        require(jobs.count(None) == 1, 'duplicate worker claim')
        token = next(job[0] for job in jobs if job)
        finish(self.db, case, 2, token)  # injected processing failure, e.g. provider timeout
        require(current(self.db, case) == (2, 'failed', None), 'failed revision has a usable result')
        retried = claim(self.db, case, 2)
        require(finish(self.db, case, 2, token) == 'rejected_attempt', 'old attempt interrupted active retry')
        work(self.db, case, 2, claimed_job=retried)
        require(finish(self.db, case, 2, token) == 'rejected_attempt', 'old attempt cleared new result')
        check_ready(self.db, case, 2)

    def simultaneous(self, case):
        upload(self.db, case, 'first', 0, PLAN, ORIGINAL)
        release = Barrier(2)
        def compete(db, digest):
            release.wait(timeout=10)
            try:
                return upload(db, case, digest, 1, PLAN, digest)
            except Conflict:
                return 'conflict'
        futures = [self.thread(compete, digest) for digest in (REVISED, SCAN)]
        outcomes = [f.result() for f in futures]
        require(set(outcomes) == {2, 'conflict'}, 'two uploads from the same base overwrote one another')
        winner = (REVISED, SCAN)[outcomes.index(2)]
        require(self.db.execute('SELECT estimate FROM revisions WHERE case_id=%s AND rev=2',
                                (case,)).fetchone()[0] == winner, 'winner differs from active estimate')

    def publication_race(self, case):
        upload(self.db, case, 'first', 0, PLAN, ORIGINAL)
        boundary = Barrier(2)
        old = self.thread(work, case, 1, before_finish=boundary)
        boundary.wait(timeout=10)
        upload(self.db, case, 'replacement', 1, PLAN, REVISED)
        outcome, _ = old.result()
        require(outcome in ('current', 'archived'), 'old revision finalization failed')
        self.counts['concurrent upload/finalize: old finalized ' + outcome] += 1
        require(current(self.db, case) == (2, 'queued', None), 'prior result visible on new revision')
        work(self.db, case, 2)
        check_ready(self.db, case, 2)

    def failed_replacement(self, case):
        held = (Event(), Event())
        upload(self.db, case, 'first', 0, PLAN, ORIGINAL)
        old = self.thread(work, case, 1, held=held)
        try:
            require(held[0].wait(10), 'old worker did not reach barrier')
            upload(self.db, case, 'bad-supplement', 1, PLAN, OTHER_ESTIMATE)
            work(self.db, case, 2)
            require(current(self.db, case) == (2, 'failed', None), 'wrong-member result accepted')
        finally:
            held[1].set()
        require(old.result()[0] == 'archived', 'old worker promoted over failure')
        require(current(self.db, case) == (2, 'failed', None), 'old result hid unresolved failure')
        upload(self.db, case, 'correction', 2, PLAN, REVISED)
        work(self.db, case, 3)
        check_ready(self.db, case, 3)

    def isolated(self, case):
        upload(self.db, case, 'first', 0, PLAN, REVISED)
        work(self.db, case, 1)
        other = case + '-Z001'
        self.new(other, 'DEMO-Z001')
        upload(self.db, other, 'first', 0, OTHER_PLAN, OTHER_ESTIMATE)
        work(self.db, other, 1)
        check_ready(self.db, case, 1)
        alternate = current(self.db, other)
        require(alternate[2]['total'] == 120000, 'cross-case estimate read')
        upload(self.db, case, 'wrong-member', 1, PLAN, OTHER_ESTIMATE)
        work(self.db, case, 2)
        require(current(self.db, case) == (2, 'failed', None), 'bad supplement exposed prior result')
        require(current(self.db, other) == alternate, 'mutation leaked into second case')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repetitions', type=int, default=40)
    parser.add_argument('--live-scan', action='store_true', help='Add one actual Astra transcription of late V1')
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error('repetitions must be positive')
    if args.live_scan and os.getenv('OPENAI_OCR_MODEL', 'gpt-6.2-astra') != 'gpt-6.2-astra':
        parser.error('The live benchmark requires OPENAI_OCR_MODEL=gpt-6.2-astra')
    for digest, path in PATHS.items():
        require(sha256(path.read_bytes()).hexdigest() == digest, f'changed fixture {path.name}')
    with temporary_database() as dsn:
        experiment = Experiment(dsn)
        try:
            experiment.db.execute(Path(__file__).with_suffix('.sql').read_text())
            print(experiment.db.execute('SHOW server_version').fetchone()[0])
            for test in (experiment.ordered, experiment.late, experiment.repeats,
                         experiment.simultaneous, experiment.publication_race,
                         experiment.failed_replacement, experiment.isolated):
                for i in range(args.repetitions):
                    case = f'{test.__name__}-{i}'
                    experiment.new(case)
                    test(case)
                print(f'{test.__name__}: {args.repetitions}/{args.repetitions} passed', flush=True)
            if args.live_scan:
                experiment.new('live')
                start = perf_counter()
                experiment.late('live', OpenAI(max_retries=0, timeout=45))
                print(f'live late scan: passed in {perf_counter()-start:.3f}s', flush=True)
            for name, times in experiment.times.items():
                print(f'{name}: n={len(times)} p50={median(times)*1000:.3f}ms '
                      f'p95={sorted(times)[ceil(len(times)*.95)-1]*1000:.3f}ms')
            for key, count in experiment.counts.items():
                print(f'{key}: {count}')
        finally:
            experiment.close()


if __name__ == '__main__':
    main()
