"""Revisioned discharge packets, external payer decisions and separately recorded remittances."""

from decimal import Decimal, InvalidOperation

import psycopg
from psycopg.types.json import Jsonb

from app.workspace_store import WorkspaceError, _save_document, document_digest


SCHEMA = """
CREATE TABLE IF NOT EXISTS zeroupfront_demo.discharge_cases (
    id text PRIMARY KEY, head integer NOT NULL, prior_case_id text REFERENCES zeroupfront_demo.cases(id),
    prior_revision integer, UNIQUE(id,head)
);
CREATE TABLE IF NOT EXISTS zeroupfront_demo.discharge_revisions (
    case_id text REFERENCES zeroupfront_demo.discharge_cases(id), revision integer NOT NULL,
    evidence jsonb NOT NULL, PRIMARY KEY(case_id,revision)
);
CREATE TABLE IF NOT EXISTS zeroupfront_demo.discharge_sources (
    case_id text NOT NULL, revision integer NOT NULL, role text NOT NULL, filename text NOT NULL,
    digest text NOT NULL REFERENCES zeroupfront_demo.documents(digest), PRIMARY KEY(case_id,revision,role),
    FOREIGN KEY(case_id,revision) REFERENCES zeroupfront_demo.discharge_revisions(case_id,revision)
);
CREATE TABLE IF NOT EXISTS zeroupfront_demo.discharge_approvals (
    case_id text NOT NULL, revision integer NOT NULL, actor text NOT NULL, username text,
    approved_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(case_id,revision),
    FOREIGN KEY(case_id,revision) REFERENCES zeroupfront_demo.discharge_revisions(case_id,revision)
);
CREATE TABLE IF NOT EXISTS zeroupfront_demo.discharge_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, case_id text NOT NULL, revision integer NOT NULL,
    version integer NOT NULL, kind text NOT NULL, actor text NOT NULL, username text, data jsonb NOT NULL,
    document text REFERENCES zeroupfront_demo.documents(digest), filename text, created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(case_id,revision,version), FOREIGN KEY(case_id,revision) REFERENCES zeroupfront_demo.discharge_revisions(case_id,revision)
);
CREATE UNIQUE INDEX IF NOT EXISTS discharge_payment_reference ON zeroupfront_demo.discharge_events
    (case_id,lower(data->>'reference')) WHERE kind='payment';
CREATE TABLE IF NOT EXISTS zeroupfront_demo.discharge_intake_requests (
    actor text NOT NULL, request_key text NOT NULL, digest text NOT NULL,
    case_id text NOT NULL REFERENCES zeroupfront_demo.discharge_cases(id), PRIMARY KEY(actor,request_key)
);
"""


def initialize(dsn):
    with psycopg.connect(dsn) as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtext('zeroupfront_demo.discharge'))")
        db.execute(SCHEMA)


def _head(db, ident, rev):
    row = db.execute(
        "SELECT head FROM zeroupfront_demo.discharge_cases WHERE id=%s FOR UPDATE", (ident,)
    ).fetchone()
    if not row:
        raise WorkspaceError(404, "Discharge case not found.")
    if row[0] != rev:
        raise WorkspaceError(412, "The discharge packet has changed. Open the current revision.")


def _projection(events, approved):
    status, decision, payments = "not_sent", None, []
    for event in events:
        if event["kind"] == "submission":
            status = "submitted"
        elif event["kind"] == "reply":
            decision = event["data"]
            status = decision["outcome"]
        elif event["kind"] == "payment":
            payments.append(event["data"])
    amounts = {}
    for payment in payments:
        code = payment["currency"]
        amounts[code] = amounts.get(code, 0) + payment["amount_minor"]
    settlement = "unpaid"
    if payments:
        if (
            not decision
            or decision["outcome"] not in {"partial", "confirmed"}
            or set(amounts) != {decision["currency"]}
        ):
            settlement = "reconciliation_required"
        else:
            paid = amounts[decision["currency"]]
            settlement = (
                "paid"
                if paid == decision["amount_minor"]
                else ("partially_paid" if paid < decision["amount_minor"] else "reconciliation_required")
            )
    actions = []
    if approved:
        actions = ["submission"] if status == "not_sent" else ["reply"]
        if status in {"partial", "confirmed"}:
            actions.append("payment")
    return dict(
        insurer_status=status,
        settlement_status=settlement,
        payer_decision=decision,
        paid_by_currency=amounts,
        workflow_version=len(events),
        allowed_actions=actions,
        events=events,
    )


