# Contributing to ZeroUpfront

The default workspace opens the hospital’s discharge worklist. A claim revision ties the uploaded PDFs to its findings and page citations. Staff approval, the payer’s written response and receipt of money are separate events. Start with the [demo walkthrough](docs/demo.md) or the [discharge workflow](docs/discharge-workflow.md).

## Run a local workspace

Use Python 3.12, uv, Node.js 24 with npm, and the PostgreSQL server tools. CI uses Node 24 and Python 3.12. Run the local launcher as a regular user. Check that both `initdb --version` and `pg_ctl --version` work. If your PostgreSQL installation supplies `pg_config`, its `--bindir` output shows which directory to add to your PATH.

```sh
git clone https://github.com/aowngong/ZeroUpfront.git
cd ZeroUpfront
uv sync --locked --python 3.12
npm --prefix web ci
npm --prefix web run build
uv run --locked python app/run_workspace.py
```

With `DATABASE_URL` unset, the launcher serves the app on loopback and keeps a private PostgreSQL cluster in `.local/workspace/postgres/`. Stop with Ctrl+C and restart to resume. For a separate rehearsal, append `--data-dir .local/rehearsal/postgres --port 8040`. Synthetic digital cases work without an OpenAI key. [Discharge worklist](http://127.0.0.1:8038/#/discharge) · [Pre-arrival cases](http://127.0.0.1:8038/#/cases)

Select **Try duplicate bill example** to create a fresh claim. Open the page citation, replace the duplicate bill using **Try corrected bill**, and inspect both revisions in **Version history**. Use **Claim and attachments** after staff review to inspect the export and its source documents. For frontend changes, keep the launcher running on port 8038 and run `npm --prefix web run dev` in a second terminal. Open the URL printed by Vite. Its development proxy forwards `/api` to the launcher.

## Find the code and data

| Area | Entry point |
| --- | --- |
| Web navigation and discharge screens | [Route handling](web/src/main.tsx) · [Discharge workspace](web/src/Discharge.tsx) |
| Discharge intake, review and settlement | [HTTP routes](app/discharge_api.py) · [Screening rules](app/discharge_claim.py) · [Revision and event storage](app/discharge_store.py) |
| Form-specific field checks and second reads | [AIA Thailand](app/payer_aia.py) · [CMS and FEP](app/payer_us.py) · [Optional AI reader](app/payer_ai_reader.py) |
| Case data and expected outcomes | [Discharge exhibits](fixtures/discharge/README.md) · [Complex Thai and US cases](fixtures/complex/README.md) · [Text extraction samples](ZeroUpfront-training-samples/README.md) |
| Architecture and trade-offs | [Application design](docs/application-design.md) · [Policy representation and citations](docs/policy-representation.md) · [Context and retrieval experiments](docs/benchmark-comparison.md) |
| Dependencies and provenance | [Software and form sources](THIRD_PARTY.md) · [Locked package licenses](docs/third-party-packages.md) · [Release components](docs/release-components.md) |

## Verify a change

Run the entry point that a coordinator uses. A change to a finding should identify the correct physical page and preserve access to the source PDF on the earlier revision. These commands cover the main local checks. CI also runs loopback HTTP, concurrent revision and container tests. [CI workflow](.github/workflows/preflight.yml)

```sh
npm --prefix web run build
uv run --locked python -m unittest discover -s tests
uv run --locked python app/check_fixtures.py
uv run --locked python app/finance_eval.py
uv run --locked python app/eval_documents.py --require-complete
uv run --locked python app/eval_documents.py --samples ZeroUpfront-training-samples
uv run --locked python bench/discharge_journey.py
```

To reproduce the payer-form checks, run the following in order. The first command tests Thai and US packets in parallel using separate disposable databases. Preparation downloads fingerprinted official blank forms when the cache is empty. The filled cases, original PDFs and raw run reports stay under the ignored `.local/` directory. The final replay uses the six saved model responses and requires no external connection. [Thai findings](docs/thai-form-accuracy.md) · [US findings](docs/us-form-accuracy.md) · [Held-out comparisons](docs/payer-holdout.md) · [Citation and model evaluation](docs/payer-review-design.md)

```sh
uv run --locked python bench/payer_forms.py
uv run --locked python bench/payer_challenge.py --prepare-only
uv run --locked python bench/payer_citation_replay.py
```

For an individual digital page or a local policy-search preview, these commands show what evidence the reader sees. Use the documented benchmark commands when investigating long policies or stale revisions. [168-page US policy](docs/us-hybrid-decision.md) · [Thai and English embeddings](docs/embedding-eval.md) · [Same-case document replacement](docs/same-case-revision.md) · [Workspace timings](docs/workspace-performance.md)

```sh
uv run --locked python app/document_text.py fixtures/complex/us-case.pdf --page 1
uv run --locked python app/policy_rag.py us "Was the overseas accident notice on time?"
```

## Optional OpenAI workflows

Create a private environment file and enter your own funded project key under `OPENAI_API_KEY`. Each teammate can use a separate key in the same OpenAI project. Keep credentials server-side. The repository ignores `.env`. [Configuration template](.env.example)

```sh
test -e .env || (umask 077 && cp .env.example .env)
```

For scanned uploads, set `WORKSPACE_ENABLE_OCR=1`. For the staff-triggered advisory read, set `WORKSPACE_ENABLE_AI_REVIEW=1`. Restart the local launcher with `uv run --locked --env-file .env python app/run_workspace.py`. OCR transcribes selected pages. A confirmed second read sends the available original PDFs and encounter metadata for that revision and returns provisional observations. These calls use API credit. [Staff configuration and processing limits](docs/deployment.md)

The research CLIs have their own live switches. Use synthetic packets for these commands. Add `--force-vision` to the single-page command to inspect a broken selectable text layer.

```sh
uv run --locked --env-file .env python app/check_fixtures.py --live
uv run --locked --env-file .env python app/document_text.py fixtures/complex/th-case-mixed.pdf --page 4 --live
uv run --locked --env-file .env python app/policy_rag.py th "How does the active rider affect the draft amount?" --scanned-case --live
```

For the hosted retrieval comparison, `cloud_policy.py` creates or reuses the synthetic policy index in the configured OpenAI project. The following commands exercise hosted search and measure retrieval recall. [Index lifecycle and credit use](docs/cloud-rag.md)

```sh
uv run --locked --env-file .env python app/cloud_policy.py
uv run --locked --env-file .env python app/policy_rag.py us "How does the overseas notification rider apply?" --policy-context search --live
uv run --locked --env-file .env python bench/hosted_recall.py --compare
```

## Staff release

The release serves the built React client and FastAPI from one origin. Give each hospital a dedicated PostgreSQL database and `DATABASE_URL`, set `WORKSPACE_HOSPITAL_NAME`, and use staff mode behind HTTPS. The deployment guide covers account provisioning, proxy settings, and the `/healthz` and `/readyz` probes. To build and rehearse the release locally with Docker, run the commands below. [Deployment guide](docs/deployment.md)

```sh
docker build -t zeroupfront:release .
uv run --locked python bench/container_release.py
```

## Working together

Update the public README and walkthrough in the same change whenever the demo, supported workflow or reported results change. Keep the [build declaration](docs/hackathon-declaration.md) current when adding a deliverable or reusing another project, dataset or service. Preserve first-run measurements when publishing a retest.

Branch from `main`, keep commits focused, and include the reproduction command or UI steps in each pull request. In the three-person team, the tech lead coordinates API contracts, integration and release checks. The other two owners can work in parallel on the coordinator experience and the data, fixtures and integrations. Ask the tech lead to review changes that cross those boundaries. A public GitHub link gives read access. Invite teammates as repository collaborators to let them push branches directly.
