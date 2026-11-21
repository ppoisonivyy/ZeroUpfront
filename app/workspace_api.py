"""HTTP contract for the synthetic coordinator demo. Run app.workspace_server:app for the UI."""
from contextlib import asynccontextmanager
import os
import json
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4
from datetime import date

from fastapi import APIRouter, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from openai import APIError, OpenAI
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app import workspace_store as store
from app import discharge_store, preclaims
from app.discharge_api import router as discharge_router
from app.workspace_http_common import INTAKE_BYTES, MultipartBodyLimit, _actor, _pdf, _read_upload, _revision, ocr_service_error
from app.case_workflow import validate_attachment
from app.staff_access import install_access, initialize_access, mode
from app.hospital_platform import HospitalContext, bind_database, build_platform
from app.workspace_documents import CASE_INSURERS, evaluate_estimate, packet_bytes, seed_cases

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
Role = Literal["policy", "estimate", "plan"]
Status = Literal["needs_itemization", "possible_exclusion", "ready_for_review", "staff_reviewed", "needs_review"]


class Line(BaseModel):
    label: str
    amount: int


class Source(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: Role
    label: str
    url: str
    page: int
    quote: str


class HistoryEntry(BaseModel):
    revision: int
    status: Status
    total: int | None


class Summary(HistoryEntry):
    id: str
    procedure: str
    insurer: str
    member: str
    admission_date: str
    intake: bool = False
    patient: str | None = None
    workflow_stage: str | None = None
    input_kind: str | None = None
    insurer_status: str = "not_sent"
    latest_event_kind: str | None = None
    open_hold_count: int = 0


class Case(Summary):
    open_holds: list[dict] = Field(default_factory=list)
    policy_edition: str
    clause: str | None
    reason: str
    lines: list[Line]
    sources: list[Source]
    history: list[HistoryEntry]
    reviewer: str | None
    reviewer_username: str | None = None
    currency: str | None = "THB"
    workflow_version: int
    events: list[dict]
    allowed_actions: list[str]
    admission_check: dict | None
    deposit_decision: dict | None
    manual_review: dict | None = None
    clarification_available: bool = False
    sample_estimate_available: bool = False
    issues: list[str] = Field(default_factory=list)
    input_kind: str | None = None


class Approval(BaseModel):
    reviewer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

    @field_validator("reviewer")
    @classmethod
    def valid_display_name(cls, value):
        if not value.isprintable():
            raise ValueError("Enter a printable reviewer name.")
        return value


def _documents(case_id, estimate):
    return {"policy": (FIXTURES / "policies" / (CASE_INSURERS[case_id] + ".pdf")).read_bytes(),
            "plan": (FIXTURES / "cases" / case_id / "plan.pdf").read_bytes(),
            "estimate": estimate}


def _sample(case_id, detail):
    if case_id == "Z002":
        return (FIXTURES / "cases" / "Z002" / "revised-estimate.pdf").read_bytes()
    if detail.get("sample_estimate_available") and mode() == "local":
        from app.journey_examples import exhibits
        return exhibits("clean")[1]["estimate"]
    raise HTTPException(404, "No bundled correction is available for this case.")


def _evaluate(case_id, data, filename):
    # A private upload can never reach the cloud. The OCR path accepts only the exact committed demo scan.
    is_demo_scan = case_id == "Z002" and data == (FIXTURES / "cases/Z002/scanned-estimate.pdf").read_bytes()
    try:
        if is_demo_scan and os.getenv("WORKSPACE_ENABLE_OCR") == "1":
            if not os.getenv("OPENAI_API_KEY"):
                raise HTTPException(503, "The demo OCR service needs a configured OpenAI API key.")
            with OpenAI(timeout=90, max_retries=1) as client:
                return evaluate_estimate(case_id, data, filename, ocr_client=client)
        return evaluate_estimate(case_id, data, filename)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except APIError as exc:
        raise ocr_service_error(exc) from exc


@asynccontextmanager
async def lifespan(app):
    hospital = getattr(app.state, "hospital", None)
    dsn = hospital.dsn if hospital else os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("Set DATABASE_URL to the PostgreSQL database for the synthetic coordinator workspace.")
    seeds = []
    if hospital:
        bind_database(hospital)
    seed = not hospital and os.getenv("WORKSPACE_SEED_DEMO", "1" if mode() == "local" else "0") == "1"
    for case in seed_cases() if seed else []:
        case_id = case["id"]
        estimate = (FIXTURES / "cases" / case_id / "estimate.pdf").read_bytes()
        seeds.append((case, _documents(case_id, estimate)))
    store.initialize(dsn, seeds)
    discharge_store.initialize(dsn)
    preclaims.initialize(dsn)
    initialize_access(dsn)
    app.state.dsn = dsn
    app.state.hospital_name = hospital.name if hospital else os.getenv("WORKSPACE_HOSPITAL_NAME", "").strip()
    yield


router = APIRouter()


async def workspace_error(request, exc):
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)}, headers=headers)


