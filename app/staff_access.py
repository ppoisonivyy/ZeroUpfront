"""Staff accounts for a single hospital's dedicated workspace database."""
import argparse
from getpass import getpass
from hashlib import sha256
import os
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import psycopg
from starlette.concurrency import run_in_threadpool


HASHER = PasswordHasher()
COOKIE = "zu_staff_session"
SESSION_SECONDS = 8 * 60 * 60
PUBLIC_ROUTES = {"/api/access/session", "/api/access/login"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

DDL = """
CREATE SCHEMA IF NOT EXISTS zeroupfront_demo;
CREATE TABLE IF NOT EXISTS zeroupfront_demo.staff_accounts (
    username text PRIMARY KEY, display_name text NOT NULL, password_hash text NOT NULL,
    active boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS zeroupfront_demo.staff_sessions (
    token_hash bytea PRIMARY KEY, username text NOT NULL REFERENCES zeroupfront_demo.staff_accounts,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS staff_session_expiry ON zeroupfront_demo.staff_sessions (expires_at);
CREATE TABLE IF NOT EXISTS zeroupfront_demo.login_attempts (
    bucket bytea PRIMARY KEY, attempts integer NOT NULL, starts timestamptz NOT NULL
);
"""


def mode():
    chosen = os.environ.get("WORKSPACE_AUTH_MODE", "staff")
    if chosen not in {"local", "staff"}:
        raise RuntimeError("WORKSPACE_AUTH_MODE must be staff or local.")
    return chosen


def initialize_access(dsn):
    mode()
    with psycopg.connect(dsn) as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtext('zeroupfront_demo.staff'))")
        db.execute(DDL)


def _username(raw):
    value = raw.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._@+-]{0,127}", value):
        raise ValueError("Enter a username with 1–128 letters, digits or email characters.")
    return value


def provision(dsn, username, display_name, password, *, reset=False):
    username = _username(username)
    display_name = display_name.strip()
    if not (1 <= len(display_name) <= 100 and display_name.isprintable()):
        raise ValueError("Enter a printable staff name of up to 100 characters.")
    if not 14 <= len(password) <= 256:
        raise ValueError("Use a passphrase between 14 and 256 characters.")
    encoded = HASHER.hash(password)
    with psycopg.connect(dsn) as db:
        if reset:
            result = db.execute("""
                UPDATE zeroupfront_demo.staff_accounts SET display_name=%s, password_hash=%s, active=true
                WHERE username=%s
            """, (display_name, encoded, username))
            if not result.rowcount:
                raise ValueError("This staff account does not exist.")
            db.execute("DELETE FROM zeroupfront_demo.staff_sessions WHERE username=%s", (username,))
        else:
            result = db.execute("""
                INSERT INTO zeroupfront_demo.staff_accounts VALUES (%s,%s,%s,true)
                ON CONFLICT DO NOTHING
            """, (username, display_name, encoded))
            if not result.rowcount:
                raise ValueError("This username already exists. Use reset to rotate its passphrase.")


def disable(dsn, username):
    username = _username(username)
    with psycopg.connect(dsn) as db:
        result = db.execute("UPDATE zeroupfront_demo.staff_accounts SET active=false WHERE username=%s", (username,))
        if not result.rowcount:
            raise ValueError("This staff account does not exist.")
        db.execute("DELETE FROM zeroupfront_demo.staff_sessions WHERE username=%s", (username,))


def _digest(value):
    return sha256(value.encode()).digest()


def _staff(dsn, token):
    if not token or len(token) > 128:
        return None
    with psycopg.connect(dsn) as db:
        return db.execute("""
            SELECT a.username, a.display_name FROM zeroupfront_demo.staff_sessions s
            JOIN zeroupfront_demo.staff_accounts a USING (username)
            WHERE s.token_hash=%s AND s.expires_at>now() AND a.active
        """, (_digest(token),)).fetchone()


def _local_request(request):
    host = request.url.hostname
    peer = request.client.host if request.client else None
    return (host in LOCAL_HOSTS and peer in LOCAL_HOSTS) or (host == "testserver" and peer == "testclient")


def _allowed_attempt(dsn, username, peer):
    # Commit both counters even on rejection. Bound each window across worker processes.
    with psycopg.connect(dsn) as db:
        db.execute("DELETE FROM zeroupfront_demo.login_attempts WHERE starts < now()-interval '20 minutes'")
        for kind, value, limit in (("peer", peer, 60), ("account", username, 12)):
            count, = db.execute("""
                INSERT INTO zeroupfront_demo.login_attempts AS t VALUES (%s,1,now())
                ON CONFLICT (bucket) DO UPDATE SET
                attempts=CASE WHEN t.starts<now()-interval '10 minutes' THEN 1 ELSE t.attempts+1 END,
                starts=CASE WHEN t.starts<now()-interval '10 minutes' THEN now() ELSE t.starts END
                RETURNING attempts
            """, (_digest(kind + "/" + value),)).fetchone()
            if count > limit:
                return False
    return True


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