def _detail(db, ident, rev=None):
    row = db.execute(
        """
        SELECT r.evidence,r.revision,c.prior_case_id,c.prior_revision,a.actor,a.username
        FROM zeroupfront_demo.discharge_cases c JOIN zeroupfront_demo.discharge_revisions r
        ON r.case_id=c.id AND r.revision=coalesce(%s,c.head)
        LEFT JOIN zeroupfront_demo.discharge_approvals a USING(case_id,revision) WHERE c.id=%s
    """,
        (rev, ident),
    ).fetchone()
    if not row:
        raise WorkspaceError(404, "Discharge case or revision not found.")
    evidence, rev, prior, prior_rev, actor, username = row
    history = [
        dict(revision=n, status=status, total=amount)
        for n, status, amount in db.execute(
            """
        SELECT r.revision,CASE WHEN a.actor IS NULL THEN r.evidence->>'status' ELSE 'staff_reviewed' END,
               r.evidence->'bill_total_minor' FROM zeroupfront_demo.discharge_revisions r
        LEFT JOIN zeroupfront_demo.discharge_approvals a USING(case_id,revision) WHERE r.case_id=%s ORDER BY revision DESC
    """,
            (ident,),
        )
    ]
    sources = [
        dict(s, url=f"/api/discharge/{ident}/revisions/{rev}/sources/{s['role']}") for s in evidence["sources"]
    ]
    events = [
        dict(
            id=i,
            kind=k,
            actor=a,
            username=u,
            created_at=stamp.isoformat(),
            data=d,
            filename=f,
            source_url=f"/api/discharge/{ident}/revisions/{rev}/events/{i}/source" if f else None,
        )
        for i, k, a, u, stamp, d, f in db.execute(
            """
        SELECT id,kind,actor,username,created_at,data,filename FROM zeroupfront_demo.discharge_events
        WHERE case_id=%s AND revision=%s ORDER BY version
    """,
            (ident, rev),
        )
    ]
    totals = dict(
        db.execute(
            """
        SELECT data->>'currency',sum((data->>'amount_minor')::bigint)::bigint
        FROM zeroupfront_demo.discharge_events WHERE kind='payment' AND case_id=%s GROUP BY data->>'currency'
    """,
            (ident,),
        ).fetchall()
    )
    return dict(
        evidence,
        id=ident,
        revision=rev,
        history=history,
        case_paid_by_currency=totals,
        sources=sources,
        prior_case_id=prior,
        prior_revision=prior_rev,
        reviewer=actor,
        reviewer_username=username,
        status="staff_reviewed" if actor else evidence["status"],
    ) | _projection(events, bool(actor))


def detail(dsn, ident, rev=None):
    with psycopg.connect(dsn) as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return _detail(db, ident, rev)


def summaries(dsn):
    with psycopg.connect(dsn) as db:
        with db.cursor(row_factory=psycopg.rows.dict_row) as cur:
            return cur.execute("""
                SELECT c.id,c.head AS revision,r.evidence->>'member' AS member,r.evidence->>'procedure' AS procedure,
                       r.evidence->>'insurer' AS insurer,r.evidence->>'encounter' AS encounter,
                       r.evidence->>'admission_date' AS admission_date,r.evidence->>'discharge_date' AS discharge_date,
                       r.evidence->>'currency' AS currency,r.evidence->'bill_total_minor' AS bill_total_minor,
                       CASE WHEN a.actor IS NULL THEN r.evidence->>'status' ELSE 'staff_reviewed' END AS status,
                       coalesce(stage.status,'not_sent') AS insurer_status
                FROM zeroupfront_demo.discharge_cases c JOIN zeroupfront_demo.discharge_revisions r
                ON r.case_id=c.id AND r.revision=c.head LEFT JOIN zeroupfront_demo.discharge_approvals a USING(case_id,revision)
                LEFT JOIN LATERAL (SELECT CASE WHEN e.kind='submission' THEN 'submitted' ELSE e.data->>'outcome' END AS status
                    FROM zeroupfront_demo.discharge_events e WHERE e.case_id=c.id AND e.revision=c.head
                    AND e.kind IN ('submission','reply') ORDER BY e.version DESC LIMIT 1) stage ON true ORDER BY c.id
            """).fetchall()


