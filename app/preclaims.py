"""Revisioned hospital preparation and insurer handoff for the synthetic Meridian case."""

from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Header, HTTPException, Query, Request
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from app import preclaim_fixture as fixture
from app.hospital_platform import hospital_path
from app.workspace_http_common import _actor, _pdf, _revision
from app.workspace_store import _save_document

router = APIRouter()
Match = Annotated[str | None, Header(alias="If-Match")]
SelectedRevision = Annotated[int | None, Query(ge=1)]
SourceRole = Literal["policy", "report", "estimate", "draft", "request"]
DDL = """
CREATE TABLE IF NOT EXISTS zeroupfront_demo.preclaims (
    id text PRIMARY KEY, insurer text NOT NULL, hospital text NOT NULL,
    head integer NOT NULL CHECK(head > 0), replacement text NOT NULL REFERENCES zeroupfront_demo.documents(digest)
);
CREATE TABLE IF NOT EXISTS zeroupfront_demo.preclaim_revisions (
    case_id text NOT NULL REFERENCES zeroupfront_demo.preclaims(id), revision integer NOT NULL,
    policy text NOT NULL REFERENCES zeroupfront_demo.documents(digest),
    report text NOT NULL REFERENCES zeroupfront_demo.documents(digest),
    estimate text NOT NULL REFERENCES zeroupfront_demo.documents(digest),
    case_values jsonb NOT NULL,
    draft text REFERENCES zeroupfront_demo.documents(digest),
    created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(case_id, revision)
);
CREATE TABLE IF NOT EXISTS zeroupfront_demo.preclaim_reviews (
    case_id text NOT NULL, revision integer NOT NULL,
    actor text NOT NULL, username text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    form text NOT NULL REFERENCES zeroupfront_demo.documents(digest),
    PRIMARY KEY(case_id,revision),
    FOREIGN KEY(case_id,revision) REFERENCES zeroupfront_demo.preclaim_revisions(case_id,revision)
);
CREATE TABLE IF NOT EXISTS zeroupfront_demo.preclaim_submissions (
    case_id text PRIMARY KEY, revision integer NOT NULL, actor text NOT NULL, username text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(case_id,revision) REFERENCES zeroupfront_demo.preclaim_reviews(case_id,revision)
);
CREATE TABLE IF NOT EXISTS zeroupfront_demo.preclaim_questions (
    case_id text NOT NULL, revision integer NOT NULL, sequence integer NOT NULL CHECK(sequence > 0),
    source_role text NOT NULL, page integer NOT NULL CHECK(page > 0), question text NOT NULL,
    asked_by text NOT NULL, asked_at timestamptz NOT NULL DEFAULT now(),
    reply text, replied_by text, replied_at timestamptz,
    PRIMARY KEY(case_id,revision,sequence),
    FOREIGN KEY(case_id,revision) REFERENCES zeroupfront_demo.preclaim_reviews(case_id,revision)
);
"""


def initialize(dsn):
    with psycopg.connect(dsn) as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtext('zeroupfront_demo.preclaims'))")
        db.execute(DDL)


def seed(dsn, hospital):
    initialize(dsn)
    with psycopg.connect(dsn) as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtext('zeroupfront_demo.seed_preclaims'))")
        if db.execute("SELECT 1 FROM zeroupfront_demo.preclaims WHERE id=%s", (fixture.CASE,)).fetchone():
            return
        exhibits = fixture.exhibits(hospital)
        values = fixture.case_values(hospital)

        def checked(report):
            return fixture.checks(exhibits["policy"], exhibits[report], exhibits["estimate"], fixture.CASE, values)

        if checked("report") != (True, False, True):
            raise ValueError("Unexpected initial rule or medical report in the Amelia demo.")
        if checked("replacement") != (True, True, True):
            raise ValueError("The signed replacement in the Amelia demo did not pass verification.")
        digests = {key: _save_document(db, value) for key, value in exhibits.items()}
        db.execute(
            "INSERT INTO zeroupfront_demo.preclaims VALUES(%s,%s,%s,1,%s)",
            (fixture.CASE, fixture.INSURER, hospital, digests["replacement"]),
        )
        db.execute(
            """INSERT INTO zeroupfront_demo.preclaim_revisions(case_id,revision,policy,report,estimate,case_values,created_by)
                      VALUES(%s,1,%s,%s,%s,%s,'Fictional intake desk')""",
            (fixture.CASE, digests["policy"], digests["report"], digests["estimate"], Jsonb(values)),
        )


