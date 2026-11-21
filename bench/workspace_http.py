"""Time verified synthetic workspace requests over loopback HTTP on a disposable PostgreSQL cluster."""
import argparse
from collections import defaultdict
from contextlib import contextmanager
from io import BytesIO
from math import ceil
import os
from pathlib import Path
import socket
from statistics import median
import subprocess
import sys
from time import monotonic, perf_counter, sleep

import httpx
from pypdf import PdfReader

from case_revision import temporary_database


ROOT = Path(__file__).resolve().parents[1]
CASE = "/api/cases/Z002"
EXHIBITS = ROOT / "fixtures/cases/Z002"


@contextmanager
def server(dsn, enable_ocr, *, auth_mode="local"):
    # Hand the already-bound loopback socket to Uvicorn so no other program can claim the ephemeral port.
    with socket.socket() as bound:
        bound.bind(("127.0.0.1", 0))
        port = bound.getsockname()[1]
        args = [sys.executable, "-m", "uvicorn", "app.workspace_api:app", "--fd", str(bound.fileno()),
                "--log-level", "error", "--no-access-log"]
        env = dict(os.environ, DATABASE_URL=dsn, WORKSPACE_AUTH_MODE=auth_mode, WORKSPACE_ENABLE_OCR="1" if enable_ocr else "0")
        ready = "/api/cases" if auth_mode == "local" else "/api/access/session"
        with subprocess.Popen(args, cwd=ROOT, env=env, pass_fds=(bound.fileno(),)) as process:
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=210, trust_env=False) as client:
                    deadline = monotonic() + 30
                    while monotonic() < deadline:
                        if process.poll() is not None:
                            raise RuntimeError("Uvicorn exited before startup.")
                        try:
                            if client.get(ready, timeout=1).is_success:
                                break
                        except httpx.TransportError:
                            pass
                        sleep(0.05)
                    else:
                        raise RuntimeError("Timed out waiting for the workspace API.")
                    yield client
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()


def timed(samples, label, fn, *args, **kwargs):
    started = perf_counter()
    response = fn(*args, **kwargs)
    elapsed = (perf_counter() - started) * 1000
    if not response.is_success:
        raise RuntimeError(f"{label}: HTTP {response.status_code}, {response.text[:400]}")
    samples[label].append(elapsed)
    return response


def upload(client, revision, filename, data, *, ocr=False):
    return client.post(CASE + "/estimate", headers={"If-Match": f'"{revision}"'},
                       files={"file": (filename, data, "application/pdf")}, data={"confirmed": "true", "ocr": str(ocr).lower()})


def cycle(client, samples, revision, revised, original):
    queue = timed(samples, "Queue", client.get, "/api/cases").json()
    detail = timed(samples, "Case detail", client.get, CASE).json()
    assert len(queue) == 3 and detail["revision"] == revision and detail["status"] == "needs_itemization"
    result = timed(samples, "Revised estimate", upload, client, revision, "revised-estimate.pdf", revised).json()
    revision += 1
    assert (result["status"], result["revision"], result["total"]) == ("ready_for_review", revision, 82000)
    assert [line["amount"] for line in result["lines"]] == [52000, 30000]
    source_url = next(source["url"] for source in result["sources"] if source["role"] == "estimate")
    assert timed(samples, "Original source PDF", client.get, source_url).content == revised
    approved = timed(samples, "Staff approval", client.post, CASE + "/approve",
                     headers={"If-Match": f'"{revision}"'}, json={"reviewer": "Demo coordinator"}).json()
    assert approved["status"] == "staff_reviewed" and approved["reviewer"] == "Demo coordinator"
    packet = timed(samples, "Reviewed request PDF", client.get, CASE + "/export", params={"revision": revision})
    reader = PdfReader(BytesIO(packet.content))
    pages = reader.pages
    assert len(pages) == 2 and "THB 82,000" in pages[0].extract_text() and "Gap report" in pages[1].extract_text()
    expected = {"alder.pdf": (ROOT / "fixtures/policies/alder.pdf").read_bytes(),
                "plan.pdf": (EXHIBITS / "plan.pdf").read_bytes(), "revised-estimate.pdf": revised}
    assert dict(reader.attachments) == {label: [pdf] for label, pdf in expected.items()}
    reset = upload(client, revision, "original.pdf", original)
    reset.raise_for_status()
    assert reset.json()["revision"] == revision + 1 and reset.json()["status"] == "needs_itemization"
    return revision + 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=50)
    parser.add_argument("--live-scan", action="store_true", help="Also send the one bundled Z002 scan through OpenAI OCR.")
    args = parser.parse_args()
    if args.repetitions <= 0:
        parser.error("--repetitions must be positive")
    if args.live_scan and not os.getenv("OPENAI_API_KEY"):
        parser.error("--live-scan requires OPENAI_API_KEY")
    revised, original = [(EXHIBITS / name).read_bytes() for name in ("revised-estimate.pdf", "estimate.pdf")]
    samples = defaultdict(list)
    with temporary_database() as dsn, server(dsn, args.live_scan) as client:
        revision = cycle(client, defaultdict(list), 1, revised, original)  # unmeasured warm-up
        for _ in range(args.repetitions):
            revision = cycle(client, samples, revision, revised, original)
        for label, values in samples.items():
            p95 = sorted(values)[ceil(0.95 * len(values)) - 1]
            print(f"{label}: n={len(values)} p50={median(values):.2f}ms p95={p95:.2f}ms", flush=True)
        if args.live_scan:
            scan_timings = defaultdict(list)
            result = timed(scan_timings, "Cloud OCR", upload, client, revision, "scanned-estimate.pdf",
                           (EXHIBITS / "scanned-estimate.pdf").read_bytes(), ocr=True).json()
            source = next(source for source in result["sources"] if source["role"] == "estimate")
            assert (result["status"], result["clause"], result["total"], result["lines"]) == (
                "needs_itemization", "AT-2", 82000, [])
            assert source["method"] == "ocr" and source["page"] == 1 and result["revision"] == revision + 1
            print(f"Cloud OCR: n=1 elapsed={scan_timings['Cloud OCR'][0] / 1000:.3f}s, "
                  f"{result['status']}, {result['clause']}, THB {result['total']}, "
                  f"source page {source['page']}, method {source['method']}")


if __name__ == "__main__":
    main()
