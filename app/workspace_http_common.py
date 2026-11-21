"""Shared HTTP guards for admission and discharge workspaces."""
import re

from fastapi import HTTPException, Request, Response
from starlette.datastructures import UploadFile as MultipartFile
from openai import APIConnectionError, APITimeoutError, AuthenticationError, PermissionDeniedError, RateLimitError

INTAKE_BYTES = 24 * 1024 * 1024


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
        raise HTTPException(413, f"Choose a PDF of at most {maximum // (1024 * 1024)} MiB.")
    return raw


def _actor(request, fallback):
    actor = getattr(request.state, "actor", None) or fallback
    if not isinstance(actor, str) or not actor.strip() or len(actor.strip()) > 100 or not actor.strip().isprintable():
        raise HTTPException(422, "Enter the name of the staff member recording this action.")
    return actor.strip()
