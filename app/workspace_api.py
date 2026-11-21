"""HTTP contract for the synthetic coordinator demo. Run app.workspace_server:app for the UI."""
from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from openai import APIError, OpenAI
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from app import workspace_store as store
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


class Case(Summary):
    policy_edition: str
    clause: str | None
    reason: str
    lines: list[Line]
    sources: list[Source]
    history: list[HistoryEntry]
    reviewer: str | None
    insurer_status: Literal["not_sent"]


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


def _assert_case(case_id):
    if case_id not in CASE_INSURERS:
        raise HTTPException(404, "Case not found.")


def _sample(case_id):
    if case_id != "Z002":
        raise HTTPException(404, "The revised demo estimate is available for Z002.")
    return (FIXTURES / "cases" / "Z002" / "revised-estimate.pdf").read_bytes()


def _revision(if_match):
    if if_match is None:
        raise HTTPException(428, "Send the displayed revision in If-Match, for example \"1\".")
    match = re.fullmatch(r'"([1-9][0-9]{0,8})"', if_match)
    if not match:
        raise HTTPException(400, "If-Match must contain one quoted positive revision number.")
    return int(match.group(1))


def _pdf(data, filename, disposition="inline"):
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    })


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
        raise HTTPException(503, "Demo OCR could not finish. Retry with the scan or use a digital demo estimate.") from exc


@asynccontextmanager
async def lifespan(app):
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("Set DATABASE_URL to the PostgreSQL database for the synthetic coordinator workspace.")
    seeds = []
    for case in seed_cases():
        case_id = case["id"]
        estimate = (FIXTURES / "cases" / case_id / "estimate.pdf").read_bytes()
        seeds.append((case, _documents(case_id, estimate)))
    store.initialize(dsn, seeds)
    app.state.dsn = dsn
    yield


app = FastAPI(title="ZeroUpfront synthetic coordinator API", version="1.0", lifespan=lifespan)


@app.exception_handler(store.WorkspaceError)
async def workspace_error(request, exc):
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


@app.get("/api/cases", response_model=list[Summary])
def cases(request: Request):
    return store.list_cases(request.app.state.dsn)


@app.get("/api/cases/{case_id}", response_model=Case)
def case(request: Request, case_id: str, revision: Annotated[int | None, Query(ge=1)] = None):
    return store.case_detail(request.app.state.dsn, case_id, revision)


PDF_RESPONSES = {200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}}


@app.get("/api/cases/{case_id}/sample-estimate", response_class=Response, responses=PDF_RESPONSES)
def sample_estimate(case_id: str):
    return _pdf(_sample(case_id), "Z002-revised-estimate.pdf")


@app.post("/api/cases/{case_id}/estimate", response_model=Case)
def replace_estimate(request: Request, case_id: str, file: Annotated[UploadFile | None, File()] = None,
                     sample: Annotated[bool, Form()] = False, confirmed: Annotated[bool, Form()] = False,
                     if_match: Annotated[str | None, Header()] = None):
    """Confirm that the candidate estimate belongs to this synthetic encounter before replacement."""
    _assert_case(case_id)
    base = _revision(if_match)
    if not confirmed:
        raise HTTPException(422, "Confirm the estimate belongs to this demo encounter.")
    if sample == (file is not None):
        raise HTTPException(422, "Choose exactly one demo PDF or the bundled sample.")
    dsn = request.app.state.dsn
    if store.case_detail(dsn, case_id)["revision"] != base:
        raise HTTPException(412, "The case has a newer revision. Open the current revision before continuing.")
    if sample:
        data, filename = _sample(case_id), "revised-estimate.pdf"
    else:
        data, filename = file.file.read(MAX_UPLOAD_BYTES + 1), file.filename
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Choose a demo estimate under 4 MiB.")
    evidence = _evaluate(case_id, data, filename)
    # Parsing and optional cloud OCR finish before the transaction. Recheck the base under a case lock.
    return store.replace_estimate(dsn, case_id, base, evidence, _documents(case_id, data))


@app.post("/api/cases/{case_id}/approve", response_model=Case)
def approve_case(request: Request, case_id: str, approval: Approval, if_match: Annotated[str | None, Header()] = None):
    return store.approve(request.app.state.dsn, case_id, _revision(if_match), approval.reviewer)


@app.get("/api/cases/{case_id}/export", response_class=Response, responses=PDF_RESPONSES)
def export_case(request: Request, case_id: str, revision: Annotated[int, Query(ge=1)]):
    dsn = request.app.state.dsn
    approved, originals = store.approved_snapshot(dsn, case_id, revision)
    try:
        pdf = packet_bytes(approved, originals)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    # Reject a replacement that committed during rendering, without keeping a database lock during PDF generation.
    store.check_export_current(dsn, case_id, revision)
    return _pdf(pdf, f"{case_id}-r{revision}-request.pdf", "attachment")


@app.get("/api/cases/{case_id}/revisions/{revision}/sources/{role}", response_class=Response, responses=PDF_RESPONSES)
def case_source(request: Request, case_id: str, revision: int, role: Role):
    pdf, _ = store.source_pdf(request.app.state.dsn, case_id, revision, role)
    return _pdf(pdf, f"{case_id}-r{revision}-{role}.pdf")