@router.get("/api/cases", response_model=list[Summary])
def cases(request: Request):
    return preclaims.summaries(request.app.state.dsn) + store.list_cases(request.app.state.dsn)


@router.get("/api/cases/{case_id}", response_model=Case)
def case(request: Request, case_id: str, revision: Annotated[int | None, Query(ge=1)] = None):
    return store.case_detail(request.app.state.dsn, case_id, revision)


PDF_RESPONSES = {200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}}


@router.get("/api/cases/{case_id}/sample-estimate", response_class=Response, responses=PDF_RESPONSES)
def sample_estimate(request: Request, case_id: str):
    detail = store.case_detail(request.app.state.dsn, case_id)
    return _pdf(_sample(case_id, detail), f"{case_id}-revised-estimate.pdf")


def _intake(metadata, documents, names, ocr, saved_ocr=None):
    from app.intake_documents import evaluate_intake
    try:
        if ocr:
            if os.getenv("WORKSPACE_ENABLE_OCR") != "1" or not os.getenv("OPENAI_API_KEY"):
                raise HTTPException(503, "Cloud OCR is unavailable on this installation.")
            with OpenAI(timeout=90, max_retries=1) as client:
                return evaluate_intake(metadata, documents, names, ocr_client=client, _saved_ocr=saved_ocr)
        return evaluate_intake(metadata, documents, names, _saved_ocr=saved_ocr)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except APIError as exc:
        raise ocr_service_error(exc) from exc


@router.post("/api/cases", response_model=Case, status_code=201)
def create_case(request: Request, policy: Annotated[UploadFile, File()], plan: Annotated[UploadFile, File()],
                estimate: Annotated[UploadFile, File()], member: Annotated[str, Form(min_length=1, max_length=200)],
                insurer: Annotated[str, Form(min_length=1, max_length=200)],
                policy_edition: Annotated[str, Form(min_length=1, max_length=120)],
                procedure: Annotated[str, Form(min_length=1, max_length=300)], admission_date: Annotated[date, Form()],
                confirmed: Annotated[bool, Form()], ocr: Annotated[bool, Form()] = False,
                idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None):
    if not confirmed:
        raise HTTPException(422, "Confirm the uploaded files belong to the same encounter.")
    files = {"policy": policy, "plan": plan, "estimate": estimate}
    names = {role: file.filename for role, file in files.items()}
    documents = {role: _read_upload(file) for role, file in files.items()}
    metadata = dict(id="C" + uuid4().hex, member=member.strip(), insurer=insurer.strip(),
                    policy_edition=policy_edition.strip(), procedure=procedure.strip(), admission_date=admission_date.isoformat())
    if not all(metadata.values()):
        raise HTTPException(422, "Enter all encounter identifiers.")
    dsn = request.app.state.dsn
    request_key = None
    if idempotency_key is not None:
        digests = {role: store.document_digest(data) for role, data in documents.items()}
        inputs = {k: v for k, v in metadata.items() if k != "id"}
        payload = json.dumps([inputs, digests, names, ocr], sort_keys=True, ensure_ascii=False).encode()
        request_key = (getattr(request.state, "username", None) or "local", idempotency_key, store.document_digest(payload))
    with store.coordinate_ocr(dsn, "admission", request_key, ocr) as db:
        if request_key:
            previous = store.previous_intake(db, request_key)
            if previous:
                return previous
        result = _intake(metadata, documents, names, ocr)
        return store.create_case(db, result, documents, request_key)


