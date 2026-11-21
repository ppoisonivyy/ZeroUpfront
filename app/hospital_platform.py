"""Deployment-owned hospital directory and request context for dedicated databases."""
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import os
import re

from fastapi import FastAPI
import psycopg
from psycopg.conninfo import conninfo_to_dict


@dataclass(frozen=True)
class Hospital:
    slug: str
    name: str
    dsn: str = field(repr=False)

    @property
    def prefix(self):
        return "/h/" + self.slug


current_hospital = ContextVar("current_hospital", default=None)


def hospital_path(path):
    hospital = current_hospital.get()
    return hospital.prefix + path if hospital else path


class HospitalContext:
    def __init__(self, app, hospital):
        self.app = app
        self.hospital = hospital

    async def __call__(self, scope, receive, send):
        token = current_hospital.set(self.hospital)
        try:
            return await self.app(scope, receive, send)
        finally:
            current_hospital.reset(token)


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("The hospital directory contains a duplicate field or slug.")
        result[key] = value
    return result


def configured_hospitals():
    raw = os.environ.get("WORKSPACE_HOSPITALS")
    if raw is None:
        return []
    try:
        registry = json.loads(raw, object_pairs_hook=_unique_fields)
    except ValueError:
        raise ValueError("WORKSPACE_HOSPITALS must be a JSON object with unique fields and slugs.") from None
    if not isinstance(registry, dict) or not registry:
        raise ValueError("Configure at least one hospital or unset WORKSPACE_HOSPITALS for a single workspace.")
    hospitals = []
    targets = set()
    for slug, config in registry.items():
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or len(slug) > 63:
            raise ValueError("Use a lowercase hospital slug of up to 63 letters, digits and single hyphens.")
        if not isinstance(config, dict) or set(config) != {"hospital_name", "database_url_env"}:
            raise ValueError(f"Hospital {slug} requires hospital_name and database_url_env.")
        name, env_name = config["hospital_name"], config["database_url_env"]
        if not isinstance(name, str) or not name.strip() or len(name) > 120 or not name.isprintable():
            raise ValueError(f"Hospital {slug} requires a printable display name of up to 120 characters.")
        if not isinstance(env_name, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", env_name):
            raise ValueError(f"Hospital {slug} requires a database environment variable name.")
        dsn = os.environ.get(env_name)
        if not dsn or not dsn.strip():
            raise ValueError(f"Hospital {slug} requires its database environment variable to be set.")
        try:
            params = conninfo_to_dict(dsn)
        except psycopg.ProgrammingError:
            raise ValueError(f"Hospital {slug} has an invalid PostgreSQL connection setting.") from None
        # Transport or credential differences do not make two URLs for the same database independent.
        target = (params.get("service"), params.get("host"), params.get("hostaddr"), params.get("port", "5432"),
                  params.get("dbname") or params.get("user"))
        if target in targets:
            raise ValueError("Each hospital requires a separate PostgreSQL database.")
        targets.add(target)
        hospitals.append(Hospital(slug, name.strip(), dsn))
    return hospitals


def bind_database(hospital):
    # A persistent identity also catches two aliases for the same database or a swapped deployment secret.
    with psycopg.connect(hospital.dsn, connect_timeout=5) as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtext('zeroupfront_demo.schema'))")
        db.execute("CREATE SCHEMA IF NOT EXISTS zeroupfront_demo")
        db.execute("""CREATE TABLE IF NOT EXISTS zeroupfront_demo.hospital_binding (
                      singleton boolean PRIMARY KEY CHECK (singleton), slug text NOT NULL)""")
        db.execute("""INSERT INTO zeroupfront_demo.hospital_binding VALUES (true,%s)
                      ON CONFLICT DO NOTHING""", (hospital.slug,))
        assigned, = db.execute("SELECT slug FROM zeroupfront_demo.hospital_binding WHERE singleton").fetchone()
        if assigned != hospital.slug:
            raise ValueError(f"The database for hospital {hospital.slug} is already bound to a different hospital.")


def build_platform(create_workspace):
    hospitals = configured_hospitals()
    workspaces = {h.slug: create_workspace(h) for h in hospitals}
    if hospitals:
        @asynccontextmanager
        async def lifespan(_app):
            async with AsyncExitStack() as stack:
                for hospital in hospitals:
                    workspace = workspaces[hospital.slug]
                    await stack.enter_async_context(workspace.router.lifespan_context(workspace))
                yield

        platform = FastAPI(title="ZeroUpfront hospitals", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
        for hospital in hospitals:
            platform.mount(hospital.prefix, workspaces[hospital.slug])
    else:
        platform = create_workspace()
    platform.state.hospital_apps = workspaces

    @platform.get("/api/hospitals")
    def directory():
        return {"mode": "multi" if hospitals else "single",
                "hospitals": [{"slug": h.slug, "name": h.name} for h in hospitals]}
    return platform
