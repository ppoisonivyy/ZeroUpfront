# Discharge workspace at 10,000 claims

On 21 November 2026, ZeroUpfront accepted **10,000 distinct synthetic members and encounters** through its normal multipart discharge API. Each submitted PDF contained the matching case identifiers. At the largest checkpoint the database held 11,040 revisions, 43,160 revision-to-exhibit links, 5,000 staff approvals and 10,000 workflow events. PostgreSQL held 47,048 distinct PDF blobs including payer correspondence and the startup fixtures. The database occupied 180.3 MiB. A 29.8 MiB custom-format dump restored all row and unique-identity counts in a fresh database. Requests on three restored cases also reproduced the saved settlement state and all their exhibit hashes. [Runnable benchmark](../bench/discharge_scale.py)

## Measurements

Client timings include loopback HTTP, download, decoding and the correctness assertions for that operation. An Apple M4 Max with 128 GiB RAM, macOS 27.2.1 and PostgreSQL 18.6 ran the database and app. Six local Uvicorn processes populated the database. One Uvicorn process served all timed requests. The harness warmed each read path and ran 30 requests per read cell. The write cells had 10 and 30 distinct held cases at the two sizes. Each rate is completions divided by elapsed batch time. [Machine-readable measurements](../bench/results/discharge-scale.json)

| Operation | Concurrent requests | 100 claims p50 / p95, ms | 10,000 claims p50 / p95, ms | 10,000 claims req/s |
| --- | ---: | ---: | ---: | ---: |
| Open first 25 claims | 1 | 4.38 / 4.85 | 96.84 / 102.95 | 10.25 |
| Open first 25 claims | 4 | 5.08 / 6.70 | 101.83 / 103.80 | 36.90 |
| Open a page of claims needing investigation | 1 | 4.83 / 5.80 | 95.28 / 98.78 | 10.45 |
| Open a page of claims needing investigation | 4 | 4.94 / 6.65 | 100.31 / 102.57 | 37.49 |
| Find an exact member ID | 1 | 5.07 / 5.64 | 96.71 / 100.24 | 10.31 |
| Find an exact member ID | 4 | 4.88 / 6.40 | 104.43 / 108.38 | 35.95 |
| Case detail and history | 1 | 4.11 / 4.66 | 4.36 / 6.21 | 222.32 |
| Case detail and history | 4 | 4.35 / 6.11 | 4.86 / 6.88 | 750.58 |
| Original billed PDF | 1 | 2.64 / 2.79 | 2.63 / 3.28 | 370.21 |
| Original billed PDF | 4 | 3.01 / 4.78 | 3.22 / 4.48 | 1,148.41 |
| Correct a held bill and preserve the earlier revision | 4 | 45.36 / 48.51 | 46.18 / 63.31 | 81.62 |
| Complete collection | 1 | 4.24 / 4.59 | 126.18 / 136.16 | 7.85 |
| Complete collection | 4 | 4.91 / 7.04 | 184.80 / 233.54 | 20.14 |

At 10,000 cases the first page transferred **8,504 bytes**, compared with **3,382,041 bytes** for the complete collection. At four concurrent clients, first-page p95 was 103.80 ms versus 233.54 ms for all claims. Worklist totals, filtering and ordering still depend on the database size. The filtered measurements requested different pages across the needs-investigation queue. Each search looked up one synthetic member chosen by a seeded random generator.

All 760 timed requests passed their correctness checks. The harness verified each case ID, member, encounter, revision, preparation status and payer status returned by the full collection. It also checked the page order, queue counts and search result identities against the cases it had submitted independently. Original billed PDFs matched byte-for-byte. A corrected bill advanced the revision while preserving the earlier hold. The first 100 cases took 0.56 seconds to seed and the additional 9,900 took 49.05 seconds, including their revision and workflow requests.

The browser comparison measured navigation, rendering and searching on the restored corpus. [Desktop and mobile results](ux-redesign.md#browser-checks)

## Dataset, reproduction and restore

The generator expands the repository's digital inpatient fixtures into ten equally represented starting scenarios, including a duplicate, missing records, inconsistent currency, a corrected claim, staff approval, payer submission, a partial decision and receipts. Each claim keeps unique, synthetic identifiers in both its PDFs and metadata. The hospital, payer, procedure and small example invoices come from a common fixture. The generator reuses these scenarios to measure database and HTTP scale. Clinical diversity, coverage accuracy, unstructured scan processing, production network latency, browser rendering, authentication, sustained traffic and real hospital utilization are outside this test. No OpenAI requests or real patient records are involved. [Source fixtures](../fixtures/discharge/README.md)

With Python, uv, and PostgreSQL tools (`initdb`, `pg_ctl`, `pg_dump`, `pg_restore`) available, run the harness as a regular user. It always starts a private disposable database, generates the corpus, measures each checkpoint, saves the dump locally, and verifies a fresh restore. By default the dump and `results.json` stay under the Git-ignored `.local/testing-audit/db-scale` directory. The measured writes advance the current revision for some duplicate cases.

```sh
uv run --locked python bench/discharge_scale.py --sizes 100 10000 --requests 30 --workers 4
```

To inspect the saved corpus separately, start a local PostgreSQL server and choose an unused database name. The following command chain stops if the database already exists. The dump contains the application's startup fixtures as well as the generated discharge encounters.

```sh
createdb zeroupfront_scale_audit && pg_restore --no-owner --no-acl --exit-on-error \
  --dbname=zeroupfront_scale_audit .local/testing-audit/db-scale/synthetic-discharge.dump
psql zeroupfront_scale_audit -c 'SELECT count(*) FROM zeroupfront_demo.discharge_cases;'
```

To open that scratch database in the built local workspace, use an unused loopback port. The release deployment uses its own staff authentication and database. [Local setup](../CONTRIBUTING.md#run-a-local-workspace)

```sh
DATABASE_URL='dbname=zeroupfront_scale_audit' WORKSPACE_AUTH_MODE=local \
  uv run --locked python app/run_workspace.py --port 8059
```
