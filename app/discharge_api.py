"""Independent discharge intake and manual settlement records for one hospital."""

from datetime import date
import json
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from openai import APIError, OpenAI
from pydantic import BaseModel, ConfigDict, Field

from app import discharge_store as store
from app import payer_ai_reader as ai_reader
from app.workspace_store import coordinate_ocr
from app.hospital_platform import disclosure_client, hospital_allows, require_disclosure, require_hosted_ocr
from app.staff_access import mode
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


class PattayaSettlementBalance(BaseModel):
    status: Literal["unpaid", "partially_paid", "paid", "reconciliation_required"]
    outstanding_minor: int | None
    next_action: Literal["book", "record_short", "top_up", "confirm_topup", "complete", "review"]


class WorklistItem(Summary):
    pattaya_settlement: PattayaSettlementBalance | None = None


class WorklistPage(BaseModel):
    items: list[WorklistItem]
    counts: WorklistCounts
    total: int
    page: int
    page_size: int


class Detail(Summary):
    ai_review_enabled: bool = Field(default_factory=lambda: hospital_allows("payer_second_read") and ai_reader.enabled())
    guarantee_fee_read_enabled: bool = Field(default_factory=lambda: hospital_allows("guarantee_fees") and ai_reader.enabled())
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
    follow_up: dict | None = None
    settlement_status: str
    paid_by_currency: dict[str, int]
    case_paid_by_currency: dict[str, int]
    patient_statement_facts: dict | None = None
    reviewed_patient_statement: dict | None = None
    sample_bill_available: bool = False
    example_scenario: Literal["pattaya_fx"] | None = None
    staff_practice_hospital: str | None = None
    letter_kind: str | None = None
    ocr_review_available: bool = False
    ocr_page_count: int = 0
    ocr_attestation: AttestationSummary | None = None


def _evaluate(meta, raw, names, ocr, saved_ocr=None, *, pattaya_fixture=False):
    from app.discharge_claim import evaluate_discharge

    options = {"_saved_ocr": saved_ocr} if saved_ocr else {}
    if pattaya_fixture:
        options["_pattaya_fixture"] = True
    if mode() != "local" and meta.get("as_of", "") > date.today().isoformat():
        raise HTTPException(422, "The review date cannot be in the future.")

    try:
        if ocr:
            require_hosted_ocr()
            with disclosure_client(OpenAI, "hosted_ocr", timeout=90, max_retries=1) as client:
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


@router.get("", response_model=list[WorklistItem], response_model_exclude_unset=True)
def queue(request: Request):
    return store.summaries(request.app.state.dsn)


class WorklistFilters(BaseModel):
    page: int = Field(default=1, ge=1, le=2_147_483_647)
    page_size: int = Field(default=25, ge=1, le=100)
    queue: Literal["all", "needs", "ready", "payer"] = "all"


class WorklistSearch(WorklistFilters):
    search: str = Field(max_length=250)


@router.get("/worklist", response_model=WorklistPage, response_model_exclude_unset=True)
def worklist(request: Request, filters: Annotated[WorklistFilters, Query()]):
    if request.query_params.get("search"):
        raise HTTPException(422, "Send claim search text in the body of POST /api/discharge/worklist/search.")
    return store.worklist(request.app.state.dsn, filters.queue, "", filters.page, filters.page_size)


@router.post("/worklist/search", response_model=WorklistPage, response_model_exclude_unset=True)
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


def _require_practice_mode():
    if mode() != "local":
        raise HTTPException(404, "Local discharge example not found.")


@router.post("/examples/{scenario}", response_model=Detail, status_code=201)
def example(request: Request, scenario: str):
    from app.discharge_claim import load_discharge_fixture

    _require_practice_mode()
    if scenario == "pattaya_fx":
        from app import pattaya_case, pattaya_workflow

        ident = "D" + uuid4().hex
        meta, raw, names = pattaya_case.exhibits()
        evaluated = _evaluate(dict(meta, id=ident), raw, names, False, pattaya_fixture=True)
        return pattaya_workflow.seed(request.app.state.dsn, ident, evaluated, raw, names)
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


class PracticeConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]


class PracticeAction(PracticeConfirmation):
    action: Literal["book_spot", "book_forward", "record_short_credit", "record_remittance", "record_topup"]
    workflow_version: int = Field(strict=True, ge=0)
    quote_id: str | None = Field(default=None, max_length=80)
    insurer_reference: str | None = Field(default=None, min_length=1, max_length=100)
    bank_document: Literal["instruction", "initial_credit", "topup_instruction", "topup_credit"] | None = None


def _pattaya_case(dsn, ident, revision):
    from app import pattaya_workflow

    case = store.detail(dsn, ident)
    pattaya_workflow.require_case(case)
    if case["revision"] != revision:
        raise HTTPException(412, "Open the current Pattaya practice revision.")
    return case


@router.get("/{ident}/pattaya")
def pattaya_review(request: Request, response: Response, ident: str, revision: Annotated[int, Query(ge=1)]):
    from app import pattaya_agents

    case = _pattaya_case(request.app.state.dsn, ident, revision)
    response.headers["Cache-Control"] = "private, no-store"
    return pattaya_agents.review(case)


@router.get("/{ident}/pattaya/reference-rate")
def pattaya_reference(request: Request, ident: str, revision: Annotated[int, Query(ge=1)]):
    from app.fx_reference import reference

    _pattaya_case(request.app.state.dsn, ident, revision)
    return reference()


class GuaranteeFeeRequest(PracticeConfirmation):
    event_id: int = Field(gt=0, strict=True)


def _current_guarantee(dsn, ident, revision, event_id):
    case = store.detail(dsn, ident)
    if case["revision"] != revision:
        raise HTTPException(412, "Open the current discharge revision to read its guarantee.")
    reply = next((e for e in reversed(case["events"]) if e["kind"] == "reply"), None)
    if not reply or reply["id"] != event_id or not reply["source_url"] or reply["data"]["outcome"] not in {"confirmed", "partial"}:
        raise HTTPException(409, "Open the latest confirmed or partial payer decision with an original PDF.")
    return reply["source_url"]


@router.post("/{ident}/guarantee-fees")
def guarantee_fees(request: Request, ident: str, options: GuaranteeFeeRequest, if_match: Match = None):
    from app import guarantee_fees as fees

    revision, dsn = _revision(if_match), request.app.state.dsn
    require_disclosure("guarantee_fees")
    source = _current_guarantee(dsn, ident, revision, options.event_id)
    if not ai_reader.enabled():
        raise HTTPException(503, "The OpenAI guarantee reader is unavailable. Review the original payer letter.")
    raw = store.source(dsn, ident, revision, event_id=options.event_id)
    try:
        result = fees.read(raw)
    except APIError as exc:
        raise HTTPException(ocr_service_error(exc).status_code, "The guarantee reader is unavailable. Review the original payer letter.") from exc
    _current_guarantee(dsn, ident, revision, options.event_id)
    return {**result, "source_url": source}


@router.get("/{ident}/pattaya/bank-documents/{kind}", response_class=Response, responses=PDF)
def pattaya_bank_document(request: Request, ident: str, kind: Literal["instruction", "initial_credit", "topup_instruction", "topup_credit"],
                          revision: Annotated[int, Query(ge=1)]):
    from app import pattaya_workflow

    case = _pattaya_case(request.app.state.dsn, ident, revision)
    return _pdf(pattaya_workflow.preview_bank_document(case, kind), f"pattaya-{kind}.pdf")