def _write(db, ident, rev, evidence, raw, names):
    hashes = {role: document_digest(data) for role, data in raw.items()}
    if hashes != {source["role"]: source["sha256"] for source in evidence["sources"]}:
        raise WorkspaceError(409, "The evaluated source hashes differ from the submitted exhibits.")
    db.execute("INSERT INTO zeroupfront_demo.discharge_revisions VALUES (%s,%s,%s)", (ident, rev, Jsonb(evidence)))
    for role, data in raw.items():
        digest = _save_document(db, data)
        db.execute(
            "INSERT INTO zeroupfront_demo.discharge_sources VALUES (%s,%s,%s,%s,%s)",
            (ident, rev, role, names[role], digest),
        )


def create(dsn, ident, evidence, raw, names, prior=None, request_key=None):
    with psycopg.connect(dsn) as db:
        if request_key:
            actor, key, digest = request_key
            db.execute("SELECT pg_advisory_xact_lock(hashtext(%s),hashtext(%s))", (actor, key))
            row = db.execute(
                """SELECT digest,case_id FROM zeroupfront_demo.discharge_intake_requests
                                WHERE actor=%s AND request_key=%s""",
                (actor, key),
            ).fetchone()
            if row:
                if row[0] != digest:
                    raise WorkspaceError(409, "That intake key already identifies a different discharge packet.")
                return _detail(db, row[1], 1)
        prior_rev = None
        if prior:
            row = db.execute(
                """
                SELECT c.head,r.evidence->>'member',r.evidence->>'admission_date',r.evidence->>'procedure',
                       r.evidence->>'insurer' FROM zeroupfront_demo.cases c
                JOIN zeroupfront_demo.revisions r ON r.case_id=c.id AND r.revision=c.head WHERE c.id=%s FOR SHARE OF c
            """,
                (prior,),
            ).fetchone()
            expected = tuple(evidence[k] for k in ("member", "admission_date", "procedure", "insurer"))
            if not row or row[1:] != expected:
                raise WorkspaceError(
                    422, "The linked case must match this member, admission date, procedure and insurer."
                )
            prior_rev = row[0]
        db.execute("INSERT INTO zeroupfront_demo.discharge_cases VALUES (%s,1,%s,%s)", (ident, prior, prior_rev))
        _write(db, ident, 1, evidence, raw, names)
        if request_key:
            db.execute(
                "INSERT INTO zeroupfront_demo.discharge_intake_requests VALUES (%s,%s,%s,%s)",
                (*request_key, ident),
            )
        return _detail(db, ident)


def snapshot(dsn, ident, base, *, approved=False):
    with psycopg.connect(dsn) as db:
        _head(db, ident, base)
        case = _detail(db, ident, base)
        if approved and case["status"] != "staff_reviewed":
            raise WorkspaceError(409, "Staff must review the current discharge revision before export.")
        rows = db.execute(
            """
            SELECT s.role,s.filename,d.pdf FROM zeroupfront_demo.discharge_sources s
            JOIN zeroupfront_demo.documents d USING(digest) WHERE s.case_id=%s AND s.revision=%s
        """,
            (ident, base),
        ).fetchall()
        return case, {role: raw for role, _, raw in rows}, {role: name for role, name, _ in rows}


def replace(dsn, ident, base, evidence, raw, names):
    with psycopg.connect(dsn) as db:
        _head(db, ident, base)
        existing = dict(
            db.execute(
                "SELECT role,digest FROM zeroupfront_demo.discharge_sources WHERE case_id=%s AND revision=%s",
                (ident, base),
            ).fetchall()
        )
        if existing != {role: document_digest(data) for role, data in raw.items()}:
            _write(db, ident, base + 1, evidence, raw, names)
            db.execute("UPDATE zeroupfront_demo.discharge_cases SET head=%s WHERE id=%s", (base + 1, ident))
        return _detail(db, ident)


def approve(dsn, ident, base, actor, username):
    with psycopg.connect(dsn) as db:
        _head(db, ident, base)
        case = _detail(db, ident)
        if case["status"] == "staff_reviewed" and (case["reviewer"], case["reviewer_username"]) == (
            actor,
            username,
        ):
            return case
        if case["status"] != "ready_for_review":
            raise WorkspaceError(409, "Only a ready discharge packet can receive its first staff approval.")
        db.execute(
            """INSERT INTO zeroupfront_demo.discharge_approvals (case_id,revision,actor,username)
                      VALUES (%s,%s,%s,%s)""",
            (ident, base, actor, username),
        )
        return _detail(db, ident)