def summaries(dsn):
    with psycopg.connect(dsn) as db:
        rows = db.execute("""SELECT c.id,c.head,a.actor,s.revision,r.case_values,q.sequence,q.reply FROM zeroupfront_demo.preclaims c
            JOIN zeroupfront_demo.preclaim_revisions r ON r.case_id=c.id AND r.revision=c.head
            LEFT JOIN zeroupfront_demo.preclaim_reviews a ON a.case_id=c.id AND a.revision=c.head
            LEFT JOIN zeroupfront_demo.preclaim_submissions s ON s.case_id=c.id AND s.revision=c.head
            LEFT JOIN LATERAL (SELECT sequence,reply FROM zeroupfront_demo.preclaim_questions
                WHERE case_id=c.id AND revision=s.revision ORDER BY sequence DESC LIMIT 1) q ON true
            ORDER BY c.id""").fetchall()
    return [
        {
            "id": ident,
            "revision": rev,
            "member": values["member"],
            "patient": values["patient"],
            "procedure": values["procedure"],
            "insurer": values["insurer"],
            "total": values["total"],
            "admission_date": values["admission_date"],
            "intake": True,
            "input_kind": "payer_preclaim",
            "status": "staff_reviewed" if actor else "ready_for_review" if rev > 1 else "needs_review",
            "insurer_status": "submitted" if sent else "not_sent",
            "workflow_stage": "hospital_reply_needed" if sequence and reply is None else "hospital_replied" if sequence else "waiting_for_insurer"
            if sent
            else "staff_reviewed"
            if actor
            else "ready_for_review"
            if rev > 1
            else "needs_documents",
        }
        for ident, rev, actor, sent, values, sequence, reply in rows
    ]


def _insurer(request):
    if getattr(request.state, "role", "") != "insurer" or not getattr(request.state, "insurer", None):
        raise HTTPException(403, "Sign in with an insurer account to view its inbox.")
    return request.state.insurer


