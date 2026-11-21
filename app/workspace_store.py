"""PostgreSQL storage for the isolated synthetic coordinator workspace."""
from hashlib import sha256
from contextlib import contextmanager, nullcontext

import psycopg
from psycopg.types.json import Jsonb
from app.case_workflow import projection, validate_event


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
CREATE TABLE IF NOT EXISTS zeroupfront_demo.events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, case_id text NOT NULL, revision integer NOT NULL,
    version integer NOT NULL, kind text NOT NULL, actor text NOT NULL, data jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), document text REFERENCES zeroupfront_demo.documents(digest),
    filename text, UNIQUE(case_id,revision,version),
    FOREIGN KEY (case_id,revision) REFERENCES zeroupfront_demo.revisions(case_id,revision)
);
ALTER TABLE zeroupfront_demo.approvals ADD COLUMN IF NOT EXISTS username text;
ALTER TABLE zeroupfront_demo.events ADD COLUMN IF NOT EXISTS username text;
CREATE TABLE IF NOT EXISTS zeroupfront_demo.intake_requests (
    actor text NOT NULL, request_key text NOT NULL, payload_digest text NOT NULL,
    case_id text NOT NULL REFERENCES zeroupfront_demo.cases(id), PRIMARY KEY(actor, request_key)
);
"""


class WorkspaceError(Exception):
    def __init__(self, status, message, *, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def document_digest(pdf):
    return sha256(pdf).hexdigest()


def _writing(dsn):
    return nullcontext(dsn) if isinstance(dsn, psycopg.Connection) else psycopg.connect(dsn)


def lock_intake(db, scope, request_key):
    actor, key, _ = request_key
    args = (scope + "/" + actor, key)
    if db.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s),hashtext(%s))", args).fetchone()[0]:
        return
    # Fast digital writes can finish and replay. A slow OCR owner must not occupy a second worker indefinitely.
    previous_ms = int(db.execute("SELECT setting FROM pg_settings WHERE name='lock_timeout'").fetchone()[0])
    wait_ms = min(previous_ms or 1000, 1000)
    db.execute("SELECT set_config('lock_timeout', %s, true)", (str(wait_ms),))
    try:
        db.execute("SELECT pg_advisory_xact_lock(hashtext(%s),hashtext(%s))", args)
    except psycopg.errors.LockNotAvailable as exc:
        raise WorkspaceError(409, "This intake is still processing. Retry the same packet and key shortly.",
                             retry_after=1) from exc
    db.execute("SELECT set_config('lock_timeout', %s, true)", (str(previous_ms),))


@contextmanager
def coordinate_ocr(dsn, scope, request_key, ocr):
    if not ocr or request_key is None:
        yield dsn
        return
    with psycopg.connect(dsn) as db:
        lock_intake(db, scope, request_key)
        yield db


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


def _events(db, case_id, revision):
    rows = db.execute("""
        SELECT id,kind,actor,created_at,data,filename,username FROM zeroupfront_demo.events
        WHERE case_id=%s AND revision=%s ORDER BY version
    """, (case_id, revision)).fetchall()
    return [dict(id=ident, kind=kind, actor=actor, username=username, created_at=stamp.isoformat(), data=data, filename=name,
                 source_url=f"/api/cases/{case_id}/revisions/{revision}/events/{ident}/source" if name else None)
            for ident, kind, actor, stamp, data, name, username in rows]


def _open_holds(db, case_id, revision):
    """A hospital hold follows the encounter until staff document its resolution."""
    rows = db.execute("""
        SELECT h.id, h.revision, h.data->>'category', h.data->>'notes', h.actor
        FROM zeroupfront_demo.events h
        WHERE h.case_id=%s AND h.kind='hold' AND h.revision<=%s AND NOT EXISTS (
            SELECT 1 FROM zeroupfront_demo.events x WHERE x.case_id=h.case_id AND x.kind='resolve_hold'
            AND x.revision<=%s AND x.data->>'hold_id'=h.id::text
        ) ORDER BY h.id
    """, (case_id, revision, revision)).fetchall()
    return [dict(id=i, revision=r, category=c, note=n, actor=a) for i,r,c,n,a in rows]


def _check_holds(db, case_id, revision):
    if _open_holds(db, case_id, revision):
        raise WorkspaceError(409, "Resolve the open case hold before releasing this request.")


def _detail(db, case_id, revision=None):
    # One MVCC snapshot keeps the selected head, evidence, approval and history consistent.
    rows = db.execute("""
        SELECT r.revision, CASE WHEN a.reviewer IS NULL THEN r.evidence->>'status' ELSE 'staff_reviewed' END,
               r.evidence->'total', a.reviewer, a.username,
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
    for number, status, total, reviewer, username, evidence in rows:
        history.append({"revision": number, "status": status, "total": total})
        if evidence is not None:
            sources = [dict(source, url=f"/api/cases/{case_id}/revisions/{number}/sources/{source['role']}")
                       for source in evidence["sources"]]
            detail = dict(evidence, revision=number, sources=sources, status=status,
                          reviewer=reviewer, reviewer_username=username, insurer_status="not_sent")
    if detail is None:
        raise WorkspaceError(404, "Case revision not found.")
    workflow = projection(_events(db, case_id, detail["revision"]), detail["status"] == "staff_reviewed")
    holds = _open_holds(db, case_id, detail["revision"])
    if holds and "submission" in workflow["allowed_actions"]:
        workflow["allowed_actions"].remove("submission")
    workflow["allowed_actions"].append("hold")
    if holds:
        workflow["allowed_actions"].append("resolve_hold")
    return dict(detail, history=history, intake=detail.get("input_kind") == "intake",
                open_holds=holds, open_hold_count=len(holds)) | workflow


