"""Run isolated, password-protected hospital workspaces with fictional patient records."""
import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import secrets
import signal
import sys

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import uvicorn

from app import preclaims, discharge_store, pattaya_case, pattaya_workflow, staff_access, workspace_store
from app.discharge_claim import evaluate_discharge, load_discharge_fixture
from app.hospital_platform import OPENAI_USES, Hospital, bind_database, configured_hospitals
from app.intake_documents import evaluate_intake
from app.journey_examples import NAMES, exhibits
from app.run_workspace import ROOT, _terminate, workspace_database
from fixtures.discharge.build import EXHIBITS, VARIANTS, render


HOSPITALS = {
    "canal-bridge": ("Canal Bridge Demo Hospital", "CB"),
    "lakeside": ("Lakeside Demo Hospital", "LS"),
}
DEFAULT_STATE = ROOT / ".local" / "hospital-demo"


def database_name(slug):
    return "zu_demo_" + slug.replace("-", "_")


def seed(hospital):
    name, code = HOSPITALS[hospital.slug]
    if hospital.name != name:
        raise ValueError("Seeding is restricted to the named fictional demo hospitals.")
    bind_database(hospital)
    intake, documents = exhibits("clean" if code == "CB" else "possible-exclusion")
    intake["id"] = "C-" + code + "-PLAN"
    workspace_store.initialize(hospital.dsn, [(evaluate_intake(intake, documents, NAMES), documents)])
    preclaims.seed(hospital.dsn, name)
    discharge_store.initialize(hospital.dsn)
    staff_access.initialize_access(hospital.dsn)
    with psycopg.connect(hospital.dsn) as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtext('zeroupfront_demo.seed_hospital_examples'))")
        for number, scenario in enumerate(("duplicate_line", "aligned", "over_cap"), 1):
            ident = f"D-{code}-{number:03d}"
            if db.execute("SELECT 1 FROM zeroupfront_demo.discharge_cases WHERE id=%s", (ident,)).fetchone():
                continue
            meta, _, names = load_discharge_fixture(scenario)
            substitutions = (
                ("EXAMPLE-2402", f"DEMO-{code}-{number:03d}"),
                ("EXAMPLE-VISIT-42", f"VISIT-{code}-{number:03d}"),
                ("Canal Bridge Demo Hospital", name),
                ("2026-12-", "2025-12-"),
            )
            for key, value in meta.items():
                for old, new in substitutions:
                    value = value.replace(old, new)
                meta[key] = value
            meta["id"] = ident
            variant_role = VARIANTS.get(scenario, (None, []))[0]
            raw = {role: render(role, scenario if role == variant_role else "aligned", substitutions=substitutions)
                   for role in EXHIBITS}
            evidence = evaluate_discharge(meta, raw, names)
            if scenario == "duplicate_line":
                corrected = render("bill", substitutions=substitutions)
                evidence["sample_bill_digest"] = workspace_store._save_document(db, corrected)
                evidence["sample_bill_available"] = True
            discharge_store.create(db, ident, evidence, raw, names)

        ident = f"D-{code}-PATTAYA"
        if not db.execute("SELECT 1 FROM zeroupfront_demo.discharge_cases WHERE id=%s", (ident,)).fetchone():
            meta, raw, names = pattaya_case.exhibits(facility=name, member=f"DEMO-{code}-239", encounter=f"VISIT-{code}-FX")
            evidence = evaluate_discharge(dict(meta, id=ident), raw, names, _pattaya_fixture=True)
            evidence["staff_practice_hospital"] = hospital.slug
            pattaya_workflow.seed(db, ident, evidence, raw, names)


def set_demo_password(dsn, name, username, *, reset=False):
    if sys.stdin.isatty():
        first = getpass(f"Choose a {username} password for {name} (14–256 characters): ")
        if first != getpass("Confirm password: "):
            raise ValueError("The entries differ.")
    elif reset:
        raise ValueError("Set the password from an interactive terminal.")
    else:
        # An unattended launch leaves the account inaccessible until the operator sets a password.
        first = secrets.token_urlsafe(32)
    reviewer = username == "reviewer"
    staff_access.provision(dsn, username, "Meridian Assist reviewer" if reviewer else "Demo coordinator",
                           first, reset=reset, insurer="Meridian Assist" if reviewer and not reset else None)