def _row(db, ident, revision=None, *, payer=None):
    row = db.execute(
        """SELECT c.id,c.insurer,c.hospital,c.head,r.revision,r.policy,r.report,r.estimate,r.draft,r.case_values,
                        a.actor AS reviewer,a.form,s.revision AS submitted_revision,s.created_at AS submitted_at
                 FROM zeroupfront_demo.preclaims c
                 JOIN zeroupfront_demo.preclaim_revisions r ON r.case_id=c.id AND r.revision=coalesce(%s::int,c.head)
                 LEFT JOIN zeroupfront_demo.preclaim_reviews a ON a.case_id=c.id AND a.revision=r.revision
                 LEFT JOIN zeroupfront_demo.preclaim_submissions s ON s.case_id=c.id AND s.revision=r.revision
                 WHERE c.id=%s AND (%s::text IS NULL OR (c.insurer=%s AND s.revision=r.revision))""",
        (revision, ident, payer, payer),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Pre-claim revision not found.")
    return row


def _value(db, digest):
    row = db.execute("SELECT pdf FROM zeroupfront_demo.documents WHERE digest=%s", (digest,)).fetchone()
    if not row:
        raise HTTPException(404, "Source document missing.")
    return bytes(row["pdf"])


def _check(db, row, report=None):
    return fixture.checks(
        _value(db, row["policy"]),
        _value(db, report or row["report"]),
        _value(db, row["estimate"]),
        row["id"],
        row["case_values"],
    )


def _detail(db, row, *, payer=None):
    verified, signed, estimated = _check(db, row)
    values = row["case_values"]
    base = hospital_path(("/api/insurer/preclaims/" if payer else "/api/preclaims/") + row["id"])
    source = f"{base}/revisions/{row['revision']}/sources/"
    rule = {
        "clause": "§4.2",
        "quote": values["rule_quote"],
        "page": values["rule_page"],
        "verified": verified,
        "source_url": source + "policy",
    }
    issues = []
    if not verified:
        issues.append(
            dict(code="unverified_rule", title="Verify the policy wording against the original page", **rule)
        )
    if not signed:
        issues.append(
            dict(code="missing_signed_report", title="Signed treating physician report required", **rule)
        )
    if not estimated:
        issues.append(
            {
                "code": "estimate_mismatch",
                "title": "Check the estimate against this encounter",
                "page": 1,
                "source_url": source + "estimate",
                "quote": "",
                "verified": False,
            }
        )
    status = (
        "waiting_for_insurer"
        if row["submitted_revision"]
        else "staff_reviewed"
        if row["form"]
        else "needs_documents"
        if issues
        else "ready_for_review"
    )
    questions = db.execute(
        """SELECT sequence,source_role,page,question,asked_at,reply,replied_at
           FROM zeroupfront_demo.preclaim_questions WHERE case_id=%s AND revision=%s ORDER BY sequence""",
        (row["id"], row["revision"]),
    ).fetchall() if row["submitted_revision"] else []
    if questions:
        status = "hospital_reply_needed" if questions[-1]["reply"] is None else "hospital_replied"
    sources = [
        {"role": key, "label": label, "page": page, "url": source + key, "quote": quote}
        for key, label, page, quote in (
            (
                "policy",
                "Global Select policy wording",
                values["rule_page"],
                values["rule_quote"] if verified else "",
            ),
            (
                "report",
                "Signed medical report" if signed else "Initial medical report",
                1,
                values["signature"]
                if signed
                else (
                    "Treating physician signature: Pending"
                    if "Treating physician signature: Pending" in fixture.pages(_value(db, row["report"]))[0]
                    else ""
                ),
            ),
            (
                "estimate",
                "Itemised estimate",
                1,
                f"Estimated total: {values['currency']} {values['total']:,}" if estimated else "",
            ),
        )
    ]
    return {
        "id": row["id"],
        "patient": values["patient"],
        "member": values["member"],
        "procedure": values["procedure"],
        "insurer": row["insurer"],
        "hospital": row["hospital"],
        "total": values["total"],
        "currency": values["currency"],
        "status": status,
        "revision": row["revision"],
        "current_revision": row["head"],
        "admission_date": values["admission_date"],
        "gap": issues[0] if issues else None,
        "issues": issues,
        "rule": rule,
        "sources": sources,
        "draft_url": source + "request" if row["form"] else source + "draft" if row["draft"] else None,
        "form_edition": values["form_edition"],
        "reviewer": row["reviewer"],
        "submitted_revision": row["submitted_revision"],
        "submitted_at": row["submitted_at"],
        "questions": questions,
        "simulation": True,
    }


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]


@router.get("/api/preclaims/{ident}")
def detail(request: Request, ident: str, revision: SelectedRevision = None):
    with psycopg.connect(request.app.state.dsn, row_factory=dict_row) as db:
        return _detail(db, _row(db, ident, revision))


@router.get("/api/insurer/preclaims")
def inbox(request: Request):
    payer = _insurer(request)
    with psycopg.connect(request.app.state.dsn, row_factory=dict_row) as db:
        entries = db.execute(
            """SELECT c.id,s.revision FROM zeroupfront_demo.preclaim_submissions s
                   JOIN zeroupfront_demo.preclaims c ON c.id=s.case_id WHERE c.insurer=%s ORDER BY s.created_at DESC""",
            (payer,),
        ).fetchall()
        return [_detail(db, _row(db, e["id"], e["revision"], payer=payer), payer=payer) for e in entries]