def case_detail(dsn, case_id, revision=None):
    with psycopg.connect(dsn) as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return _detail(db, case_id, revision)


def list_cases(dsn):
    with psycopg.connect(dsn) as db:
        with db.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            return cursor.execute("""
            SELECT c.id, c.head AS revision, r.evidence->>'procedure' AS procedure,
                   r.evidence->>'insurer' AS insurer, r.evidence->>'member' AS member,
                   r.evidence->>'admission_date' AS admission_date, r.evidence->'total' AS total,
                   CASE WHEN a.reviewer IS NULL THEN r.evidence->>'status' ELSE 'staff_reviewed' END AS status,
                   coalesce(r.evidence->>'input_kind'='intake', false) AS intake,
                   coalesce(stage.status,'not_sent') AS insurer_status, latest.kind AS latest_event_kind,
                   (SELECT count(*) FILTER (WHERE h.kind='hold') - count(*) FILTER (WHERE h.kind='resolve_hold')
                    FROM zeroupfront_demo.events h WHERE h.case_id=c.id AND h.kind IN ('hold','resolve_hold')) AS open_hold_count
            FROM zeroupfront_demo.cases c
            JOIN zeroupfront_demo.revisions r ON r.case_id=c.id AND r.revision=c.head
            LEFT JOIN zeroupfront_demo.approvals a USING (case_id, revision)
            LEFT JOIN LATERAL (SELECT e.kind FROM zeroupfront_demo.events e WHERE e.case_id=c.id AND e.revision=c.head
                               ORDER BY version DESC LIMIT 1) latest ON true
            LEFT JOIN LATERAL (SELECT CASE e.kind WHEN 'reply' THEN e.data->>'outcome' WHEN 'submission' THEN 'submitted'
                                               WHEN 'supplement' THEN 'supplement_sent' END AS status
                               FROM zeroupfront_demo.events e WHERE e.case_id=c.id AND e.revision=c.head
                               AND e.kind IN ('reply','submission','supplement') ORDER BY version DESC LIMIT 1) stage ON true
            ORDER BY c.id
            """).fetchall()


def _previous_intake(db, request_key):
    actor, key, digest = request_key
    row = db.execute("""
        SELECT payload_digest,case_id FROM zeroupfront_demo.intake_requests WHERE actor=%s AND request_key=%s
    """, (actor, key)).fetchone()
    if not row:
        return None
    if row[0] != digest:
        raise WorkspaceError(409, "This intake request key has already been used for a different packet.")
    return _detail(db, row[1], 1)


def previous_intake(dsn, request_key):
    with _writing(dsn) as db:
        return _previous_intake(db, request_key)


def create_case(dsn, evidence, documents, request_key=None):
    _check_manifest(evidence, documents)
    case_id = evidence["id"]
    with _writing(dsn) as db:
        if request_key:
            lock_intake(db, "admission", request_key)
            existing = _previous_intake(db, request_key)
            if existing:
                return existing
        db.execute("INSERT INTO zeroupfront_demo.cases (id,head) VALUES (%s,1)", (case_id,))
        digests = [_save_document(db, documents[role]) for role in ("policy", "plan", "estimate")]
        db.execute("""
            INSERT INTO zeroupfront_demo.revisions (case_id,revision,policy,plan,estimate,evidence)
            VALUES (%s,1,%s,%s,%s,%s)
        """, (case_id, *digests, Jsonb(evidence)))
        if request_key:
            db.execute("""
                INSERT INTO zeroupfront_demo.intake_requests (actor,request_key,payload_digest,case_id)
                VALUES (%s,%s,%s,%s)
            """, (*request_key, case_id))
        return _detail(db, case_id)


