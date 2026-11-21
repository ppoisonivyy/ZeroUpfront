# Encounter binding, expired leases and historical exports

The original revision benchmark caught wrong-member supplements and rejected callbacks from earlier attempts. A separate check found that a second encounter for the same member could still accept the first encounter's estimate. A worker that disconnected after claiming a job also left it stuck in the running state. The database experiment below tested fixes for both behaviors and a proposed rule for exporting an approved revision. [Original observations](same-case-revision.md#what-the-revision-guard-leaves-open)

| Check | Original behavior | Follow-on result |
| --- | --- | --- |
| One member, two encounters | Both case IDs accepted the same synthetic estimate and plan. Their PDFs recorded DEMO-Z002 and AT-2026.1 but supplied no encounter identifier. | **40/40 trials passed.** Both candidate cases initially withheld a result. A separate hospital record then bound the estimate digest to encounter A. Only A could proceed. Encounter B stayed blocked, as did a case in another hospital with the same encounter number. |
| Connection loss after a worker claim | The disconnected worker's revision stayed running. A replacement worker could not claim it. | **40/40 passed.** The original worker claimed token 1 and disconnected. After its lease actually expired on PostgreSQL's clock, two separate connections raced the old completion against a new claim. The new worker got token 2 and committed the sole current result. The expired callback was rejected in all 40 races and again after the replacement committed. |
| Approved export during replacement | The original harness had no review or export table. Its current-result test could not exercise stale downloads. | **40/40 passed.** Replacing the estimate rejected a delayed writer and an old approval attempt. The current-export lookup became empty while the explicit historical lookup still returned the originally issued artifact digest. Reinstating the identical estimate bytes required a fresh review and produced a distinct test artifact. |

These **120 trials** ran on a disposable PostgreSQL 18.6 cluster using the same Z002 PDFs and existing deterministic checker. A case row locks acceptance or publication against concurrent revision changes. The follow-on schema binds a verified estimate digest to a specific hospital and encounter. A fresh worker attempt increments a monotonically increasing token. PostgreSQL accepts completion only when the attempt matches, its lease is still valid, and the revision remains active. Approval binds to the revision and verified run. A historical artifact remains associated with that review and can be addressed separately from the current one.

The hospital verification record is supplied as test input. A pilot must establish how an authorized coordinator verifies the encounter against a trusted record and how to handle legitimate later corrections to that binding. The export test stores SHA-256 digests of deterministic fixture bytes. Insurer PDF generation, browser downloads, authorization, object-store retention and already-issued signed URLs remain independent integration checks. A direct download URL issued before a revision change needs its own expiry or revocation design if current-only access must end immediately.

## Reproduce

The local run creates its own PostgreSQL cluster under /tmp and requires initdb and pg_ctl on PATH. It needs no API key.

```sh
uv run --locked --with 'psycopg[binary]==3.3.2' python bench/case_revision_guards.py --repetitions 40
```

[Guard experiment](../bench/case_revision_guards.py) · [Original schema and fixture digests](../bench/case_revision.py)
