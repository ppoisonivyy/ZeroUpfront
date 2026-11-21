"""Serve the built coordinator client and its API on the same origin."""
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .workspace_api import app

DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


@app.get("/", include_in_schema=False)
@app.get("/cases/{case_id}", include_in_schema=False)
def workspace():
    return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="web-assets")
app.mount("/pdfjs", StaticFiles(directory=DIST / "pdfjs"), name="pdf-viewer-resources")
