"""PostgreSQL storage for the isolated synthetic coordinator workspace."""
from hashlib import sha256

import psycopg
from psycopg.types.json import Jsonb


DDL = """
CREATE SCHEMA IF NOT EXISTS zeroupfront_demo;
CREATE TABLE IF NOT EXISTS zeroupfront_demo.cases (
    id text PRIMARY KEY, head integer NOT NULL CHECK (head > 0)
);
CREATE TABLE IF NOT EXISTS zeroupfront_demo.documents (
    digest text PRIMARY KEY, pdf bytea NOT NULL
);
CREATE TABLE IF NOT EXISTS zeroupfront_demo.revisions (
    case_id text REFERENCES zeroupfront_demo.cases(id),
    revision integer NOT NULL CHECK (revision > 0),
    policy text NOT NULL REFERENCES zeroupfront_demo.documents(digest),
    plan text NOT NULL REFERENCES zeroupfront_demo.documents(digest),
    estimate text NOT NULL REFERENCES zeroupfront_demo.documents(digest),
    evidence jsonb NOT NULL,
    PRIMARY KEY (case_id, revision)
);
CREATE TABLE IF NOT EXISTS zeroupfront_demo.approvals (
    case_id text NOT NULL, revision integer NOT NULL, reviewer text NOT NULL,
    approved_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, revision),
    FOREIGN KEY (case_id, revision) REFERENCES zeroupfront_demo.revisions(case_id, revision)
);
"""


class WorkspaceError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def document_digest(pdf):
    return sha256(pdf).hexdigest()


def _save_document(db, pdf):
    digest = document_digest(pdf)
    db.execute("""
        INSERT INTO zeroupfront_demo.documents (digest, pdf) VALUES (%s, %s)
        ON CONFLICT (digest) DO NOTHING
    """, (digest, pdf))
    return digest


def _check_manifest(evidence, documents):
    cited = {source["role"]: source["sha256"] for source in evidence["sources"]}
    if cited != {role: document_digest(data) for role, data in documents.items()}:
        raise WorkspaceError(409, "A cited exhibit has changed. Reload the verified demo exhibits before continuing.")


def initialize(dsn, seeds):
    """Seed from evaluated inputs atomically. Existing cases retain all of their history."""
    with psycopg.connect(dsn) as db:
        # Serializes schema creation across concurrently starting Uvicorn processes.
        db.execute("SELECT pg_advisory_xact_lock(hashtext('zeroupfront_demo.schema'))")
        db.execute(DDL)
        for evidence, documents in seeds:
            case_id = evidence["id"]
            inserted = db.execute("""
                INSERT INTO zeroupfront_demo.cases (id, head) VALUES (%s, 1)
                ON CONFLICT DO NOTHING RETURNING id
            """, (case_id,)).fetchone()
            if inserted:
                _check_manifest(evidence, documents)
                digests = [_save_document(db, documents[role]) for role in ("policy", "plan", "estimate")]
                db.execute("""
                    INSERT INTO zeroupfront_demo.revisions
                        (case_id, revision, policy, plan, estimate, evidence)
                    VALUES (%s, 1, %s, %s, %s, %s)
                """, (case_id, *digests, Jsonb(evidence)))


def _require_head(db, case_id, revision):
    record = db.execute("SELECT head FROM zeroupfront_demo.cases WHERE id=%s FOR UPDATE", (case_id,)).fetchone()
    if not record:
        raise WorkspaceError(404, "Case not found.")
    if record[0] != revision:
        raise WorkspaceError(412, "The case has a newer revision. Open the current revision before continuing.")


def _detail(db, case_id, revision=None):
    # One MVCC snapshot keeps the selected head, evidence, approval and history consistent.
    rows = db.execute("""
        SELECT r.revision, CASE WHEN a.reviewer IS NULL THEN r.evidence->>'status' ELSE 'staff_reviewed' END,
               r.evidence->'total', a.reviewer,
               CASE WHEN r.revision=coalesce(%s, c.head) THEN r.evidence END
        FROM zeroupfront_demo.cases c
        JOIN zeroupfront_demo.revisions r ON r.case_id=c.id
        LEFT JOIN zeroupfront_demo.approvals a USING (case_id, revision)
        WHERE c.id=%s ORDER BY r.revision DESC
    """, (revision, case_id)).fetchall()
    if not rows:
        raise WorkspaceError(404, "Case not found.")
    history = []
    detail = None
    for number, status, total, reviewer, evidence in rows:
        history.append({"revision": number, "status": status, "total": total})
        if evidence is not None:
            sources = [dict(source, url=f"/api/cases/{case_id}/revisions/{number}/sources/{source['role']}")
                       for source in evidence["sources"]]
            detail = dict(evidence, revision=number, sources=sources, status=status,
                          reviewer=reviewer, insurer_status="not_sent")
    if detail is None:
        raise WorkspaceError(404, "Case revision not found.")
    return dict(detail, history=history)