def replace_estimate(dsn, case_id, base, evidence, documents, *, reviewed=False):
    _check_manifest(evidence, documents)
    with psycopg.connect(dsn) as db:
        _require_head(db, case_id, base)
        policy, plan, estimate = db.execute("""
            SELECT policy, plan, estimate FROM zeroupfront_demo.revisions WHERE case_id=%s AND revision=%s
        """, (case_id, base)).fetchone()
        if policy != document_digest(documents["policy"]) or plan != document_digest(documents["plan"]):
            raise WorkspaceError(409, "The evaluated plan or policy differs from the saved case.")
        if reviewed or estimate != document_digest(documents["estimate"]):
            digest = _save_document(db, documents["estimate"])
            db.execute("""
                INSERT INTO zeroupfront_demo.revisions (case_id, revision, policy, plan, estimate, evidence)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (case_id, base + 1, policy, plan, digest, Jsonb(evidence)))
            db.execute("UPDATE zeroupfront_demo.cases SET head=%s WHERE id=%s", (base + 1, case_id))
        return _detail(db, case_id)


def approve(dsn, case_id, base, reviewer, username=None):
    with _writing(dsn) as db:
        _require_head(db, case_id, base)
        _check_holds(db, case_id, base)
        detail = _detail(db, case_id)
        if detail["status"] == "staff_reviewed":
            if detail["reviewer"] != reviewer or detail["reviewer_username"] != username:
                raise WorkspaceError(409, "This revision already has a recorded reviewer.")
            return detail
        if detail["status"] != "ready_for_review":
            raise WorkspaceError(409, "Resolve the case findings before approving this revision.")
        db.execute("""
            INSERT INTO zeroupfront_demo.approvals (case_id, revision, reviewer, username) VALUES (%s, %s, %s, %s)
        """, (case_id, base, reviewer, username))
        return _detail(db, case_id)


def _require_approval(db, case_id, revision):
    _require_head(db, case_id, revision)
    _check_holds(db, case_id, revision)
    if not db.execute("""
        SELECT 1 FROM zeroupfront_demo.approvals WHERE case_id=%s AND revision=%s
    """, (case_id, revision)).fetchone():
        raise WorkspaceError(409, "A staff reviewer must approve this revision before export.")


def revision_snapshot(dsn, case_id, revision, *, approved=False):
    with psycopg.connect(dsn) as db:
        if approved:
            _require_approval(db, case_id, revision)
        else:
            _require_head(db, case_id, revision)
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


def record_event(dsn, case_id, base, version, action, actor, username, fields, attachment, filename):
    with _writing(dsn) as db:
        _require_head(db, case_id, base)
        target = fields.get("target_revision") or base
        if target != base and action not in {"reply", "supplement"}:
            raise WorkspaceError(409, "Only mail on a previously submitted revision can be recorded in history.")
        detail = _detail(db, case_id, target)
        if version != detail["workflow_version"]:
            raise WorkspaceError(409, "The workflow changed. Reload this revision before recording the event.")
        try:
            data = validate_event(detail, action, fields, attachment is not None)
        except ValueError as exc:
            raise WorkspaceError(409 if action not in detail["allowed_actions"] else 422, str(exc)) from exc
        digest = _save_document(db, attachment) if attachment else None
        db.execute("""
            INSERT INTO zeroupfront_demo.events (case_id,revision,version,kind,actor,username,data,document,filename)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (case_id, target, version + 1, action, actor, username, Jsonb(data), digest, filename))
        return _detail(db, case_id, target)


def create_example(dsn, evidence, documents, events):
    """The complete simulated timeline commits together even if its last event fails validation."""
    case_id = evidence["id"]
    with psycopg.connect(dsn) as db:
        detail = create_case(db, evidence, documents)
        if events:
            detail = approve(db, case_id, 1, "Synthetic coordinator")
        for version, (action, fields, raw) in enumerate(events):
            detail = record_event(db, case_id, 1, version, action, "Synthetic coordinator", None, fields,
                                  raw, "synthetic-payer-letter.pdf" if raw else None)
        return detail


def event_source(dsn, case_id, revision, event_id):
    with psycopg.connect(dsn) as db:
        record = db.execute("""
            SELECT d.pdf FROM zeroupfront_demo.events e JOIN zeroupfront_demo.documents d ON d.digest=e.document
            WHERE e.case_id=%s AND e.revision=%s AND e.id=%s
        """, (case_id, revision, event_id)).fetchone()
    if not record:
        raise WorkspaceError(404, "Event attachment not found.")
    return record[0]


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