def prepare(admin_dsn, approved_uses=()):
    directory = {}
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        for slug, (name, _) in HOSPITALS.items():
            database = database_name(slug)
            if not admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone():
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            dsn = make_conninfo(admin_dsn, dbname=database)
            seed(Hospital(slug, name, dsn))
            with psycopg.connect(dsn) as db:
                existing = {row[0] for row in db.execute("SELECT username FROM zeroupfront_demo.staff_accounts")}
            for username in ("judge", "reviewer"):
                if username not in existing:
                    set_demo_password(dsn, name, username)
            variable = "ZU_DEMO_" + slug.upper().replace("-", "_") + "_DSN"
            os.environ[variable] = dsn
            directory[slug] = {
                "hospital_name": name, "database_url_env": variable,
                "approved_openai_uses": [use for use in OPENAI_USES if f"{slug}/{use}" in approved_uses],
            }
    os.environ["WORKSPACE_HOSPITALS"] = json.dumps(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("serve", "password", "seed-configured"), default="serve")
    parser.add_argument("hospital", nargs="?", choices=tuple(HOSPITALS))
    parser.add_argument("--account", choices=("judge", "reviewer"), default="judge",
                        help="Account to update with the password action")
    parser.add_argument("--port", type=int, default=8040)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--approve-openai-use", action="append", default=[], metavar="HOSPITAL/USE",
                        choices=[f"{slug}/{use}" for slug in HOSPITALS for use in OPENAI_USES],
                        help="Approve one external document-processing use for a fictional hospital on this launch.")
    args = parser.parse_args()
    if args.approve_openai_use and args.action != "serve":
        parser.error("--approve-openai-use applies to the local serve command.")
    folder = args.data_dir.resolve() / "postgres"
    try:
        if args.action == "seed-configured":
            hospitals = configured_hospitals()
            if not hospitals or any(h.slug not in HOSPITALS or h.name != HOSPITALS[h.slug][0] for h in hospitals):
                parser.error("Configure only the named fictional hospital databases before seeding.")
            for hospital in hospitals:
                seed(hospital)
            return
        if args.action == "password":
            if not args.hospital or not (folder / "postmaster.pid").exists():
                parser.error("Start the private hospital demo, then select a hospital slug.")
            pid, data_dir, _, port, socket, *_ = (folder / "postmaster.pid").read_text().splitlines()
            if Path(data_dir).resolve() != folder or not socket.startswith("/"):
                parser.error("The demo cluster does not match this directory.")
            os.kill(int(pid), 0)
            dsn = make_conninfo(host=socket, port=port, user="coordinator", dbname=database_name(args.hospital))
            set_demo_password(dsn, HOSPITALS[args.hospital][0], args.account, reset=True)
            print(f"{args.account.title()} password updated. Sign in with username {args.account}.")
            return
        if os.getenv("DATABASE_URL") or os.getenv("WORKSPACE_HOSPITALS"):
            parser.error("The loopback demo requires its own private databases. Unset DATABASE_URL and WORKSPACE_HOSPITALS.")
        if not (ROOT / "web/dist/index.html").exists():
            parser.error("Build the client with npm --prefix web ci and npm --prefix web run build.")
        signal.signal(signal.SIGTERM, _terminate)
        with workspace_database(folder):
            prepare(os.environ["DATABASE_URL"], args.approve_openai_use)
            os.environ.update(WORKSPACE_AUTH_MODE="staff", WORKSPACE_SEED_DEMO="0")
            print(f"Hospital directory: http://127.0.0.1:{args.port}/", flush=True)
            uvicorn.run("app.workspace_server:app", host="127.0.0.1", port=args.port, access_log=False)
    except ValueError as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
