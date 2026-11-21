"""Launch the local synthetic coordinator workspace with persistent PostgreSQL."""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory

from psycopg.conninfo import make_conninfo
import uvicorn


ROOT = Path(__file__).resolve().parents[1]


def _terminate(_signum, _frame):
    # Uvicorn restores and re-raises a termination signal after graceful shutdown.
    # Unwind Python contexts so the private database also shuts down.
    raise SystemExit(0)


@contextmanager
def workspace_database(data_dir):
    if os.environ.get("DATABASE_URL"):
        yield
        return

    if not all(shutil.which(name) for name in ("initdb", "pg_ctl")):
        raise SystemExit("Install PostgreSQL with initdb and pg_ctl on PATH, or set DATABASE_URL to a dedicated demo database.")
    data_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not (data_dir / "PG_VERSION").exists():
        subprocess.run(["initdb", "-D", str(data_dir), "-U", "coordinator", "-A", "trust",
                        "--no-locale", "--encoding=UTF8"], check=True, stdout=subprocess.DEVNULL)

    # A private Unix socket keeps the demo cluster separate from any local service.
    with TemporaryDirectory(prefix="zu-db-", dir="/tmp") as socket_dir:
        subprocess.run(["pg_ctl", "-D", str(data_dir), "-l", str(data_dir / "server.log"),
                        "-o", f"-k {socket_dir} -c listen_addresses=''", "-w", "start"], check=True)
        try:
            os.environ["DATABASE_URL"] = make_conninfo(host=socket_dir, user="coordinator", dbname="postgres")
            yield
        finally:
            os.environ.pop("DATABASE_URL", None)
            subprocess.run(["pg_ctl", "-D", str(data_dir), "-m", "fast", "-w", "stop"], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8038)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".local" / "workspace" / "postgres",
                        help="Persistent data directory used when DATABASE_URL is unset")
    args = parser.parse_args()
    if not (ROOT / "web" / "dist" / "index.html").is_file():
        parser.exit(1, "Build the client first with npm --prefix web ci and npm --prefix web run build.\n")
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("WORKSPACE_AUTH_MODE", "local" if not os.getenv("DATABASE_URL") else "staff")
    previous = signal.signal(signal.SIGTERM, _terminate)
    try:
        with workspace_database(args.data_dir.resolve()):
            uvicorn.run("app.workspace_server:app", host="127.0.0.1", port=args.port)
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    main()
