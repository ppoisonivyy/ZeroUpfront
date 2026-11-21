# ZeroUpfront

ZeroUpfront helps a hospital's international patient department prepare a clause-cited guarantee-of-payment request. This repository includes the stack design, original synthetic PDFs, an executable pre-check evaluation and performance benchmarks.

## Start here

- [Benchmark comparison and preprocessing recommendation](docs/benchmark-comparison.md)
- [Context sizing and token counts](docs/context-budget.md)
- [Coordinator application design, revision contracts and three-person build plan](docs/application-design.md)
- [Stack, architecture and product research](docs/architecture.md)
- [Original PDFs, reviewed JSON rules and source citations](docs/policy-representation.md)
- [OpenAI hosting, retrieval and credit scope](docs/cloud-rag.md)
- [Thai and English embedding comparison](docs/embedding-eval.md)
- [Decisions API fit and Codex Security for the tech lead](docs/decisions.md)
- [Synthetic policy and treatment packets](fixtures/README.md)
- [Performance measurements and reproduction commands](docs/performance.md)
- [Demo script](docs/demo.md)

## Run the demo

For this preparation snapshot, clone the research branch. Use Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/). Create the local key file and enter your project key. The private file is Git-ignored.

```sh
git clone --branch prep/research-reliability https://github.com/aowngong/ZeroUpfront.git
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
