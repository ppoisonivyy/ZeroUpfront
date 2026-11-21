# ZeroUpfront

ZeroUpfront helps hospital coordinators prepare preauthorization requests and check discharge claims. Discharge is the main worklist. A coordinator compares the final bill, discharge summary, written payer letter and supporting records, opens the cited page, and signs off the reviewed revision. Staff can then export the packet and record an external submission, a payer decision and actual payments separately. Pre-arrival stays accessible in the same workspace.

## Start here

- [Run the coordinator workspace](#coordinator-workspace) or [build the release image](docs/deployment.md).
- [Third-party software, services, fonts, form sources and design references](THIRD_PARTY.md) · [Locked versions and licenses](docs/third-party-packages.md) · [Release image components](docs/release-components.md).

- [Discharge claim workflow and comparison with preauthorization](docs/discharge-workflow.md)
- [Discharge screening and settlement test results](docs/discharge-journey-results.md) and [live OpenAI OCR on the scanned discharge summary](docs/discharge-ocr.md)
- [Pre-admission claim-failure scenarios and coordinator actions](docs/claim-journey-results.md)
- [Build, verify and operate the staff release](docs/deployment.md)
- [Color preference research and worklist palette](docs/workspace-colors.md)

- [US policy accuracy and field-specific verification](docs/us-hybrid-decision.md)
- [Coordinator pilot, staff time and cost per verified question](docs/coordinator-pilot.md)
- [Same-case replacement during a live OCR request](docs/same-case-revision.md) and [encounter, lease and export trials](docs/case-revision-guards.md)
- [Benchmark comparison and preprocessing recommendation](docs/benchmark-comparison.md)
- [Context sizing and token counts](docs/context-budget.md)
- [Coordinator application design, revision contracts and three-person build plan](docs/application-design.md)
- [Coordinator screen walkthrough and product design references](docs/coordinator-ux.md)
- [Team journey compared with Thai hospital and insurer workflows](docs/planned-admission-flow.md)
- [Stack, architecture and product research](docs/architecture.md)
- [Original PDFs, reviewed JSON rules and source citations](docs/policy-representation.md)
- [OpenAI hosting, retrieval and credit scope](docs/cloud-rag.md)
- [Thai and English embedding comparison](docs/embedding-eval.md)
- [Decisions API fit and Codex Security for the tech lead](docs/decisions.md)
- [Synthetic policy and treatment packets](fixtures/README.md)
- [Performance measurements and reproduction commands](docs/performance.md)
- [Demo script](docs/demo.md)

## Run the demo

### Coordinator workspace

Use Python 3.12, uv, Node 24 with npm, and PostgreSQL with `initdb` and `pg_ctl` on PATH. From a checkout containing the coordinator app, run the following as a regular user.

```sh
npm --prefix web ci
npm --prefix web run build
uv run --locked python app/run_workspace.py
```

Open [the local workspace](http://127.0.0.1:8038/). On the discharge worklist, choose **Try duplicate bill example**. Inspect the repeated pharmacy charge on page 2, choose **Try corrected bill**, and save the corrected revision. Review its attachments, mark the packet reviewed, then open **Claim and attachments** to preview each original or download the export. **Version history** keeps the original bill accessible.

Choose **Try a case** on the pre-arrival worklist to start a fresh synthetic example. Choose **Partial guarantee** to compare the written letter with actual admission charges, or open Z002 to replace an unitemized estimate. Select an attachment to preview the exact original before downloading the reviewed packet.

The launcher saves case history in a dedicated PostgreSQL cluster under `.local/workspace/`. Use `--data-dir .local/rehearsal/postgres --port 8040` to start an isolated rehearsal. A networked installation uses staff accounts and a dedicated `DATABASE_URL`. Staff record transmissions made through their hospital's existing payer channel. [Staff deployment guide](docs/deployment.md)

Digital processing works offline. For supported scanned pre-arrival and discharge exhibits, configure a funded server-side `OPENAI_API_KEY` and `WORKSPACE_ENABLE_OCR=1` in `.env`, then run `uv run --locked --env-file .env python app/run_workspace.py`. When the only remaining discharge finding concerns OCR, **Verify scanned pages** lets staff compare each original page with its transcript and record the verification. The new revision then goes through ordinary staff review. The long-policy evaluation commands below run separately. [Measured workspace performance](docs/workspace-performance.md)

### Research tools

Clone the repository and use Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/). Create the local key file and enter your project key. The private file is Git-ignored.

```sh
git clone https://github.com/aowngong/ZeroUpfront.git
cd ZeroUpfront
uv sync --locked --python 3.12
test -e .env || (umask 077 && cp .env.example .env)
```

**Original packet checks.** The first command runs four digital checks locally. The second adds two scan variants, transcribes scan pages with Astra and extracts structured fields from the resulting evidence.

```sh
uv run --locked python app/check_fixtures.py
uv run --locked --env-file .env python app/check_fixtures.py --live
```

**Policy and case review.** The live CLI reads the complete selected edition for the two eight-page demo policies. These editions fit comfortably in the model request, and complete context performed better on the evidence benchmark. The Thai example combines a five-page case packet with an eight-page policy and an active rider. The US packet exercises overseas notification and a missing supplier schedule.

```sh
uv run --locked --env-file .env python app/policy_rag.py th "How do the Gold room limit, active rider and companion bed affect the draft amount?" --scanned-case --live
uv run --locked --env-file .env python app/policy_rag.py us "Was the overseas accident notice on time under the active rider?" --live
```

For the hosted search comparison, set up the expiring policy index and select the search mode. Setup creates or reuses an index in the same OpenAI project. Repeat it after seven days of inactivity if the store expires.

```sh
uv run --locked --env-file .env python app/cloud_policy.py
uv run --locked --env-file .env python app/policy_rag.py us "How does the overseas notification rider apply?" --policy-context search --live
```

Both modes submit the selected evidence and current synthetic case to Astra. The program checks quoted text, physical pages and the proposed amount before displaying a draft. Only synthetic policy passages enter the shared index. The source PDFs and the private key file stay in the checkout. Without `--live`, the policy CLI previews lexical search locally. [Model settings](.env.example) · [Hosting and credit scope](docs/cloud-rag.md)

**Evaluation.** Page relevance judgments and financial answers for the complex cases live outside the model input. The supplied JSONL corpus remains a separate text-extraction evaluation.

```sh
uv run --locked python -m unittest discover -s tests
uv run --locked python app/finance_eval.py
uv run --locked python app/eval_documents.py --require-complete
uv run --locked python app/eval_documents.py --samples ZeroUpfront-training-samples
uv run --locked --env-file .env python bench/hosted_recall.py --compare
```

GitHub Actions runs the offline checks on pushes and pull requests. The last command uses your API key and prepared index to compare the live retrieval methods. Use `--live` with the samples evaluator to score model output on the seven held-out text conversations. [Source register and research findings](docs/document-research.md) · [Complex case guide](fixtures/complex/README.md)

## Team ownership

| Role | First responsibility |
| --- | --- |
| Tech lead | Own shared interfaces, integration, performance and the release build. |
| Teammate 1 | Own the main user experience and the on-screen demo flow. |
| Teammate 2 | Own the data, integrations, and demo fixtures. |

Agree on the one flow you want judges to see. Build a minimal version that runs end to end, then polish it. Use GitHub Issues for work that needs coordination and assign each issue one owner.

## Git workflow

Share the public repository link for read access. As repo owner, invite both teammates through **Settings → Collaborators** to let them push feature branches directly to this repository. Invite teammates who run live checks to the funded OpenAI API project so each can create their own key.

1. Branch from `main` for each task, using a short name such as `feat/demo-flow`.
2. Open a small pull request with a summary and a quick way to verify it. Request review from the tech lead for changes to shared interfaces, setup, or deployment. For other changes, any teammate can review.
3. Squash-merge once the change is verified. Keep `main` in a state the team can demo.

Before submission, run through the demo from a fresh clone and tag the commit you submit.

## Inspect one scanned or digital PDF page

```sh
uv run --locked --env-file .env python app/document_text.py fixtures/complex/th-case-mixed.pdf --page 4 --live
```

Native pages are read locally. For a broken text layer, select a single page and add `--force-vision`. Astra receives that physical page as a one-page PDF. The included scan PDFs are ready to use without local OCR software.
