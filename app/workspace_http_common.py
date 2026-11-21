"""Shared HTTP guards for admission and discharge workspaces."""
import re

from fastapi import HTTPException, Response
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
