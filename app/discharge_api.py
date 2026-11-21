"""Independent discharge intake and manual settlement records for one hospital."""

from datetime import date
import json
import os
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from openai import APIError, OpenAI
from pydantic import BaseModel, Field

from app import discharge_store as store
from app.case_workflow import validate_attachment
from app.workspace_http_common import _actor, _pdf, _read_upload, _revision, ocr_service_error


router = APIRouter(prefix="/api/discharge", tags=["Discharge"])
Role = Literal["bill", "summary", "letter", "records"]
Upload = Annotated[UploadFile | None, File()]
Match = Annotated[str | None, Header(alias="If-Match")]
PDF = {200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}}


class Summary(BaseModel):
    id: str
    revision: int
    member: str
    procedure: str
    encounter: str
    insurer: str | None = None
    admission_date: str
    discharge_date: str
    status: str
    insurer_status: str
    currency: str | None = None
    bill_total_minor: int | None = None


class Detail(Summary):
    facility: str | None = None
    as_of: str | None = None
    prior_case_id: str | None
    prior_revision: int | None
    source_reported_cap_minor: int | None = None
    source_reported_patient_share_minor: int | None = None
    payable_minor: int | None = None
    findings: list[dict]
    sources: list[dict]
    history: list[dict]
    reviewer: str | None
    reviewer_username: str | None
    events: list[dict]
    workflow_version: int
    allowed_actions: list[str]
    payer_decision: dict | None
    settlement_status: str
    paid_by_currency: dict[str, int]
    case_paid_by_currency: dict[str, int]
    sample_bill_available: bool = False


def _evaluate(meta, raw, names, ocr):
    from app.discharge_claim import evaluate_discharge

    try:
        if ocr:
            if os.getenv("WORKSPACE_ENABLE_OCR") != "1" or not os.getenv("OPENAI_API_KEY"):
                raise HTTPException(503, "Cloud OCR is unavailable on this installation.")
            with OpenAI(timeout=90, max_retries=1) as client:
                evidence = evaluate_discharge(meta, raw, names, ocr_client=client)
        else:
            evidence = evaluate_discharge(meta, raw, names)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except APIError as exc:
        raise ocr_service_error(exc) from exc
    return {**meta, **evidence}


def _files(uploads):
    chosen = {role: f for role, f in uploads.items() if f is not None}
    if not chosen:
        raise HTTPException(422, "Upload at least one discharge exhibit.")
    return {role: _read_upload(f) for role, f in chosen.items()}, {role: f.filename for role, f in chosen.items()}


@router.get("", response_model=list[Summary])
def queue(request: Request):
    return store.summaries(request.app.state.dsn)


@router.post("", response_model=Detail, status_code=201)
def intake(
    request: Request,
    member: Annotated[str, Form(min_length=1, max_length=150)],
    encounter: Annotated[str, Form(min_length=1, max_length=150)],
    procedure: Annotated[str, Form(min_length=1, max_length=250)],
    admission_date: Annotated[date, Form()],
    discharge_date: Annotated[date, Form()],
    confirmed: Annotated[bool, Form()],
    insurer: Annotated[str, Form(min_length=1, max_length=160)],
    facility: Annotated[str, Form(min_length=1, max_length=160)],
    bill: Upload = None,
    summary: Upload = None,
    letter: Upload = None,
    records: Upload = None,
    prior_case_id: Annotated[str | None, Form()] = None,
    as_of: Annotated[date | None, Form()] = None,
    ocr: Annotated[bool, Form()] = False,
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None,
):
    if not confirmed:
        raise HTTPException(422, "Confirm the discharge exhibits belong to this encounter.")
    if discharge_date < admission_date:
        raise HTTPException(422, "Discharge must be on or after admission.")
    ident = "D" + uuid4().hex
    meta = dict(
        id=ident,
        member=member.strip(),
        encounter=encounter.strip(),
        procedure=procedure.strip(),
        admission_date=admission_date.isoformat(),
        discharge_date=discharge_date.isoformat(),
    )
    meta.update(insurer=insurer.strip(), facility=facility.strip())
    if as_of:
        meta["as_of"] = as_of.isoformat()
    raw, names = _files(dict(bill=bill, summary=summary, letter=letter, records=records))
    result = _evaluate(meta, raw, names, ocr)
    key = None
    if idempotency_key:
        metadata = {k: v for k, v in meta.items() if k != "id"}
        manifest = {role: store.document_digest(data) for role, data in raw.items()}
        encoded = json.dumps([metadata, manifest, names, prior_case_id, ocr], sort_keys=True).encode()
        key = (
            getattr(request.state, "username", None) or "local",
            idempotency_key,
            store.document_digest(encoded),
        )
    return store.create(request.app.state.dsn, ident, result, raw, names, prior_case_id or None, key)


@router.post("/examples/{scenario}", response_model=Detail, status_code=201)
def example(request: Request, scenario: str):
    from app.discharge_claim import load_discharge_fixture

    if os.getenv("WORKSPACE_AUTH_MODE", "staff") != "local":
        raise HTTPException(404, "Local discharge example not found.")
    try:
        meta, raw, names = load_discharge_fixture(scenario)
    except (ValueError, KeyError) as exc:
        raise HTTPException(404, "Local discharge example not found.") from exc
    ident = "D" + uuid4().hex
    result = _evaluate(dict(meta, id=ident), raw, names, False)
    result["sample_bill_available"] = scenario == "duplicate_line"
    return store.create(request.app.state.dsn, ident, result, raw, names)


