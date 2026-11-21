# Coordinator API performance

On 21 November 2026, the API took **14.63 ms at p95** to accept the itemized digital Z002 estimate and return a verified revision. The two-page reviewed request and gap report with three embedded original PDFs took **17.08 ms at p95** to generate and download. These measurements cover the synthetic workflow on one machine with one coordinator making sequential requests.

| HTTP operation | Observations | p50 | p95 |
| --- | ---: | ---: | ---: |
| List three cases | 50 | 3.32 ms | 3.93 ms |
| Open Z002 and its revision history | 50 | 3.55 ms | 4.12 ms |
| Upload revised PDF, verify evidence and commit revision | 50 | 12.83 ms | 14.63 ms |
| Download the exact revised source PDF | 50 | 3.02 ms | 3.83 ms |
| Approve the current revision | 50 | 4.26 ms | 5.18 ms |
| Generate and download the reviewed request PDF with its originals | 50 | 15.77 ms | 17.08 ms |

**One separate live scan took 6.317 seconds.** The same API accepted the image-only Z002 estimate and used `gpt-6.2-astra` to read its single page. The estimate cited page 1 as OCR evidence and kept the case open for itemization under AT-2. The verified total was THB 82,000 with zero priced service rows. This records one observed cloud round trip. Repeated trials and a wider scan corpus are needed to estimate OCR latency percentiles or accuracy.

## Method

The benchmark launches a Uvicorn process on a private IPv4 loopback port and initializes a disposable PostgreSQL cluster. One persistent HTTP client sends multipart uploads and buffers the entire response before stopping each timer. Request validation, fixture parsing and evidence checks, database connections and transactions, and response serialization all occur inside the measured HTTP operations.

One unmeasured digital cycle warms the service. Each of 50 measured cycles starts with the original Z002 estimate, uploads the revised PDF, checks the two service prices against THB 82,000, approves the current revision and downloads the packet. The driver reads both exported pages and checks the downloaded estimate plus all three embedded PDFs against their exact source bytes. Restoring the original estimate after each cycle grows the case history from revision 1 to 103 including warm-up. Response assertions, PDF inspection and fixture reset occur outside the latency samples. The median uses the two middle observations and p95 uses nearest rank.

The host was an Apple M4 Max running macOS 27.2.1, Python 3.12.9, Uvicorn 0.54.0 and PostgreSQL 18.6 with default durability. The digital timings exclude cloud inference, browser rendering, internet transport and human review. A production sizing estimate still needs multi-user load, representative document sizes, a managed database and actual deployment-region network timings. Separate integration tests exercise concurrent replacements, approval replays and stale export rejection. [HTTP benchmark](../bench/workspace_http.py) · [Concurrency tests](../tests/test_workspace_api.py)

For the separate discharge workflow, a 10,000-encounter benchmark covers PostgreSQL restore, paginated queues, member search, original PDF retrieval and correction under concurrent load. [Discharge benchmark](discharge-scale-benchmark.md)

## Startup and persistence

In a separate clean install, locked Python dependencies and a Node 24.22.3 frontend build started with an empty PostgreSQL directory and three cases. After approving Z002 revision 2, a Ctrl-C shutdown and restart preserved the reviewer, revision 1 source and revision 2 approval. Export reproduced the same complete PDF byte for byte. Two subsequent SIGTERM shutdowns each stopped the private PostgreSQL server and removed its PID file. A separate test altered a single stored source in an isolated database and verified that the API blocked export when the bytes differed from the approved digest. [Local launcher](../app/run_workspace.py) · [Export checks](../tests/test_workspace_api.py)

## Reproduce

With `initdb` and `pg_ctl` on PATH, run as a regular user. The driver creates and removes its own database, even if the environment already points to another one.

```sh
uv run --locked python bench/workspace_http.py --repetitions 50
```

To include the single approved synthetic scan, configure a server-side OpenAI API key in `.env` and enable the live trial for this disposable server.

```sh
uv run --locked --env-file .env python bench/workspace_http.py --repetitions 50 --live-scan
```
