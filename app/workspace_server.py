"""Serve the shared client and each configured hospital's API on the same origin."""
from pathlib import Path

import psycopg
from fastapi import Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .workspace_api import app

DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


def health():
    return Response(status_code=204)


def readiness(request: Request):
    hospitals = request.app.state.hospital_apps
    try:
        for workspace in hospitals.values() if hospitals else (request.app,):
            with psycopg.connect(workspace.state.dsn, connect_timeout=3) as db:
                db.execute("SELECT 1 FROM zeroupfront_demo.cases LIMIT 0")
    except psycopg.Error:
        return Response(status_code=503)
    return Response(status_code=204)


def workspace():
    return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})


def serve_web(platform):
    platform.add_api_route("/healthz", health, include_in_schema=False)
    platform.add_api_route("/readyz", readiness, include_in_schema=False)
    platform.add_api_route("/", workspace, include_in_schema=False)
    hospitals = platform.state.hospital_apps
    for clinic in hospitals.values() if hospitals else (platform,):
        if hospitals:
            clinic.add_api_route("/", workspace, include_in_schema=False)
        clinic.add_api_route("/cases/{case_id}", workspace, include_in_schema=False)
    platform.mount("/assets", StaticFiles(directory=DIST / "assets"), name="web-assets")
    platform.mount("/pdfjs", StaticFiles(directory=DIST / "pdfjs"), name="pdf-viewer-resources")


serve_web(app)
