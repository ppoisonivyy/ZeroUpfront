"""Independent discharge intake and manual settlement records for one hospital."""

from datetime import date
import json
import os
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from openai import APIError, OpenAI
from pydantic import BaseModel, ConfigDict, Field

from app import discharge_store as store
from app import payer_ai_reader as ai_reader
from app.workspace_store import coordinate_ocr
from app.case_workflow import validate_attachment
from app.workspace_http_common import _actor, _pdf, _read_upload, _revision, accept_files, ocr_service_error


router = APIRouter(prefix="/api/discharge", tags=["Discharge"])
Role = Literal["bill", "summary", "letter", "records"]
Upload = Annotated[UploadFile | None, File()]
Match = Annotated[str | None, Header(alias="If-Match")]
PDF = {200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}}


class PageAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role
    page: Annotated[int, Field(strict=True, ge=1, le=200)]
    sha256: Annotated[str, Field(pattern="^[a-f0-9]{64}$")]
    transcript_sha256: Annotated[str, Field(pattern="^[a-f0-9]{64}$")]


class AttestationSummary(BaseModel):
    reviewer: str
    username: str | None = None
    source_revision: int
    pages: list[PageAttestation]


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


class WorklistCounts(BaseModel):
    all: int
    needs: int
    ready: int
    payer: int


class WorklistPage(BaseModel):
    items: list[Summary]
    counts: WorklistCounts
    total: int
    page: int
    page_size: int


class Detail(Summary):
    ai_review_enabled: bool = Field(default_factory=ai_reader.enabled)
    facility: str | None = None
    as_of: str | None = None
    prior_case_id: str | None
    prior_revision: int | None
    source_reported_cap_minor: int | None = None
    source_reported_patient_share_minor: int | None = None
    payable_minor: int | None = None
    findings: list[dict]
    checks: list[dict] = Field(default_factory=list)
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
    letter_kind: str | None = None
    ocr_review_available: bool = False
    ocr_page_count: int = 0
    ocr_attestation: AttestationSummary | None = None


def _evaluate(meta, raw, names, ocr, saved_ocr=None):
    from app.discharge_claim import evaluate_discharge

    options = {"_saved_ocr": saved_ocr} if saved_ocr else {}
    if os.getenv("WORKSPACE_AUTH_MODE", "staff") != "local" and meta.get("as_of", "") > date.today().isoformat():
        raise HTTPException(422, "The review date cannot be in the future.")

    try:
        if ocr:
            if os.getenv("WORKSPACE_ENABLE_OCR") != "1" or not os.getenv("OPENAI_API_KEY"):
                raise HTTPException(503, "Cloud OCR is unavailable on this installation.")
            with OpenAI(timeout=90, max_retries=1) as client:
                evidence = evaluate_discharge(meta, raw, names, ocr_client=client, **options)
        else:
            evidence = evaluate_discharge(meta, raw, names, **options)
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


class WorklistFilters(BaseModel):
    page: int = Field(default=1, ge=1, le=2_147_483_647)
    page_size: int = Field(default=25, ge=1, le=100)
    queue: Literal["all", "needs", "ready", "payer"] = "all"


class WorklistSearch(WorklistFilters):
    search: str = Field(max_length=250)


@router.get("/worklist", response_model=WorklistPage)
def worklist(request: Request, filters: Annotated[WorklistFilters, Query()]):
    if request.query_params.get("search"):
        raise HTTPException(422, "Send claim search text in the body of POST /api/discharge/worklist/search.")
    return store.worklist(request.app.state.dsn, filters.queue, "", filters.page, filters.page_size)


@router.post("/worklist/search", response_model=WorklistPage)
def search_worklist(request: Request, filters: WorklistSearch):
    return store.worklist(request.app.state.dsn, filters.queue, filters.search.strip(), filters.page, filters.page_size)


@router.post("", response_model=Detail, status_code=201, dependencies=[Depends(accept_files("bill", "summary", "letter", "records"))])
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
    with coordinate_ocr(request.app.state.dsn, "discharge", key, ocr) as db:
        if key:
            previous = store.previous_intake(db, key)
            if previous:
                return previous
        result = _evaluate(meta, raw, names, ocr)
        return store.create(db, ident, result, raw, names, prior_case_id or None, key)


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


