"""Serve the built coordinator client and its API on the same origin."""
from pathlib import Path

import psycopg
from fastapi import Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .workspace_api import app

DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


@app.get("/healthz", include_in_schema=False)
def health():
    return Response(status_code=204)


@app.get("/readyz", include_in_schema=False)
def readiness(request: Request):
    try:
        with psycopg.connect(request.app.state.dsn, connect_timeout=3) as db:
            db.execute("SELECT 1 FROM zeroupfront_demo.cases LIMIT 0")
    except psycopg.Error:
        return Response(status_code=503)
    return Response(status_code=204)


@app.get("/", include_in_schema=False)
@app.get("/cases/{case_id}", include_in_schema=False)
def workspace():
    return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="web-assets")
app.mount("/pdfjs", StaticFiles(directory=DIST / "pdfjs"), name="pdf-viewer-resources")
