"""Start the release with temporary synthetic hospital databases for one recording."""

import os
import signal
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from app import hospital_demo, staff_access
from app.hospital_platform import configured_hospitals
from app.run_workspace import _terminate, workspace_database


def main():
    signal.signal(signal.SIGTERM, _terminate)
    for key in ("DATABASE_URL", "WORKSPACE_HOSPITALS", "OPENAI_API_KEY"):
        os.environ.pop(key, None)
    os.environ.update(
        WORKSPACE_AUTH_MODE="staff",
        WORKSPACE_SEED_DEMO="0",
        WORKSPACE_ENABLE_OCR="0",
        WORKSPACE_ENABLE_AI_REVIEW="0",
    )
    with (
        TemporaryDirectory(prefix="zu-record-") as temp,
        workspace_database(Path(temp) / "postgres"),
    ):
        hospital_demo.prepare(os.environ["DATABASE_URL"])
        hospital = next(h for h in configured_hospitals() if h.slug == "canal-bridge")
        staff_access.provision(
            hospital.dsn,
            "film-hospital",
            "Hospital coordinator",
            os.environ["DEMO_PASSWORD"],
        )
        staff_access.provision(
            hospital.dsn,
            "film-insurer",
            "Meridian Assist reviewer",
            os.environ["DEMO_INSURER_PASSWORD"],
            insurer="Meridian Assist",
        )
        uvicorn.run(
            "app.workspace_server:app",
            host="127.0.0.1",
            port=int(os.environ["DEMO_PORT"]),
            access_log=False,
        )


if __name__ == "__main__":
    main()
