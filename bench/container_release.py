"""Start a built release and disposable PostgreSQL on Docker and exercise staff access."""
import argparse
import os
import secrets
import ssl
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import time
from uuid import uuid4

import httpx


def check(cmd, *, env=None, stdin=None):
    return subprocess.run(cmd, env=env, input=stdin, text=True, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def smoke(image, postgres, cert_dir):
    suffix = uuid4().hex[:12]
    network, db, web = (f"zu-{role}-{suffix}" for role in ("net", "db", "web"))
    secret = secrets.token_hex(24)
    env = os.environ | {"POSTGRES_PASSWORD": secret,
                        "DATABASE_URL": f"postgresql://postgres:{secret}@{db}/postgres"}
    cert, key = cert_dir / "cert.pem", cert_dir / "key.pem"
    check(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
           "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
           "-out", str(cert), "-keyout", str(key)])
    # Docker binds individual files from this private temporary directory into the non-root container.
    key.chmod(0o444)
    check(["docker", "network", "create", network])
    containers = []
    try:
        check(["docker", "run", "-d", "--name", db, "--network", network,
               "-e", "POSTGRES_PASSWORD", postgres], env=env)
        containers.append(db)
        for _ in range(60):
            ready = subprocess.run(["docker", "exec", db, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"],
                                   capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Disposable PostgreSQL did not start")
        check(["docker", "run", "-d", "--name", web, "--network", network, "--read-only",
               "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m", "-e", "DATABASE_URL",
               "-v", f"{cert}:/tls-cert.pem:ro", "-v", f"{key}:/tls-key.pem:ro",
               "-p", "127.0.0.1::8080", image, "uvicorn", "app.workspace_server:app",
               "--host", "0.0.0.0", "--port", "8080", "--ssl-keyfile", "/tls-key.pem",
               "--ssl-certfile", "/tls-cert.pem"], env=env)
        containers.append(web)
        address = check(["docker", "port", web, "8080/tcp"])
        with httpx.Client(base_url="https://" + address, verify=ssl.create_default_context(cafile=cert), timeout=10) as client:
            for _ in range(60):
                try:
                    if client.get("/readyz").status_code == 204:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("The application did not become ready")
            assert client.get("/healthz").status_code == 204
            assert 'id="root"' in client.get("/").text
            assert client.get("/api/access/session").json()["mode"] == "staff"
            assert client.get("/api/cases").status_code == 401
            password = secrets.token_urlsafe(26)
            provision = ("import os,sys; from app.staff_access import provision; "
                         "provision(os.environ['DATABASE_URL'],'smoke','Release reviewer',sys.stdin.read())")
            check(["docker", "exec", "-i", web, "python", "-c", provision], stdin=password)
            login = client.post("/api/access/login", json={"username": "smoke", "password": password})
            assert login.status_code == 200, login.text
            assert client.get("/api/cases").json() == []
            assert client.post("/api/examples/missing-estimate").status_code == 404
            assert client.get("/api/discharge").json() == []
            assert client.post("/api/access/logout").status_code == 200
            assert client.get("/api/discharge").status_code == 401
            print("Passed release checks for assets, readiness, staff login, empty worklists and logout.")
    finally:
        for container in reversed(containers):
            subprocess.run(["docker", "rm", "-fv", container], stdout=subprocess.DEVNULL, check=False)
        subprocess.run(["docker", "network", "rm", network], stdout=subprocess.DEVNULL, check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="zeroupfront:release")
    parser.add_argument("--postgres", default="postgres:18")
    args = parser.parse_args()
    with TemporaryDirectory() as tmp:
        smoke(args.image, args.postgres, Path(tmp))