@router.post("/api/examples/{scenario}", response_model=Case, status_code=201)
def local_example(request: Request, scenario: str):
    from app.journey_examples import LOCAL_EXAMPLES, NAMES, admission, exhibits, payer_reply
    if mode() != "local" or scenario not in LOCAL_EXAMPLES:
        raise HTTPException(404, "Local case example not found.")
    meta, documents = exhibits(scenario)
    meta["id"] = "C" + uuid4().hex
    evidence = _intake(meta, documents, NAMES, False)
    evidence["sample_estimate_available"] = scenario == "missing-estimate"
    events = []
    if scenario in {"partial-guarantee", "admission-mismatch"}:
        events.append(("submission", {"reference": "DEMO-PORTAL-58", "channel": "Simulated payer portal"}, None))
        fields, letter = payer_reply("partial" if scenario == "partial-guarantee" else "guaranteed")
        events.append(("reply", fields, letter))
    if scenario == "admission-mismatch":
        events.append(("admission", admission(actual_admission_date="2026-12-18"), None))
    return store.create_example(request.app.state.dsn, evidence, documents, events)


@router.post("/api/cases/{case_id}/estimate", response_model=Case)
def replace_estimate(request: Request, case_id: str, file: Annotated[UploadFile | None, File()] = None,
                     sample: Annotated[bool, Form()] = False, confirmed: Annotated[bool, Form()] = False,
                     ocr: Annotated[bool, Form()] = False,
                     if_match: Annotated[str | None, Header()] = None):
    """Confirm that the candidate estimate belongs to this synthetic encounter before replacement."""
    base = _revision(if_match)
    if not confirmed:
        raise HTTPException(422, "Confirm the estimate belongs to this encounter.")
    if sample == (file is not None):
        raise HTTPException(422, "Choose exactly one PDF or the bundled sample.")
    dsn = request.app.state.dsn
    detail = store.case_detail(dsn, case_id)
    if detail["revision"] != base:
        raise HTTPException(412, "The case has a newer revision. Open the current revision before continuing.")
    if sample:
        data, filename = _sample(case_id, detail), "revised-estimate.pdf"
    else:
        data, filename = _read_upload(file, INTAKE_BYTES if detail["intake"] else MAX_UPLOAD_BYTES), file.filename
    if detail["intake"]:
        current, documents = store.revision_snapshot(dsn, case_id, base)
        names = {source["role"]: source["label"] for source in current["sources"]}
        names["estimate"] = filename
        documents["estimate"] = data
        metadata = {key: current[key] for key in ("id","member","insurer","policy_edition","procedure","admission_date")}
        result = _intake(metadata, documents, names, ocr, current.get("ocr_pages"))
        return store.replace_estimate(dsn, case_id, base, result, documents)
    evidence = _evaluate(case_id, data, filename)
    # Parsing and optional cloud OCR finish before the transaction. Recheck the base under a case lock.
    return store.replace_estimate(dsn, case_id, base, evidence, _documents(case_id, data))


@router.post("/api/cases/{case_id}/approve", response_model=Case)
def approve_case(request: Request, case_id: str, approval: Approval, if_match: Annotated[str | None, Header()] = None):
    return store.approve(request.app.state.dsn, case_id, _revision(if_match), _actor(request, approval.reviewer),
                         getattr(request.state, "username", None))


@router.get("/api/cases/{case_id}/export", response_class=Response, responses=PDF_RESPONSES)
def export_case(request: Request, case_id: str, revision: Annotated[int, Query(ge=1)]):
    dsn = request.app.state.dsn
    approved, originals = store.revision_snapshot(dsn, case_id, revision, approved=True)
    try:
        # Render the approved request as originally prepared, including on subsequent downloads after submission.
        pdf = packet_bytes(dict(approved, insurer_status="not_sent"), originals)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    # Reject a replacement that committed during rendering, without keeping a database lock during PDF generation.
    store.check_export_current(dsn, case_id, revision)
    return _pdf(pdf, f"{case_id}-r{revision}-request.pdf", "attachment")


@router.get("/api/cases/{case_id}/revisions/{revision}/sources/{role}", response_class=Response, responses=PDF_RESPONSES)
def case_source(request: Request, case_id: str, revision: int, role: Role):
    pdf, _ = store.source_pdf(request.app.state.dsn, case_id, revision, role)
    return _pdf(pdf, f"{case_id}-r{revision}-{role}.pdf")


class ManualReview(BaseModel):
    actor: str | None = None
    fields: dict = Field(default_factory=dict)
    checks: list[dict] = Field(default_factory=list)