@router.get("/api/insurer/preclaims/{ident}")
def insurer_detail(request: Request, ident: str, revision: SelectedRevision = None):
    payer = _insurer(request)
    with psycopg.connect(request.app.state.dsn, row_factory=dict_row) as db:
        return _detail(db, _row(db, ident, revision, payer=payer), payer=payer)


def _source(request, ident, revision, role, payer=None):
    with psycopg.connect(request.app.state.dsn, row_factory=dict_row) as db:
        row = _row(db, ident, revision, payer=payer)
        if role == "draft" and payer:
            raise HTTPException(404, "Only the staff-reviewed request was submitted.")
        digest = row["form"] if role == "request" else row[role]
        return _pdf(_value(db, digest), f"{row['id']}-R{revision}-{role}.pdf")


@router.get("/api/preclaims/{ident}/revisions/{revision}/sources/{role}")
def source(request: Request, ident: str, revision: int, role: SourceRole):
    return _source(request, ident, revision, role)


@router.get("/api/insurer/preclaims/{ident}/revisions/{revision}/sources/{role}")
def insurer_source(request: Request, ident: str, revision: int, role: SourceRole):
    return _source(request, ident, revision, role, _insurer(request))


@router.get("/api/preclaims/{ident}/report-example")
def report_example(request: Request, ident: str):
    with psycopg.connect(request.app.state.dsn, row_factory=dict_row) as db:
        row = db.execute("SELECT replacement FROM zeroupfront_demo.preclaims WHERE id=%s", (ident,)).fetchone()
        if not row:
            raise HTTPException(404, "Pre-claim not found.")
        return _pdf(_value(db, row["replacement"]), "fictional-signed-medical-report.pdf")


class CitedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_role: Literal["policy", "report", "estimate", "request"]
    page: int = Field(ge=1)
    question: str = Field(min_length=1, max_length=1500)
    previous_sequence: int = Field(ge=0)