def case_detail(dsn, case_id, revision=None):
    with psycopg.connect(dsn) as db:
        return _detail(db, case_id, revision)


def list_cases(dsn):
    with psycopg.connect(dsn) as db:
        with db.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            return cursor.execute("""
            SELECT c.id, c.head AS revision, r.evidence->>'procedure' AS procedure,
                   r.evidence->>'insurer' AS insurer, r.evidence->>'member' AS member,
                   r.evidence->>'admission_date' AS admission_date, r.evidence->'total' AS total,
                   CASE WHEN a.reviewer IS NULL THEN r.evidence->>'status' ELSE 'staff_reviewed' END AS status
            FROM zeroupfront_demo.cases c
            JOIN zeroupfront_demo.revisions r ON r.case_id=c.id AND r.revision=c.head
            LEFT JOIN zeroupfront_demo.approvals a USING (case_id, revision)
            ORDER BY c.id
            """).fetchall()


def replace_estimate(dsn, case_id, base, evidence, documents):
    _check_manifest(evidence, documents)
    with psycopg.connect(dsn) as db:
        _require_head(db, case_id, base)
        policy, plan, estimate = db.execute("""
            SELECT policy, plan, estimate FROM zeroupfront_demo.revisions WHERE case_id=%s AND revision=%s
        """, (case_id, base)).fetchone()
        if policy != document_digest(documents["policy"]) or plan != document_digest(documents["plan"]):
            raise WorkspaceError(409, "The evaluated plan or policy differs from the saved case.")
        if estimate != document_digest(documents["estimate"]):
            digest = _save_document(db, documents["estimate"])
            db.execute("""
                INSERT INTO zeroupfront_demo.revisions (case_id, revision, policy, plan, estimate, evidence)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (case_id, base + 1, policy, plan, digest, Jsonb(evidence)))
            db.execute("UPDATE zeroupfront_demo.cases SET head=%s WHERE id=%s", (base + 1, case_id))
        return _detail(db, case_id)


def approve(dsn, case_id, base, reviewer):
    with psycopg.connect(dsn) as db:
        _require_head(db, case_id, base)
        detail = _detail(db, case_id)
        if detail["status"] == "staff_reviewed":
            if detail["reviewer"] != reviewer:
                raise WorkspaceError(409, "This revision already has a recorded reviewer.")
            return detail
        if detail["status"] != "ready_for_review":
            raise WorkspaceError(409, "Resolve the case findings before approving this revision.")
        db.execute("""
            INSERT INTO zeroupfront_demo.approvals (case_id, revision, reviewer) VALUES (%s, %s, %s)
        """, (case_id, base, reviewer))
        return _detail(db, case_id)


def _require_approval(db, case_id, revision):
    _require_head(db, case_id, revision)
    if not db.execute("""
        SELECT 1 FROM zeroupfront_demo.approvals WHERE case_id=%s AND revision=%s
    """, (case_id, revision)).fetchone():
        raise WorkspaceError(409, "A staff reviewer must approve this revision before export.")


def approved_snapshot(dsn, case_id, revision):
    with psycopg.connect(dsn) as db:
        _require_approval(db, case_id, revision)
        originals = db.execute("""
            SELECT p.pdf, t.pdf, e.pdf FROM zeroupfront_demo.revisions r
            JOIN zeroupfront_demo.documents p ON p.digest=r.policy
            JOIN zeroupfront_demo.documents t ON t.digest=r.plan
            JOIN zeroupfront_demo.documents e ON e.digest=r.estimate
            WHERE r.case_id=%s AND r.revision=%s
        """, (case_id, revision)).fetchone()
        return _detail(db, case_id, revision), dict(zip(("policy", "plan", "estimate"), originals, strict=True))


def check_export_current(dsn, case_id, revision):
    with psycopg.connect(dsn) as db:
        _require_approval(db, case_id, revision)


def source_pdf(dsn, case_id, revision, role):
    with psycopg.connect(dsn) as db:
        record = db.execute("""
            SELECT d.pdf, d.digest FROM zeroupfront_demo.revisions r
            JOIN zeroupfront_demo.documents d ON d.digest=CASE %s
                WHEN 'policy' THEN r.policy WHEN 'estimate' THEN r.estimate WHEN 'plan' THEN r.plan END
            WHERE r.case_id=%s AND r.revision=%s
        """, (role, case_id, revision)).fetchone()
    if not record:
        raise WorkspaceError(404, "Source document not found.")
    return record
