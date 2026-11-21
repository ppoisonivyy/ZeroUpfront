# What ZeroUpfront uses

This register covers the hospital workspace, optional research programs, test data and release tooling. The [locked package inventory](docs/third-party-packages.md) lists versions, upstream links and declared licenses for **37 Python packages and 90 npm entries**. The [release image inventory](docs/release-components.md) records the Debian packages and native libraries found in the tested arm64 image. Optional platform packages in a lockfile can differ from what a particular machine installs.

## Product components

| Component | Job in ZeroUpfront | Source and notices |
| --- | --- | --- |
| React and React DOM | Worklists, forms, reviewer actions and revision history | [React, MIT](https://github.com/facebook/react/blob/main/LICENSE) |
| Native HTML controls and project CSS | Search, disclosure, file input, validation, responsive layouts and status labels | Browser-provided behavior. The workflow and styling live in [web/src](web/src). |
| Lucide React | Icons alongside text labels | [Lucide](https://lucide.dev/license), ISC with MIT terms for listed Feather-derived icons |
| Mozilla PDF.js | Renders a selected original PDF page in the browser, including clickable export attachment previews | [PDF.js](https://github.com/mozilla/pdf.js), Apache-2.0. The distribution includes separate resource notices described below. |
| Inter and Noto Sans Thai | Locally served interface type and Thai PDF shaping | [Inter](https://rsms.me/inter/), [Noto Sans Thai license](app/fonts/OFL.txt), SIL Open Font License 1.1 |
| FastAPI, Starlette, Uvicorn, Pydantic, python-multipart | HTTP requests, schema validation, multipart uploads and the ASGI server | [Python package versions and notices](docs/third-party-packages.md) |
| PostgreSQL and psycopg | Durable case records, original files, revision history, transactions and concurrent review | [PostgreSQL license](https://www.postgresql.org/about/licence/) and [psycopg license](https://www.psycopg.org/psycopg3/docs/basic/install.html#license) |
| argon2-cffi | Staff password hashing | [argon2-cffi](https://github.com/hynek/argon2-cffi) and its bindings in the package inventory |
| pypdf, ReportLab, uharfbuzz and Pillow | PDF text extraction, assembly and attachments, generation of synthetic packets, Thai text shaping and image handling | [Python package versions and notices](docs/third-party-packages.md) |
| OpenAI Python SDK and HTTPX | Server-side model calls, HTTP transport and test clients | [OpenAI Python, Apache-2.0](https://github.com/openai/openai-python) and [HTTPX](https://www.python-httpx.org/) |

**Component choice.** Use the existing libraries for PDF rendering, icons and fonts. Keep claim states, the approval action, evidence citations and payment balances in application code. Native labeled controls cover the current worklist and review forms. For a new dialog that needs focus trapping and focus restoration, evaluate an accessible headless primitive such as Radix Dialog against the keyboard requirements before adding a dependency. Those primitives are candidates for future work. [Radix Dialog](https://www.radix-ui.com/primitives/docs/components/dialog) · [WAI-ARIA dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)

## Assets and notices in the browser release

The Vite build emits a dependency notice at `/assets/third-party-licenses.md`. The [asset-copy script](web/scripts/pdf-assets.mjs) also ships the Inter license at `/assets/inter-license.txt` and the original PDF.js resource license files under `/pdfjs/`.

| PDF.js resource location | Attribution and terms supplied by upstream |
| --- | --- |
| `cmaps/LICENSE` | Adobe character maps, with the included redistribution notice |
| `standard_fonts/LICENSE_FOXIT` and `LICENSE_LIBERATION` | Foxit font notice and the Liberation version distributed in this PDF.js release, GPL v2 with the stated font exceptions |
| `wasm/LICENSE_*` | JBIG2, OpenJPEG, qcms and QuickJS components and the PDF.js wrapper notices for each |
| `iccs/LICENSE` | CC0 1.0 for the included color profile |

## Services, build and verification

| Use | Components |
| --- | --- |
| Optional hosted processing | OpenAI Responses for model-assisted extraction and vision OCR. The policy research suite separately uses embeddings, Vector Stores and hosted retrieval. These are hosted services with their own terms and metering. Digital workspace screening runs locally. The project key stays server-side. [Configuration](.env.example) · [Research modes](docs/cloud-rag.md) · [Service terms](https://openai.com/policies/services-agreement/) |
| Local and release builds | CPython, uv, Node.js, npm, TypeScript, the Vite React plugin and Vite. Docker builds use the Node and Python Debian Bookworm images and Astral's uv image. PostgreSQL runs separately. [Dockerfile](Dockerfile) · [Release guide](docs/deployment.md) |
| CI and source control | Git, GitHub, GitHub Actions hosted runners, actions/checkout, actions/setup-node and astral-sh/setup-uv. The workflow pins action revisions. [Workflow](.github/workflows/preflight.yml) |
| Rehearsal tools | Python unittest, HTTPX, PostgreSQL command-line tools and OpenSSL for local TLS release testing. Poppler utilities inspect or rasterize selected research samples. Playwright and Chromium were used for browser verification and walkthrough captures. These tools run outside the production UI. |
| Development and team materials | OpenAI Codex assisted development. The team walkthrough uses the presentation tooling in Codex. Neither service handles a claim in the running workspace. |

## Source documents and design references

- The original policy evaluation uses the US OPM 2026 BCBS Service Benefit Plan brochure and Thailand's Allianz Ayudhya Superior Health Plus wording. Their owners publish the originals. The [research source register](docs/document-research.md) records the editions and what was tested.
- The discharge rehearsal uses AIA Thailand's Thai and English claimant/physician forms, the CMS-hosted institutional CMS-1450/UB-04 specimen and the Blue Cross Blue Shield FEP Overseas Medical Claim Form. Templates, logos, form designs and coding material remain subject to their respective terms. The repository contains the harness and fictional case values. Downloaded templates and completed copies stay in the ignored local workspace. [AIA Thailand](https://www.aia.co.th/) · [CMS-1450](https://www.cms.gov/regulations-and-guidance/legislation/paperworkreductionactof1995/pra-listing-items/cms-1450) · [FEP forms](https://www.fepblue.org/claim-forms)
- The training-sample folder describes synthetic text conversations. The project also generates fictional bills, clinical exhibits, payer replies, amounts and identifiers for rehearsal. [Fixture guide](fixtures/README.md) · [Document evaluation](docs/document-research.md)
- The review interface adapts worklist and evidence-review patterns described by Linear, Stripe and Availity. The NHS design system informs status label research. These organizations are design references. [Linear triage](https://linear.app/docs/triage) · [Stripe disputes](https://docs.stripe.com/disputes/responding) · [Color research](docs/workspace-colors.md)

## Refresh the inventories

Run from the repository root. The first command queries version-specific PyPI metadata and reads npm's lockfile. The optional image inventory also uses the local Docker engine.

```sh
uv run --locked python scripts/dependency_inventory.py
docker build -t zeroupfront:release .
uv run --locked python scripts/dependency_inventory.py --image zeroupfront:release
```

This register attributes third-party work. The repository currently has no top-level license for the team's original code.
