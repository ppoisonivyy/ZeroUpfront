# Replacing an estimate while the same case is processing

Measured 21 November 2026 on a disposable PostgreSQL 18.6 cluster. **The revised Z002 estimate cleared the AT-2 itemization gap while keeping the original estimate and its decision in history.** The active-revision design served zero stale results in 41 deliberately delayed completions. A comparison query that selected the most recently completed result served the old gap in all 41. The live trial included one Astra transcription of the original image-only estimate.

## What changed in Z002

| Exhibit | Digest prefix | Physical page and extracted evidence | Pre-check |
| --- | --- | --- | --- |
| Original hospital estimate | 22b3430c23d6 | Page 1, THB 82,000 total and no priced service rows | Missing itemization under AT-2 |
| Revised hospital estimate | 392b30b0dd37 | Page 1, THB 52,000 hospital services plus THB 30,000 operating team, total THB 82,000 | Ready for staff review |
| Original estimate, scanned rendering | 92433f447fdc | Page 1, Astra returned THB 82,000 and no priced service rows | Missing itemization under AT-2 |

The plan, member DEMO-Z002, and synthetic policy AT-2026.1 are the same in all three examples. The benchmark checks full SHA-256 digests, member and edition identifiers, page count, the summed line items and the visible decision. A total-only deduplication key would collapse the correction into the original. An unchanged plan can reuse its cached extraction. Both statuses describe hospital staff work. Issuing an insurer guarantee requires separate evidence. [Fixture rulebook](../fixtures/rulebooks.json) · [Z002 documents](../fixtures/cases/Z002) · [Checker used in the benchmark](../app/check_fixtures.py)

## Concurrent trials

Two database connections and event barriers controlled completion order where needed. Each repetition used a new case record and a new extraction cache. Postgres kept default durability settings. The two digital decisions came from the repository's existing reader and checker. The extra live scan trial used the PDF vision route.

| Scenario | Trials passed | Verified behavior |
| --- | ---: | --- |
| Normal amendment | 40/40 | V1 showed the gap. Accepting V2 immediately exposed its queued state, then its itemized result. The unchanged plan was reused each time. |
| V1 worker finishes after V2 | 40/40 + 1 live scan | V1 finished and preserved the original gap in history after V2 was already ready. Current still returned V2. The negative-control query ordered by completion sequence and returned V1 every time. |
| Delivery retries and duplicate workers | 40/40 | Replaying an upload or uploading identical active bytes kept one revision. Reusing the same request ID with a different payload conflicted. Two concurrent claims yielded one worker. A stale first-attempt callback could neither interrupt the active retry nor overwrite its completed result. |
| Two distinct replacements from the same base | 40/40 | Two concurrent submissions carrying different estimate digests produced one accepted V2 and one revision conflict. Staff must resolve the losing update against the new base. |
| V1 finalization races V2 intake | 40/40 | Both lock orders occurred. V1 finalized before intake in 38 trials and after intake in two. After both transactions, V2 was current with no published decision until its worker completed. |
| Failed supplement with V1 still in flight | 40/40 | A wrong-member V2 stayed failed with no usable result after the V1 worker finished. A valid V3 recovered the case. |
| Isolation across case records | 40/40 | Independent Z001 and Z002 revision-1 decisions stayed with their respective cases. Attaching Z001's estimate to Z002 produced a visible failure on Z002 and preserved Z001's prior result. These checks exercised the case keys and member IDs. |

All **280 repeated scenario trials and the additional live scan trial** passed. In the live trial, the V1 worker had already claimed its job and extracted the plan. The test held it at that point until the replacement was uploaded, checked and visible. It then transcribed the original image with Astra and completed V1. This exercises a genuinely late cloud result under a controlled schedule. The benchmark does not estimate how often this race occurs in a hospital.

## Timing and interpretation

| Operation | Observations | p50 | p95 |
| --- | ---: | ---: | ---: |
| Commit a replacement on the local PostgreSQL connection | 40 | 0.183 ms | 0.326 ms |
| Claim, read the cached plan, parse the local one-page revised PDF, check and commit the result | 40 | 1.716 ms | 1.953 ms |

The single cloud-scan race took 3.736 seconds from first submission through both results. The local timing excludes HTTP, transport of document bytes, object-storage writes, user interaction and cloud OCR. p95 is nearest rank over these 40 observations. This research harness uses a row per revision for the manifest and check job, with the plan and estimate digests, current attempt and result. Upload keys, transactions, row locks and an active-revision join protect case state. The fixture harness holds the reader and rulebook fixed for the run. A deployed service must additionally associate the rulebook revision, model and extraction schema with each manifest, support worker lease recovery, authorize every upload and handle object storage and job dispatch. This benchmark exercises actual PostgreSQL operations through a research CLI. Browser uploads, device failures, worker crashes and a deployed work queue need separate end-to-end trials. [Database fixture](../bench/case_revision.sql) · [Benchmark](../bench/case_revision.py)

## What the revision guard leaves open

A separate database check probed four boundaries before interpreting these results as application guarantees.

| Boundary | Observed in the harness | Acceptance check for the application |
| --- | --- | --- |
| Same member, different encounters | Two distinct case records were assigned DEMO-Z002. Uploading the same eligible plan and estimate to each produced two ready-for-review results. These fixture PDFs print the member and policy edition but omit a unique encounter ID. | Match an independently verified encounter or admission. Route a missing or ambiguous match to a coordinator with the original page before permitting a submission-ready result. |
| Worker disappears after claim | The database connection closed after committing its claim. A second worker could not reclaim it, and the revision stayed running. The retry trials above began with an explicit failed attempt. | Simulate worker death, expire its lease, have a second worker claim a new attempt token and reject any publication from the expired attempt. |
| Cross-case or cross-hospital cache use | Two case records with identical plan bytes created two distinct extraction rows; neither reused a plan from the other. The schema has no hospital identifier or access/authorization model. | Exercise two authorized hospitals and two separate caller contexts, including attempts to open a source or extraction by ID. Permit sharing only for an explicitly scoped artifact. |
| Previously approved export | The schema contains neither approvals nor export artifacts. Reading the current database result tests the revision pointer. It does not test a PDF download already open or reachable by an earlier URL. | Race revision replacement with approval, generation and download. Recheck authorization and the approved revision at publication and on the current export route. Make historical exports explicit and retain their actual submitted version. |

## Reproduce

Install PostgreSQL command-line utilities on PATH (initdb and pg_ctl). Use a regular local account so initdb can create a temporary cluster under /tmp. The driver is an isolated benchmark dependency. The script creates its own cluster on a private Unix socket and removes it on exit.

```sh
uv run --locked --with 'psycopg[binary]==3.3.2' python bench/case_revision.py --repetitions 40
```

Add the API environment and scan option to exercise the deliberately late Astra callback. This adds one live PDF transcription to the local trials.

```sh
uv run --locked --with 'psycopg[binary]==3.3.2' --env-file .env python bench/case_revision.py --repetitions 40 --live-scan
```