def _screen_metadata(case):
    return {
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


@router.post("/{ident}/documents", response_model=Detail, dependencies=[Depends(accept_files("bill", "summary", "letter", "records", "file"))])
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
    as_of: Annotated[date | None, Form()] = None,
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
    meta = _screen_metadata(case)
    if as_of:
        meta["as_of"] = as_of.isoformat()
    elif os.getenv("WORKSPACE_AUTH_MODE", "staff") != "local":
        meta["as_of"] = date.today().isoformat()
    result = _evaluate(meta, raw, names, ocr, case.get("ocr_pages"))
    return store.replace(dsn, ident, base, result, raw, names)


async def _no_recheck_inputs(request: Request):
    async for chunk in request.stream():
        if chunk:
            raise HTTPException(422, "Rechecking uses the saved originals. Use document correction to upload a file.")


@router.post("/{ident}/recheck", response_model=Detail, dependencies=[Depends(_no_recheck_inputs)])
def recheck(request: Request, ident: str, if_match: Match = None):
    dsn, base = request.app.state.dsn, _revision(if_match)
    case, raw, names = store.snapshot(dsn, ident, base)
    if case["status"] != "needs_review":
        raise HTTPException(409, "Only the current discharge revision held for investigation can be rechecked.")
    result = _evaluate(_screen_metadata(case), raw, names, False, case.get("ocr_pages"))
    if case.get("sample_bill_available"):
        result["sample_bill_available"] = True
    return store.replace(dsn, ident, base, result, raw, names, recheck=True)


@router.post("/{ident}/second-read", response_model=ai_reader.SecondReadResponse)
def second_read(request: Request, response: Response, ident: str, options: ai_reader.SecondReadRequest, if_match: Match = None):
    base = _revision(if_match)
    if not options.confirmed:
        raise HTTPException(422, "Confirm sending this revision’s original PDFs for a provisional AI second read.")
    if not ai_reader.enabled():
        raise HTTPException(503, "AI second read is disabled or unavailable on this installation.")
    dsn = request.app.state.dsn
    case, raw, _ = store.snapshot(dsn, ident, base)
    try:
        advisory = ai_reader.second_read(case, raw, options.family)
    except ai_reader.UnsupportedPacket as exc:
        raise HTTPException(422, str(exc)) from exc
    except ai_reader.InvalidReview as exc:
        raise HTTPException(502, str(exc)) from exc
    except APIError as exc:
        status = ocr_service_error(exc).status_code
        raise HTTPException(status, "The AI second read could not be completed by the configured provider.") from exc
    if store.detail(dsn, ident)["revision"] != base:
        raise HTTPException(412, "The discharge packet changed during the AI read. Open the current revision.")
    response.headers["Cache-Control"] = "private, no-store"
    return advisory


class OcrVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer: str | None = None
    pages: Annotated[list[PageAttestation], Field(min_length=1, max_length=800)]


@router.get("/{ident}/revisions/{revision}/ocr-review")
def review_pages(request: Request, ident: str, revision: int):
    from app.discharge_claim import discharge_ocr_review_pages

    case = store.detail(request.app.state.dsn, ident, revision)
    sources = {source["role"]: source["url"] for source in case["sources"]}
    try:
        pages = [dict(page, source_url=sources[page["role"]]) for page in discharge_ocr_review_pages(case)]
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "revision": revision,
        "eligible": case["ocr_review_available"] and revision == case["history"][0]["revision"],
        "pages": pages,
        "reviewed_by": (case.get("ocr_attestation") or {}).get("reviewer"),
    }


@router.post("/{ident}/verify-ocr", response_model=Detail)
def verify_ocr(request: Request, ident: str, review: OcrVerification, if_match: Match = None):
    from app.discharge_claim import confirm_discharge_ocr

    dsn, base = request.app.state.dsn, _revision(if_match)
    actor = _actor(request, review.reviewer)
    case, raw, names = store.snapshot(dsn, ident, base)
    if not case["ocr_review_available"]:
        raise HTTPException(409, "Only an outstanding transcription-only review can be confirmed.")
    try:
        result = confirm_discharge_ocr(case, raw, actor, [page.model_dump() for page in review.pages])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result.get("status") != "ready_for_review" or result.get("findings"):
        raise HTTPException(409, "Unresolved findings still require an updated discharge packet.")
    result["ocr_attestation"]["username"] = getattr(request.state, "username", None)
    return store.replace(dsn, ident, base, result, raw, names, attested=True)


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


@router.post("/{ident}/workflow", response_model=Detail, dependencies=[Depends(accept_files("file"))])
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
