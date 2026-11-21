"""Time staff-authenticated reviewed PDF exports under three API CPU quotas in local Docker."""

import json
import os
import random
import secrets
import ssl
import subprocess
from argparse import ArgumentParser
from contextlib import ExitStack
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from uuid import uuid4

import httpx
from pypdf import PdfReader
from replica_scale import ROOT, batch, ok, request, stats


def docker(*args, **kwargs):
    return subprocess.check_output(["docker", *args], **kwargs).decode().strip()


def service_name(stack, name, *options, env=None):
    docker("run", "-d", "--name", name, *options, env=env)
    stack.callback(docker, "rm", "-fv", name)
    return name


def wait_for(check):
    deadline = monotonic() + 60
    while monotonic() < deadline:
        try:
            if check():
                return
        except (httpx.TransportError, subprocess.CalledProcessError):
            pass
        sleep(0.15)
    raise TimeoutError("Timed out waiting for the benchmark container")


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="zeroupfront:quota-audit")
    parser.add_argument("--postgres", default="postgres:18")
    parser.add_argument(
        "--dump",
        type=Path,
        default=ROOT / ".local/testing-audit/db-scale/synthetic-discharge.dump",
    )
    parser.add_argument("--requests", type=int, default=96)
    parser.add_argument(
        "--out", type=Path, default=ROOT / ".local/testing-audit/cpu-quota.json"
    )
    args = parser.parse_args()
    if args.requests < 8 or not args.dump.is_file():
        parser.error(
            "Provide the 10,000-claim dump and at least eight requests per round."
        )
    report = {
        "workload": "authenticated reviewed PDF export",
        "clients": 8,
        "workers": 4,
        "postgres_cpu_quota": 2,
        "container_memory_mib_each": 1024,
        "requests_per_round": args.requests,
        "docker_engine": docker("version", "--format", "{{.Server.Version}}"),
        "docker_vm_cpus": int(docker("info", "--format", "{{.NCPU}}")),
        "api_image_id": docker("image", "inspect", "--format", "{{.Id}}", args.image),
        "postgres_image_id": docker(
            "image", "inspect", "--format", "{{.Id}}", args.postgres
        ),
        "rounds": [],
    }
    key = "zu-quota-" + uuid4().hex[:12]
    secret = secrets.token_hex(20)
    dbname = key + "-db"
    env = dict(
        os.environ,
        POSTGRES_PASSWORD=secret,
        DATABASE_URL=f"postgresql://postgres:{secret}@{dbname}:5432/postgres?sslmode=disable",
        WORKSPACE_AUTH_MODE="staff",
        WORKSPACE_SEED_DEMO="0",
    )
    with ExitStack() as stack:
        tls_dir = Path(stack.enter_context(TemporaryDirectory(prefix="zu-quota-cert-")))
        cert, private_key = tls_dir / "cert.pem", tls_dir / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=127.0.0.1",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
                "-keyout",
                str(private_key),
                "-out",
                str(cert),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        private_key.chmod(
            0o444
        )  # The private host directory contains the key until this run ends.
        docker("network", "create", key)
        stack.callback(docker, "network", "rm", key)
        db = service_name(
            stack,
            dbname,
            "--network",
            key,
            "--cpus",
            "2",
            "--memory",
            "1g",
            "-e",
            "POSTGRES_PASSWORD",
            args.postgres,
            env=env,
        )
        wait_for(
            lambda: docker(
                "exec",
                db,
                "pg_isready",
                "-h",
                "127.0.0.1",
                "-U",
                "postgres",
                stderr=subprocess.DEVNULL,
            )
        )
        with args.dump.open("rb") as stream:
            docker(
                "exec",
                "-i",
                db,
                "pg_restore",
                "--no-acl",
                "--no-owner",
                "--exit-on-error",
                "-U",
                "postgres",
                "-d",
                "postgres",
                stdin=stream,
            )

        def sql(statement):
            return docker("exec", db, "psql", "-U", "postgres", "-At", "-c", statement)

        assert sql("SELECT count(*) FROM zeroupfront_demo.discharge_cases") == "10000"
        report["postgres_version"] = sql("SHOW server_version")
        sql("ANALYZE")
        records = sql("""
            SELECT c.id, c.head, r.evidence->>'member', s.digest
            FROM zeroupfront_demo.discharge_cases c
            JOIN zeroupfront_demo.discharge_revisions r ON r.case_id=c.id AND r.revision=c.head
            JOIN zeroupfront_demo.discharge_approvals a ON a.case_id=c.id AND a.revision=c.head
            JOIN zeroupfront_demo.discharge_sources s ON s.case_id=c.id AND s.revision=c.head AND s.role='bill'
            ORDER BY r.evidence->>'member'
        """)
        cases = [
            (ident, int(revision), member, digest, True)
            for ident, revision, member, digest in (
                line.split("|") for line in records.splitlines()
            )
        ]
        assert len(cases) == 5000
        api = service_name(
            stack,
            key + "-api",
            "--network",
            key,
            "--cpus",
            "4",
            "--memory",
            "1g",
            "-p",
            "127.0.0.1::8080",
            "-v",
            f"{cert}:/tls-cert.pem:ro",
            "-v",
            f"{private_key}:/tls-key.pem:ro",
            "-e",
            "DATABASE_URL",
            "-e",
            "WORKSPACE_AUTH_MODE",
            "-e",
            "WORKSPACE_SEED_DEMO",
            args.image,
            "uvicorn",
            "app.workspace_server:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8080",
            "--workers",
            "4",
            "--ssl-keyfile",
            "/tls-key.pem",
            "--ssl-certfile",
            "/tls-cert.pem",
            "--no-access-log",
            env=env,
        )
        url = "https://" + docker("port", api, "8080/tcp")
        client = stack.enter_context(
            httpx.Client(
                base_url=url,
                verify=ssl.create_default_context(cafile=cert),
                trust_env=False,
                timeout=30,
                headers={"Connection": "close"},
            )
        )
        wait_for(lambda: client.get("/readyz").status_code == 204)
        provision = (
            "import sys,os; from app.staff_access import provision; "
            "provision(os.environ['DATABASE_URL'],'cpu-audit','Synthetic staff',sys.stdin.read())"
        )
        password = secrets.token_urlsafe(32)
        docker("exec", "-i", api, "python", "-c", provision, input=password.encode())
        protected = f"/api/discharge/{cases[0][0]}/export?revision={cases[0][1]}"
        assert client.get(protected).status_code == 401
        login = ok(
            client.post(
                "/api/access/login",
                json={"username": "cpu-audit", "password": password},
            )
        )
        assert login["mode"] == "staff" and login["username"] == "cpu-audit"
        all_times = {n: ([], []) for n in (1, 2, 4)}
        for idx, order in enumerate(((1, 2, 4), (2, 4, 1), (4, 1, 2))):
            inputs = random.Random(20261121 + idx).choices(cases, k=args.requests)
            for quota in order:
                docker("update", "--cpus", str(quota), api)
                budget, period = map(
                    int, docker("exec", api, "cat", "/sys/fs/cgroup/cpu.max").split()
                )
                assert budget == period * quota
                blob = request(client, "export", inputs[0], [])
                assert any(
                    sha256(pdf).hexdigest() == inputs[0][3]
                    for group in PdfReader(BytesIO(blob)).attachments.values()
                    for pdf in group
                )
                times, elapsed = batch([client], "export", inputs, [], 8)
                report["rounds"].append(
                    dict(round=idx + 1, api_cpu_quota=quota, **stats(times, elapsed))
                )
                all_times[quota][0].extend(times)
                all_times[quota][1].append(elapsed)
                print(
                    f"Round {idx + 1}, verified {len(times)} exports at {quota} CPU(s).",
                    flush=True,
                )
        report["cells"] = [
            dict(api_cpu_quota=q, **stats(times, sum(seconds)))
            for q, (times, seconds) in all_times.items()
        ]
        ok(client.post("/api/access/logout"))
        assert client.get(protected).status_code == 401
        report["auth_checks"] = {
            "anonymous_export": 401,
            "logged_in_mode": login["mode"],
            "logged_out_export": 401,
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["cells"]), flush=True)


if __name__ == "__main__":
    main()