def install_access(app):
    @app.middleware("http")
    async def require_access(request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        local = mode() == "local"
        if local and not _local_request(request):
            return JSONResponse({"detail": "Local rehearsal is available only on this computer."}, 403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site" or (
                origin and origin != str(request.base_url).rstrip("/")
            ):
                return JSONResponse({"detail": "Open the workspace to perform this action."}, 403)
        account = None
        if not local:
            account = await run_in_threadpool(_staff, request.app.state.dsn, request.cookies.get(COOKIE))
            if request.url.path not in PUBLIC_ROUTES and not account:
                return JSONResponse({"detail": "Sign in to this hospital workspace."}, 401,
                                    headers={"Cache-Control": "no-store"})
        request.state.actor = account[1] if account else None
        request.state.username = account[0] if account else None
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/access/session")
    def session(request: Request):
        return {"mode": mode(), "actor": request.state.actor, "username": request.state.username}

    @app.post("/api/access/login")
    def login(request: Request, credentials: Login, response: Response):
        if mode() != "staff":
            raise HTTPException(409, "This workspace is in local rehearsal mode.")
        if request.url.scheme != "https" and not _local_request(request):
            raise HTTPException(403, "Open this staff workspace over HTTPS.")
        username = credentials.username.strip().lower()
        dsn = request.app.state.dsn
        if not _allowed_attempt(dsn, username, request.client.host if request.client else "unknown"):
            raise HTTPException(429, "Too many sign-in attempts. Try again in ten minutes.", headers={"Retry-After":"600"})
        with psycopg.connect(dsn) as db:
            record = db.execute("""
                SELECT password_hash, display_name FROM zeroupfront_demo.staff_accounts
                WHERE username=%s AND active FOR SHARE
            """, (username,)).fetchone()
            try:
                HASHER.verify(record[0] if record else DUMMY_HASH, credentials.password)
            except VerificationError:
                raise HTTPException(401, "The username or passphrase is incorrect.") from None
            if not record:
                raise HTTPException(401, "The username or passphrase is incorrect.")
            token = secrets.token_urlsafe(32)
            db.execute("DELETE FROM zeroupfront_demo.staff_sessions WHERE expires_at<=now() OR token_hash=%s",
                       (_digest(request.cookies.get(COOKIE, "")),))
            db.execute("""
                INSERT INTO zeroupfront_demo.staff_sessions VALUES (%s,%s,now()+%s*interval '1 second')
            """, (_digest(token), username, SESSION_SECONDS))
            db.execute("DELETE FROM zeroupfront_demo.login_attempts WHERE bucket=%s", (_digest("account/"+username),))
        response.set_cookie(COOKIE, token, httponly=True, secure=request.url.scheme == "https",
                            samesite="strict", max_age=SESSION_SECONDS, path="/api")
        return {"mode": "staff", "actor": record[1], "username": username}

    @app.post("/api/access/logout")
    def logout(request: Request, response: Response):
        with psycopg.connect(request.app.state.dsn) as db:
            db.execute("DELETE FROM zeroupfront_demo.staff_sessions WHERE token_hash=%s",
                       (_digest(request.cookies.get(COOKIE, "")),))
        response.delete_cookie(COOKIE, path="/api", httponly=True, samesite="strict")
        return {"mode": mode(), "actor": None, "username": None}


# A missing account follows the same password verification path.
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))


def main():
    parser = argparse.ArgumentParser(description="Manage staff in this hospital's dedicated workspace database.")
    parser.add_argument("action", choices=("add", "reset", "disable"))
    parser.add_argument("username")
    parser.add_argument("--name", help="Name recorded on staff reviews")
    args = parser.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        parser.exit(1, "Set DATABASE_URL to the hospital workspace database.\n")
    initialize_access(dsn)
    try:
        if args.action == "disable":
            disable(dsn, args.username)
        else:
            if not args.name:
                parser.error("--name is required to add or reset staff.")
            first = getpass("Staff passphrase: ")
            if first != getpass("Confirm passphrase: "):
                parser.exit(1, "The passphrases do not match.\n")
            provision(dsn, args.username, args.name, first, reset=args.action == "reset")
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    print("Staff account updated.")


if __name__ == "__main__":
    main()
