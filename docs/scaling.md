# Scaling the hospital workspace

One hospital has one PostgreSQL database. API processes serving that hospital connect to the same primary. PostgreSQL stores case heads, revisions, original PDFs, staff sessions and payer correspondence. A load balancer can route successive requests to different healthy API processes. The release exposes `/healthz` for process liveness and `/readyz` for its database check. [Release architecture and setup](deployment.md)

## One, two and four API processes

Across **3,456 verified authenticated requests**, four active processes increased reviewed PDF export throughput from **73 to 230 requests/s** (3.14×) and reduced its p95 from **129 to 43 ms**. Two processes captured most of the case-detail improvement. Worklist and member search throughput barely changed. Both operations compute exact global queue counts in PostgreSQL for each request, making the database query a better target for the next experiment. These measurements used process replicas on one Apple M4 Max host with 128 GiB RAM, a shared PostgreSQL primary and direct loopback HTTP with a genuine staff session. The API connected to PostgreSQL through a private Unix socket. Physical instance resizing, multiple hosts, network load balancing, failover, OCR and population-level production capacity remain unmeasured.

| Authenticated operation | 1 process, p50 / p95 ms · req/s | 2 processes, p50 / p95 ms · req/s | 4 processes, p50 / p95 ms · req/s |
| --- | ---: | ---: | ---: |
| First 25 discharge cases | 105.12 / 109.99 · 75.70 | 105.60 / 109.50 · 75.56 | 105.20 / 109.31 · 75.65 |
| Exact member search using POST | 108.08 / 112.25 · 73.54 | 107.65 / 110.42 · 74.30 | 108.40 / 111.10 · 73.68 |
| Case detail and revision history | 12.99 / 17.38 · 587.58 | 9.94 / 12.03 · 771.24 | 10.07 / 11.82 · 766.83 |
| Generate reviewed PDF with original exhibits | 108.81 / 129.26 · 73.12 | 55.69 / 66.32 · 142.15 | 33.42 / 43.39 · 229.64 |

The harness restored the same 10,000-claim synthetic dump into a private PostgreSQL 18.6 instance. Staff authentication was enabled for all timed requests. Eight concurrent clients issued 96 requests per workload per round, using the same case selections for each replica count. Requests were routed round-robin to the active subset of four separately started Uvicorn processes. Across three rounds each configuration occupied each run position once. Workloads ran separately. Latencies include HTTP, data transfer and response checks. Pooled throughput is completions divided by the sum of elapsed batch times. Before timing, each process also generated a reviewed export whose embedded bill matched the original SHA-256. [Benchmark](../bench/replica_scale.py) · [Per-round measurements](../bench/results/replica-scale.json)

After the timed reads, two processes concurrently submitted the same reviewed revision and workflow version. One request succeeded, the other returned HTTP 409, and all four processes read exactly one submission and the same original bill. A staff session created on the first process worked on every process. Logout through the fourth invalidated that session on all four. These checks use independent server processes sharing one database and one synthetic staff identity.

Run the following with uv and the PostgreSQL 18 command-line tools. The first command can be skipped if the generated dump already exists. Each command starts a fresh private database. The second discards all writes made by the concurrency exercise when it exits.

```sh
uv run --locked python bench/discharge_scale.py
uv run --locked python bench/replica_scale.py
```

## Raising the API container’s CPU limit

With four Uvicorn workers throughout, raising the API CPU quota from one to four increased throughput from **37.72 to 147.29 reviewed exports/s** (3.90×). The p95 fell from **308.66 to 81.16 ms**. All 864 timed exports returned PDF documents. A representative export from each batch contained an embedded bill with the expected SHA-256. Anonymous and logged-out export requests returned HTTP 401. [Runnable CPU benchmark](../bench/cpu_quota.py) · [Per-round timings and image identifiers](../bench/results/cpu-quota.json)

