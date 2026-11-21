"""Shared HTTP guards for admission and discharge workspaces."""
import re

from fastapi import HTTPException, Response

INTAKE_BYTES = 24 * 1024 * 1024


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