class HospitalReply(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reply: str = Field(min_length=1, max_length=3000)


def _submitted_for_update(db, ident, revision, payer=None):
    # Authorize the submitted revision before locking its correspondence.
    row = _row(db, ident, revision, payer=payer)
    locked = db.execute(
        "SELECT revision FROM zeroupfront_demo.preclaim_submissions WHERE case_id=%s AND revision=%s FOR UPDATE",
        (ident, revision),
    ).fetchone()
    if not locked or row["head"] != revision:
        raise HTTPException(409, "Reopen the current submitted revision before responding.")
    return row


@router.post("/api/insurer/preclaims/{ident}/clarifications")
def ask_question(request: Request, ident: str, question: CitedQuestion, if_match: Match = None):
    revision, payer = _revision(if_match), _insurer(request)
    with psycopg.connect(request.app.state.dsn, row_factory=dict_row) as db:
        row = _submitted_for_update(db, ident, revision, payer)
        latest = db.execute(
            "SELECT sequence,reply FROM zeroupfront_demo.preclaim_questions "
            "WHERE case_id=%s AND revision=%s ORDER BY sequence DESC LIMIT 1", (ident, revision),
        ).fetchone()
        if (latest and latest["reply"] is None) or question.previous_sequence != (latest["sequence"] if latest else 0):
            raise HTTPException(409, "This conversation changed. Reload the current request.")
        digest = row["form" if question.source_role == "request" else question.source_role]
        if question.page > len(fixture.pages(_value(db, digest))):
            raise HTTPException(422, "Choose a page in the submitted document.")
        db.execute(
            """INSERT INTO zeroupfront_demo.preclaim_questions
               (case_id,revision,sequence,source_role,page,question,asked_by) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (ident, revision, question.previous_sequence + 1, question.source_role, question.page,
             question.question, request.state.username),
        )
        return _detail(db, row, payer=payer)


@router.post("/api/preclaims/{ident}/clarifications/{sequence}/reply")
def answer_question(request: Request, ident: str, sequence: int, answer: HospitalReply, if_match: Match = None):
    if not getattr(request.state, "username", None) or request.state.role != "hospital":
        raise HTTPException(403, "Hospital staff sign-in required to answer this question.")
    revision = _revision(if_match)
    with psycopg.connect(request.app.state.dsn, row_factory=dict_row) as db:
        row = _submitted_for_update(db, ident, revision)
        saved = db.execute(
            """UPDATE zeroupfront_demo.preclaim_questions SET reply=%s,replied_by=%s,replied_at=now()
               WHERE case_id=%s AND revision=%s AND sequence=%s AND reply IS NULL""",
            (answer.reply, request.state.username, ident, revision, sequence),
        )
        if saved.rowcount != 1:
            raise HTTPException(409, "This question has changed. Reload the current request.")
        return _detail(db, row)


Action = Literal["attach-report", "review", "submit"]


@router.post("/api/preclaims/{ident}/{action}")
def advance(request: Request, ident: str, action: Action, confirmation: Confirmation, if_match: Match = None):
    base = _revision(if_match)
    actor = _actor(request, None)
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(403, "Staff sign-in is required to update this request.")
    with psycopg.connect(request.app.state.dsn, row_factory=dict_row) as db:
        locked = db.execute(
            "SELECT head,replacement FROM zeroupfront_demo.preclaims WHERE id=%s FOR UPDATE", (ident,)
        ).fetchone()
        if not locked:
            raise HTTPException(404, "Pre-claim not found.")
        if locked["head"] != base:
            raise HTTPException(412, "The evidence revision changed. Reopen the current case.")
        row = _row(db, ident, base)
        verified, signed, estimated = _check(db, row)
        if action == "attach-report":
            if not verified or not estimated or signed or row["form"] or row["submitted_revision"]:
                raise HTTPException(409, "This revision cannot accept the bundled signed replacement.")
            if _check(db, row, locked["replacement"]) != (True, True, True):
                raise HTTPException(
                    422, "The replacement does not satisfy the encounter and signed-report checks."
                )
            draft = _save_document(db, fixture.request_pdf(ident, row["case_values"], base + 1))
            db.execute(
                """INSERT INTO zeroupfront_demo.preclaim_revisions(case_id,revision,policy,report,estimate,case_values,draft,created_by)
                          VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    ident,
                    base + 1,
                    row["policy"],
                    locked["replacement"],
                    row["estimate"],
                    Jsonb(row["case_values"]),
                    draft,
                    username,
                ),
            )
            db.execute("UPDATE zeroupfront_demo.preclaims SET head=%s WHERE id=%s", (base + 1, ident))
        elif action == "review":
            if not verified or not signed or not estimated or not row["draft"] or row["form"]:
                raise HTTPException(409, "Only a complete draft awaiting staff review can be reviewed.")
            form = _save_document(db, fixture.request_pdf(ident, row["case_values"], base, actor))
            db.execute(
                "INSERT INTO zeroupfront_demo.preclaim_reviews(case_id,revision,actor,username,form) VALUES(%s,%s,%s,%s,%s)",
                (ident, base, actor, username, form),
            )
        else:
            if not row["form"] or not verified or not signed or not estimated or row["submitted_revision"]:
                raise HTTPException(409, "Only a reviewed, complete revision can be sent once.")
            db.execute(
                "INSERT INTO zeroupfront_demo.preclaim_submissions(case_id,revision,actor,username) VALUES(%s,%s,%s,%s)",
                (ident, base, actor, username),
            )
        return _detail(db, _row(db, ident))