@router.post("/{ident}/pattaya/agent-review")
def pattaya_model_review(request: Request, response: Response, ident: str, options: PracticeConfirmation, if_match: Match = None):
    from app import pattaya_agents

    _require_practice_mode()
    revision = _revision(if_match)
    case = _pattaya_case(request.app.state.dsn, ident, revision)
    result = pattaya_agents.review(case, use_model=True)
    current = _pattaya_case(request.app.state.dsn, ident, revision)
    if current["workflow_version"] != case["workflow_version"]:
        raise HTTPException(409, "The settlement ledger changed during review. Refresh the case.")
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/{ident}/pattaya/actions", response_model=Detail)
def pattaya_action(request: Request, ident: str, command: PracticeAction, if_match: Match = None):
    from app import pattaya_workflow

    dsn, revision = request.app.state.dsn, _revision(if_match)
    return pattaya_workflow.apply(dsn, ident, revision, command.action, command.workflow_version,
                                 actor=request.state.actor, username=request.state.username,
                                 quote_id=command.quote_id, bank_document=command.bank_document, insurer_reference=command.insurer_reference)


def _sample_bill(dsn, case):
    from app.discharge_claim import load_discharge_fixture

    if case.get("sample_bill_available") and case.get("sample_bill_digest"):
        return store.corrected_example_bill(dsn, case["sample_bill_digest"]), "corrected-bill.pdf"
    if mode() != "local" or not case.get("sample_bill_available"):
        raise HTTPException(404, "No local corrected bill is available for this revision.")
    _, raw, names = load_discharge_fixture("aligned")
    return raw["bill"], names["bill"]


@router.get("/{ident}/sample-bill", response_class=Response, responses=PDF)
def sample_bill(request: Request, ident: str):
    raw, _ = _sample_bill(request.app.state.dsn, store.detail(request.app.state.dsn, ident))
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
    if case.get("example_scenario") == "pattaya_fx":
        raise HTTPException(409, "This settlement rehearsal uses fixed originals. Open a new case for different documents.")
    if sample_bill:
        if any(uploads.values()):
            raise HTTPException(422, "Choose a local corrected bill or upload exhibits.")
        sample, filename = _sample_bill(dsn, case)
        new_raw, new_names = {"bill": sample}, {"bill": filename}
    else:
        new_raw, new_names = _files(uploads)
    raw.update(new_raw)
    names.update(new_names)
    meta = _screen_metadata(case)
    if as_of:
        meta["as_of"] = as_of.isoformat()
    elif mode() != "local":
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
        if case.get("sample_bill_digest"):
            result["sample_bill_digest"] = case["sample_bill_digest"]
    return store.replace(dsn, ident, base, result, raw, names, recheck=True)


@router.post("/{ident}/second-read", response_model=ai_reader.SecondReadResponse)
def second_read(request: Request, response: Response, ident: str, options: ai_reader.SecondReadRequest, if_match: Match = None):
    base = _revision(if_match)
    if not options.confirmed:
        raise HTTPException(422, "Confirm sending this revision’s original PDFs for a provisional AI second read.")
    require_disclosure("payer_second_read")
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


class FollowupDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_version: int = Field(ge=0)
    payer_event_id: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=8000)


@router.post("/{ident}/follow-up-draft", response_class=Response, responses=PDF)
def followup_draft(request: Request, ident: str, draft: FollowupDraft, if_match: Match = None):
    revision = _revision(if_match)
    content = store.followup_pdf(request.app.state.dsn, ident, revision, draft.workflow_version,
                                 draft.payer_event_id, draft.text)
    response = _pdf(content, f"{ident}-r{revision}-reply-{draft.payer_event_id}.pdf", "attachment")
    response.headers["X-Draft-SHA256"] = store.document_digest(content)
    return response


class Workflow(BaseModel):
    file_origin: Literal["workspace", "external"] | None = None
    draft_sha256: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    assign_follow_up: bool = False
    payer_event_id: int | None = Field(default=None, gt=0)
    action: Literal["submission", "reply", "payment", "supplement", "patient_statement"]
    workflow_version: int = Field(ge=0)
    target_revision: int | None = Field(default=None, ge=1)
    owner: str | None = None
    follow_up_date: str | None = None
    contact: str | None = None
    next_update: str | None = None
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