def _required(fields, key, maximum=2000):
    value = fields.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise WorkspaceError(422, f"Enter {key} with up to {maximum} characters.")
    return value.strip()


def _amount(fields):
    try:
        amount = Decimal(str(fields.get("amount")))
    except InvalidOperation:
        raise WorkspaceError(422, "Enter the recorded amount.") from None
    if not amount.is_finite() or amount <= 0 or amount > 999999999999 or amount.as_tuple().exponent < -2:
        raise WorkspaceError(422, "Enter a positive amount with at most two decimal places.")
    currency = _required(fields, "currency", 3).upper()
    if currency not in {"THB", "USD", "EUR"}:
        raise WorkspaceError(422, "Supported settlement currencies are THB, USD and EUR.")
    return dict(amount_minor=int(amount * 100), currency=currency)


def record(dsn, ident, base, fields, actor, username, raw, name, submitted_packet=None):
    with psycopg.connect(dsn) as db:
        _head(db, ident, base)
        target = fields.get("target_revision") or base
        action = fields["action"]
        case = _detail(db, ident, target)
        if (target != base and action == "submission") or fields["workflow_version"] != case["workflow_version"]:
            raise WorkspaceError(409, "Reload the specific submitted revision and its latest timeline.")
        if action not in case["allowed_actions"]:
            raise WorkspaceError(409, "This action is unavailable at the current discharge stage.")
        data = {"reference": _required(fields, "reference", 200)}
        if action == "submission":
            if raw is not None:
                raise WorkspaceError(422, "Record the channel and transmission reference for this submission.")
            data["channel"] = _required(fields, "channel", 120)
            if submitted_packet is None:
                raise WorkspaceError(409, "The approved discharge packet is unavailable.")
            raw, name = submitted_packet, f"{ident}-r{target}-submitted-request.pdf"
            data["packet_sha256"] = document_digest(submitted_packet)
        elif action == "reply":
            if (
                not raw
                or not fields.get("confirmed")
                or fields.get("outcome") not in {"query", "partial", "confirmed", "declined"}
            ):
                raise WorkspaceError(422, "Choose the payer outcome, attach its letter and confirm the encounter.")
            data.update(outcome=fields["outcome"], terms=_required(fields, "terms"))
            if data["outcome"] in {"partial", "confirmed"}:
                data.update(_amount(fields))
        elif action == "payment":
            data.update(_amount(fields), notes=_required(fields, "notes"))
            if data["currency"] != case["payer_decision"]["currency"]:
                raise WorkspaceError(
                    422, "The recorded payment currency differs from the payer decision. Reconcile it first."
                )
            if db.execute(
                """SELECT 1 FROM zeroupfront_demo.discharge_events WHERE case_id=%s AND kind='payment'
                             AND lower(data->>'reference')=lower(%s)""",
                (ident, data["reference"]),
            ).fetchone():
                raise WorkspaceError(409, "This payment reference was already recorded for this case.")
        digest = _save_document(db, raw) if raw else None
        db.execute(
            """INSERT INTO zeroupfront_demo.discharge_events
                      (case_id,revision,version,kind,actor,username,data,document,filename)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (ident, target, case["workflow_version"] + 1, action, actor, username, Jsonb(data), digest, name),
        )
        return _detail(db, ident, target)


def source(dsn, ident, revision, *, role=None, event_id=None):
    with psycopg.connect(dsn) as db:
        if role:
            row = db.execute(
                """SELECT d.pdf FROM zeroupfront_demo.discharge_sources s
                JOIN zeroupfront_demo.documents d USING(digest) WHERE s.case_id=%s AND s.revision=%s AND s.role=%s""",
                (ident, revision, role),
            ).fetchone()
        else:
            row = db.execute(
                """SELECT d.pdf FROM zeroupfront_demo.discharge_events e
                JOIN zeroupfront_demo.documents d ON d.digest=e.document WHERE e.case_id=%s AND e.revision=%s AND e.id=%s""",
                (ident, revision, event_id),
            ).fetchone()
    if not row:
        raise WorkspaceError(404, "Discharge source not found.")
    return row[0]
