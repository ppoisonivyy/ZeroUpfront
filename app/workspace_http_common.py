"""Shared HTTP guards for admission and discharge workspaces."""
import re
from tempfile import TemporaryFile

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette._utils import get_route_path
from starlette.datastructures import Headers
from starlette.datastructures import UploadFile as MultipartFile
from openai import APIConnectionError, APITimeoutError, AuthenticationError, PermissionDeniedError, RateLimitError

INTAKE_BYTES = 24 * 1024 * 1024
# Four discharge PDFs, plus form fields, filenames and multipart framing.
MAX_MULTIPART_BYTES = 4 * INTAKE_BYTES + 1024 * 1024


class MultipartBodyLimit:
    """Verify the whole upload before Starlette opens any multipart files."""

    def __init__(self, app, maximum=MAX_MULTIPART_BYTES):
        self.app = app
        self.maximum = maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        media_type = headers.get("content-type", "").partition(";")[0].strip().lower()
        if media_type != "multipart/form-data":
            return await self.app(scope, receive, send)

        # Only the hospital's protected case workflows accept uploaded files.
        path = get_route_path(scope)
        workflow = path.split("/")[:3]
        report_upload = re.fullmatch(r"/api/preclaims/[^/]+/reports", path)
        if scope["method"] != "POST" or (not report_upload and workflow not in (["", "api", "cases"], ["", "api", "discharge"])):
            return await JSONResponse({"detail": "This route does not accept multipart uploads."},
                                      status_code=415)(scope, receive, send)

        maximum = self.maximum
        if report_upload:
            from app.preclaim_report_evidence import MAX_BYTES as report_limit
            maximum = min(maximum, report_limit + 1024 * 1024)
        too_large = JSONResponse(
            {"detail": f"All files and form data together must fit within {maximum / (1024 * 1024):g} MiB."},
            status_code=413,
        )
        length = headers.get("content-length")
        if length is not None:
            try:
                declared = int(length)
                if declared < 0:
                    raise ValueError
            except ValueError:
                return await JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)(scope, receive, send)
            if declared > maximum:
                return await too_large(scope, receive, send)

        # A private temporary file keeps the raw body off the Python heap. The
        # context also closes it on disconnect, parser errors and cancellation.
        with await run_in_threadpool(TemporaryFile) as spool:
            total = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return await Response(status_code=400)(scope, receive, send)
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > maximum:
                    return await too_large(scope, receive, send)
                if chunk:
                    await run_in_threadpool(spool.write, chunk)
                if not message.get("more_body", False):
                    break
            del message, chunk
            await run_in_threadpool(spool.seek, 0)
            remaining = total

            async def replay():
                nonlocal remaining
                if spool.closed:
                    return await receive()
                block = await run_in_threadpool(spool.read, min(remaining, 64 * 1024))
                remaining -= len(block)
                if remaining == 0:
                    await run_in_threadpool(spool.close)
                return {"type": "http.request", "body": block, "more_body": remaining > 0}

            return await self.app(scope, replay, send)


def ocr_service_error(exc):
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return HTTPException(503, "Cloud OCR could not authenticate the configured project or access the configured model.")
    if isinstance(exc, RateLimitError):
        if getattr(exc, "code", None) == "insufficient_quota":
            return HTTPException(503, "The cloud OCR project has insufficient API quota. Check the project billing configuration.")
        return HTTPException(429, "Cloud OCR is rate limited. Retry after the provider limit clears.")
    if isinstance(exc, (APIConnectionError, APITimeoutError)) or (getattr(exc, "status_code", None) or 0) >= 500:
        return HTTPException(503, "The cloud OCR provider timed out or is temporarily unavailable. Retry later.")
    return HTTPException(502, "The cloud OCR provider rejected this request. Check the model and document settings.")


def accept_files(*allowed: str):
    """Check the original multipart list before FastAPI selects one value per named role."""
    async def validate(request: Request):
        form = await request.form()
        seen = set()
        for field, value in form.multi_items():
            if isinstance(value, MultipartFile) and field not in allowed:
                raise HTTPException(422, f"Unsupported attachment field '{field}'. Accepted file fields: {', '.join(allowed)}.")
            if field not in allowed:
                continue
            if field in seen:
                raise HTTPException(422, f"More than one value was supplied for '{field}'. Send one PDF per role.")
            seen.add(field)

    return validate


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


def _read_upload(file, maximum=INTAKE_BYTES):
    raw = file.file.read(maximum + 1)
    if len(raw) > maximum:
        raise HTTPException(413, f"Choose a file of at most {maximum // (1024 * 1024)} MiB.")
    return raw


def _actor(request, fallback):
    actor = getattr(request.state, "actor", None) or fallback
    if not isinstance(actor, str) or not actor.strip() or len(actor.strip()) > 100 or not actor.strip().isprintable():
        raise HTTPException(422, "Enter the name of the staff member recording this action.")
    return actor.strip()