| API CPU quota | Requests | p50, ms | p95, ms | Exports/s |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 288 | 200.26 | 308.66 | 37.72 |
| 2 | 288 | 91.28 | 142.99 | 87.45 |
| 4 | 288 | 48.52 | 81.16 | 147.29 |

Docker Desktop’s 8-CPU Linux VM hosted two disposable containers. The PostgreSQL container held the same 10,000 claims and kept a two-CPU quota. Each container had a fixed 1 GiB memory limit. Eight client threads made certificate-verified HTTPS requests with the same staff session. Each request opened a fresh TLS connection. The API used a private Docker bridge with explicitly disabled database TLS for this synthetic CPU test. The release smoke test exercises certificate verification on the database connection separately. Each condition received the same 96 selected exports per round; three rounds rotated the quota order. The harness read the enforced cgroup limit after each change. These quotas constrain CPU time on the same host. Cloud instance sizing, physical core isolation and added database capacity require separate tests. [Docker CPU limits](https://docs.docker.com/engine/containers/resource_constraints/#configure-the-default-cfs-scheduler) · [Release verification](deployment.md)

To repeat with the previously generated dump, start Docker Desktop with at least four available CPUs, install OpenSSL, then run these commands. The harness removes its private network and both containers after verification.

```sh
docker build -t zeroupfront:quota-audit .
uv run --locked python bench/cpu_quota.py
```

## Apply either change to the same release

**Vertical.** Change the CPU and RAM of one running service or replace it on a larger VM. In a Docker deployment, `--cpus=4 --memory=2g -e WEB_CONCURRENCY=4` is an example starting configuration, subject to actual upload memory and database headroom. Uvicorn reads the worker count from the environment. A single process may leave extra cores unused for Python PDF generation. Database CPU, RAM and storage I/O can be resized separately.

**Horizontal.** Increase the replica count of the same release in the hospital’s approved region. Give each replica the same hospital-specific database, CA trust, access mode and approved AI settings. Send only ready replicas traffic behind one TLS origin. No sticky sessions are needed for case access. For one worker per container, use `WEB_CONCURRENCY=1` and add containers. Keep the database primary authoritative for review, submission, payment and immediate read-after-write. A read-only standby would need explicit query routing and a replica-lag policy before serving staff reads. Database failover and cross-region replication require separate setup and testing.

## Where to add capacity

| Observable condition | Change to test | Verification |
| --- | --- | --- |
| API CPU is saturated or requests wait for an API worker during PDF exports; database and connection budget have headroom | Add one API replica behind the load balancer. Keep work for one hospital on its configured database. Route around a replica before stopping it. | Repeat the same workload with a fixed offered load. Compare export throughput, interactive p95 and failures while a replica is drained. |
| Worklist and search latencies rise with case count while API replicas add little throughput | Inspect the worklist query on production-shaped data. Its exact queue counts currently aggregate current cases for every search. Test indexed current-case summaries and transactionally maintained counts before introducing stale reads. | Capture a representative query plan and timings, including case corrections, approvals and payer replies. Every count and row must agree with the underlying revision. |
| Database CPU, memory pressure or storage latency dominates after query tuning | Increase database vCPU, RAM or provisioned I/O according to the observed constraint. For CPU-bound API tasks, compare a larger machine or additional processes on the existing machine. | Restore the same dataset on both instance sizes, hold requests, storage and settings constant as appropriate, and repeat the test. Physical vertical hardware scaling remains unmeasured. |
| Uploads and model-assisted checks delay interactive work | Bound concurrent expensive requests per hospital and per operation at the gateway. As volume warrants, move long-running extraction into a durable worker queue with per-hospital quotas, backpressure, bounded retries and idempotent revision writes. | Load a second synthetic hospital's worker traffic while the first uses search, writes and export. Record queue age, completion time, errors, and whether interactive requests still meet the agreed target. |

Run separate budgets for interactive work, exports and optional AI preprocessing. A future queue should key work by hospital, case, revision and source digest and check the revision before publishing. This protects current findings when a revised estimate arrives during extraction. Use explicit admission limits and a bounded queue so one large upload batch cannot exhaust the whole worker fleet. The present benchmark sent short, digital English PDFs without external model calls. [AWS Builders’ Library on load shedding](https://aws.amazon.com/builders-library/using-load-shedding-to-avoid-overload/) · [PostgreSQL monitoring statistics](https://www.postgresql.org/docs/18/monitoring-stats.html)

## Database connections and scaling triggers

The current API opens short-lived psycopg connections in the staff and case stores. A protected case request ordinarily authenticates in one connection before opening another for case work. Four idle replicas do not reserve four pools. Concurrent requests, health probes, administration and ingestion can still overlap. Each active keyed cloud OCR intake holds one database connection through evaluation and save. Bound these admissions separately from fast reads, and configure compatible transaction timeouts. Measure connection counts, wait events, database CPU, disk latency, API CPU, queueing, route-specific p95 and error rates at peak. Instrument by route template and workload; omit patient identifiers and search terms. [Staff access implementation](../app/staff_access.py) · [PostgreSQL activity monitoring](https://www.postgresql.org/docs/18/monitoring-stats.html#MONITORING-PG-STAT-ACTIVITY-VIEW)

For a bounded production deployment, reserve provider and emergency slots first, subtract the peak allowance for migrations, probes and background workers, then divide the remaining server connection budget across the **maximum simultaneous API processes including rolling-deployment overlap**. For example, a server limit of 100, 20 slots retained for other uses and eight active or starting API processes leaves at most ten server slots per API process. This is a planning example. Enforce the budget with explicit concurrency limits or bounded pools and a bounded acquisition timeout before using an autoscaler. If using PgBouncer, verify the chosen pooling mode against transaction and session behavior as well as the release smoke tests. [PostgreSQL connection settings](https://www.postgresql.org/docs/18/runtime-config-connection.html) · [PgBouncer pooling modes](https://www.pgbouncer.org/features.html)

Set the hospital's agreed peak traffic and latency target first. As an initial pilot trigger, investigate when interactive p95 breaches the target for five minutes. Add API replicas only when API utilization or queueing corroborates the breach and the database retains headroom. Cap the autoscaler using the connection budget; scale down after a longer quiet period to avoid flapping. Investigate lock waits, storage or query plans first when the database saturates. A load generator with a fixed arrival rate and a multi-hour soak on the intended hosting tier should set the actual production ceiling. [Horizontal autoscaling metrics and stabilization](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/)

## Capacity and recovery

The source dataset contains 10,000 cases, 11,040 revisions and 47,048 stored PDFs. Actual multi-page scans, revised bills and retained exports can be much larger. Model retained storage using measured bytes per original and revision, expected intake and retention, then include indexes, growth headroom, backups and WAL. Monitor those separately and alert on failed backups and shrinking free space. Dedicated hospital databases provide separate case stores; several databases sharing one host still compete for CPU, RAM, storage and connections. For hospitals with sustained competing loads, test separate resource limits or dedicated database instances. [Database benchmark and corpus composition](discharge-scale-benchmark.md)

For a hospital pilot, agree on the maximum tolerable data loss (RPO) and outage (RTO). Enable encrypted database backups and continuous WAL archiving or a managed point-in-time recovery equivalent. If availability requirements justify it, place a standby in another failure zone and rehearse failover as well as restore. Recover into an isolated database; reconcile latest revisions, payment references, staff access and representative original PDF hashes before redirecting traffic. Measure elapsed recovery and the latest recoverable transaction against the agreed objectives. A local logical dump and restore were exercised here. Cross-zone failover, point-in-time recovery and production recovery times still need a hosted drill. [PostgreSQL backup and point-in-time recovery](https://www.postgresql.org/docs/18/continuous-archiving.html)