@router.get("/{ident}", response_model=Detail)
def detail(request: Request, ident: str, revision: Annotated[int | None, Query(ge=1)] = None):
    return store.detail(request.app.state.dsn, ident, revision)


def _sample_bill(case):
    from app.discharge_claim import load_discharge_fixture

    if os.getenv("WORKSPACE_AUTH_MODE", "staff") != "local" or not case.get("sample_bill_available"):
        raise HTTPException(404, "No local corrected bill is available for this revision.")
    _, raw, names = load_discharge_fixture("aligned")
    return raw["bill"], names["bill"]


@router.get("/{ident}/sample-bill", response_class=Response, responses=PDF)
def sample_bill(request: Request, ident: str):
    raw, _ = _sample_bill(store.detail(request.app.state.dsn, ident))
    return _pdf(raw, f"{ident}-corrected-bill.pdf")


@router.post("/{ident}/documents", response_model=Detail)
def documents(
    request: Request,
    ident: str,
    confirmed: Annotated[bool, Form()],
    if_match: Match = None,
    bill: Upload = None,
    summary: Upload = None,
    letter: Upload = None,
    records: Upload = None,
    role: Annotated[Role | None, Form()] = None,
    file: Upload = None,
    ocr: Annotated[bool, Form()] = False,
    sample_bill: Annotated[bool, Form()] = False,
):
    if not confirmed:
        raise HTTPException(422, "Confirm the replacement belongs to this discharge encounter.")
    uploads = dict(bill=bill, summary=summary, letter=letter, records=records)
    if file is not None or role is not None:
        if file is None or role is None or any(uploads.values()):
            raise HTTPException(422, "Choose named exhibits or one role and file.")
        uploads = {role: file}
    dsn, base = request.app.state.dsn, _revision(if_match)
    case, raw, names = store.snapshot(dsn, ident, base)
    if sample_bill:
        if any(uploads.values()):
            raise HTTPException(422, "Choose a local corrected bill or upload exhibits.")
        sample, filename = _sample_bill(case)
        new_raw, new_names = {"bill": sample}, {"bill": filename}
    else:
        new_raw, new_names = _files(uploads)
    raw.update(new_raw)
    names.update(new_names)
    meta = {
        k: case[k]
        for k in (
            "id",
            "member",
            "encounter",
            "procedure",
            "admission_date",
            "discharge_date",
            "insurer",
            "facility",
            "as_of",
        )
        if case.get(k) is not None
    }
    result = _evaluate(meta, raw, names, ocr)
    return store.replace(dsn, ident, base, result, raw, names)


class Approval(BaseModel):
    reviewer: str | None = None


@router.post("/{ident}/approve", response_model=Detail)
def approve(request: Request, ident: str, approval: Approval, if_match: Match = None):
    return store.approve(
        request.app.state.dsn,
        ident,
        _revision(if_match),
        _actor(request, approval.reviewer),
        getattr(request.state, "username", None),
    )


def _render(dsn, ident, revision):
    from app.discharge_claim import discharge_packet_bytes

    case, raw, _ = store.snapshot(dsn, ident, revision, approved=True)
    try:
        return discharge_packet_bytes(case, raw)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{ident}/export", response_class=Response, responses=PDF)
def export(request: Request, ident: str, revision: Annotated[int, Query(ge=1)]):
    dsn = request.app.state.dsn
    data = _render(dsn, ident, revision)
    if store.detail(dsn, ident)["revision"] != revision:
        raise HTTPException(412, "A newer discharge revision is available.")
    return _pdf(data, f"{ident}-r{revision}-discharge-request.pdf", "attachment")


class Workflow(BaseModel):
    action: Literal["submission", "reply", "payment"]
    workflow_version: int = Field(ge=0)
    target_revision: int | None = Field(default=None, ge=1)
    actor: str | None = None
    reference: str | None = None
    channel: str | None = None
    outcome: str | None = None
    terms: str | None = None
    notes: str | None = None
    amount: str | None = None
    currency: str | None = None
    confirmed: bool = False
    file: UploadFile | None = None


@router.post("/{ident}/workflow", response_model=Detail)
def workflow(
    request: Request,
    ident: str,
    form: Annotated[Workflow, Form(media_type="multipart/form-data")],
    if_match: Match = None,
):
    base = _revision(if_match)
    raw = name = None
    if form.file is not None:
        raw, name = _read_upload(form.file), form.file.filename
        try:
            validate_attachment(raw, name)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    submitted = _render(request.app.state.dsn, ident, base) if form.action == "submission" else None
    return store.record(
        request.app.state.dsn,
        ident,
        base,
        form.model_dump(exclude={"file"}),
        _actor(request, form.actor),
        getattr(request.state, "username", None),
        raw,
        name,
        submitted,
    )


@router.get("/{ident}/revisions/{revision}/sources/{role}", response_class=Response, responses=PDF)
def source(request: Request, ident: str, revision: int, role: Role):
    return _pdf(store.source(request.app.state.dsn, ident, revision, role=role), f"{ident}-r{revision}-{role}.pdf")


@router.get("/{ident}/revisions/{revision}/events/{event_id}/source", response_class=Response, responses=PDF)
def event_source(request: Request, ident: str, revision: int, event_id: int):
    return _pdf(
        store.source(request.app.state.dsn, ident, revision, event_id=event_id),
        f"{ident}-r{revision}-event-{event_id}.pdf",
    )