@router.post("/api/cases/{case_id}/evidence", response_model=Case)
def record_evidence(request: Request, case_id: str, review: ManualReview, if_match: Annotated[str | None, Header()] = None):
    from app.intake_documents import manual_evidence
    dsn, base = request.app.state.dsn, _revision(if_match)
    current, originals = store.revision_snapshot(dsn, case_id, base)
    if not current["intake"] or current["status"] == "staff_reviewed":
        raise HTTPException(409, "Manual evidence review is available on an unapproved uploaded case.")
    actor = _actor(request, review.actor)
    transient = {"open_holds", "open_hold_count", "history", "revision", "reviewer", "insurer_status", "events", "workflow_version",
                 "allowed_actions", "latest_event_kind", "admission_check", "deposit_decision", "intake"}
    evidence = {key: value for key, value in current.items() if key not in transient}
    try:
        result = manual_evidence(evidence, originals, review.model_dump(exclude={"actor"}) | {"reviewer": actor})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    result["manual_review"]["actor"] = actor
    result["manual_review"]["username"] = getattr(request.state, "username", None)
    return store.replace_estimate(dsn, case_id, base, result, originals, reviewed=True)


@router.get("/api/cases/{case_id}/clarification", response_class=Response, responses=PDF_RESPONSES)
def clarification(request: Request, case_id: str, revision: Annotated[int, Query(ge=1)]):
    from app.workspace_documents import clarification_bytes
    dsn = request.app.state.dsn
    current, originals = store.revision_snapshot(dsn, case_id, revision)
    if not current.get("clarification_available"):
        raise HTTPException(409, "Review the unresolved source evidence before generating a clarification request.")
    try:
        pdf = clarification_bytes(current, originals)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if store.case_detail(dsn, case_id)["revision"] != revision:
        raise HTTPException(412, "A newer revision is available.")
    return _pdf(pdf, f"{case_id}-r{revision}-clarification.pdf", "attachment")


class EventForm(BaseModel):
    action: Literal["submission", "reply", "supplement", "admission", "deposit", "hold", "resolve_hold"]
    category: str | None = None
    hold_id: int | None = None
    workflow_version: Annotated[int, Query(ge=0)]
    target_revision: Annotated[int | None, Query(ge=1)] = None
    actor: str | None = None
    reference: str | None = None
    channel: str | None = None
    outcome: str | None = None
    terms: str | None = None
    notes: str | None = None
    amount: str | None = None
    currency: str | None = None
    actual_procedure: str | None = None
    actual_admission_date: str | None = None
    actual_member: str | None = None
    actual_amount: str | None = None
    actual_facility: str | None = None
    covered_procedure: str | None = None
    covered_member: str | None = None
    facility: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    patient_share: str | None = None
    letter_confirmed: bool = False
    confirmed: bool = False
    file: UploadFile | None = None


@router.post("/api/cases/{case_id}/workflow", response_model=Case)
def record_workflow(request: Request, case_id: str,
                    form: Annotated[EventForm, Form(media_type="multipart/form-data")],
                    if_match: Annotated[str | None, Header()] = None):
    revision = _revision(if_match)
    actor = _actor(request, form.actor)
    raw = filename = None
    if form.file is not None:
        raw, filename = _read_upload(form.file), form.file.filename
        try:
            validate_attachment(raw, filename)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return store.record_event(request.app.state.dsn, case_id, revision, form.workflow_version, form.action, actor,
                              getattr(request.state, "username", None),
                              form.model_dump(exclude={"file"}), raw, filename)


@router.get("/api/cases/{case_id}/revisions/{revision}/events/{event_id}/source",
         response_class=Response, responses=PDF_RESPONSES)
def event_source(request: Request, case_id: str, revision: int, event_id: int):
    raw = store.event_source(request.app.state.dsn, case_id, revision, event_id)
    return _pdf(raw, f"{case_id}-r{revision}-event-{event_id}.pdf")

def create_workspace(hospital=None):
    workspace = FastAPI(title="ZeroUpfront coordinator API", version="1.1", lifespan=lifespan,
                        docs_url=None, redoc_url=None)
    workspace.state.hospital = hospital
    workspace.add_exception_handler(store.WorkspaceError, workspace_error)
    workspace.add_middleware(MultipartBodyLimit)
    install_access(workspace)
    if hospital:
        workspace.add_middleware(HospitalContext, hospital=hospital)
    workspace.include_router(preclaims.router)
    workspace.include_router(discharge_router)
    workspace.include_router(router)
    return workspace


app = build_platform(create_workspace)
