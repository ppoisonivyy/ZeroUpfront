# What ZeroUpfront uses

This register covers the hospital workspace, optional research programs, test data and release tooling. The [locked package inventory](docs/third-party-packages.md) lists versions, upstream links and declared licenses for **37 Python packages and 90 npm entries**. The [release image inventory](docs/release-components.md) records the Debian packages and native libraries found in the tested arm64 image. Optional platform packages in a lockfile can differ from what a particular machine installs.

## Product components

| Component | Job in ZeroUpfront | Source and notices |
| --- | --- | --- |
| React and React DOM | Worklists, forms, reviewer actions and revision history | [React, MIT](https://github.com/facebook/react/blob/main/LICENSE) |
| Native HTML controls and project CSS | Search, disclosure, file input, validation, responsive layouts and status labels | Browser-provided behavior. The workflow and styling live in [web/src](web/src). |
| Lucide React | Icons alongside text labels | [Lucide](https://lucide.dev/license), ISC with MIT terms for listed Feather-derived icons |
| Mozilla PDF.js | Renders a selected original PDF page in the browser, including clickable export attachment previews | [PDF.js](https://github.com/mozilla/pdf.js), Apache-2.0. The distribution includes separate resource notices described below. |
| DM Sans and Noto Sans Thai | Locally served interface type and Thai PDF shaping | [DM Sans license](https://github.com/google/fonts/blob/main/ofl/dmsans/OFL.txt), [Noto Sans Thai license](app/fonts/OFL.txt), SIL Open Font License 1.1 |
| FastAPI, Starlette, Uvicorn, Pydantic, python-multipart | HTTP requests, schema validation, multipart uploads and the ASGI server | [Python package versions and notices](docs/third-party-packages.md) |
| PostgreSQL and psycopg | Durable case records, original files, revision history, transactions and concurrent review | [PostgreSQL license](https://www.postgresql.org/about/licence/) and [psycopg license](https://github.com/psycopg/psycopg/blob/3.3.9/psycopg/LICENSE.txt) |
| argon2-cffi | Staff password hashing | [argon2-cffi](https://github.com/hynek/argon2-cffi) and its bindings in the package inventory |
| pypdf, ReportLab, uharfbuzz and Pillow | PDF text extraction, assembly and attachments, generation of synthetic packets, Thai text shaping and image handling | [Python package versions and notices](docs/third-party-packages.md) |
| OpenAI Python SDK, HTTPX2 and HTTPCore2 | Server-side model calls and their HTTP transport | [OpenAI Python, Apache-2.0](https://github.com/openai/openai-python) and [transport package versions](docs/third-party-packages.md) |

**Component choice.** Use the existing libraries for PDF rendering, icons and fonts. Keep claim states, the approval action, evidence citations and payment balances in application code. Native labeled controls cover the current worklist and review forms. For a new dialog that needs focus trapping and focus restoration, evaluate an accessible headless primitive such as Radix Dialog against the keyboard requirements before adding a dependency. Those primitives are candidates for future work. [Radix Dialog](https://www.radix-ui.com/primitives/docs/components/dialog) · [WAI-ARIA dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)

## Assets and notices in the browser release

The Vite build emits a dependency notice at `/assets/third-party-licenses.md`. The [asset-copy script](web/scripts/pdf-assets.mjs) also ships the DM Sans license at `/assets/dm-sans-license.txt` and the original PDF.js resource license files under `/pdfjs/`.

| PDF.js resource location | Attribution and terms supplied by upstream |
| --- | --- |
| `cmaps/LICENSE` | Adobe character maps, with the included redistribution notice |
| `standard_fonts/LICENSE_FOXIT` and `LICENSE_LIBERATION` | Foxit font notice and the Liberation version distributed in this PDF.js release, GPL v2 with the stated font exceptions |
| `wasm/LICENSE_*` | JBIG2, OpenJPEG, qcms and QuickJS components and the PDF.js wrapper notices for each |
| `iccs/LICENSE` | CC0 1.0 for the included color profile |

The Python release also ships ReportLab’s Bitstream Vera and DarkGarden font assets. Its wheel includes the Vera font license, DarkGarden GPL terms and source in `reportlab/fonts/`.

## Services, build and verification

| Use | Components |
| --- | --- |
| Historical FX data | Frankfurter’s free public API serves the ECB USD/THB reference for the synthetic trade date. The application sends the pair, date and publisher. Frankfurter data and the simulated bank offers are displayed separately. [API and open-source project](https://frankfurter.dev/) · [ECB provider](https://frankfurter.dev/providers/ecb) |
| Optional hosted processing | OpenAI Responses for model-assisted extraction, optional staff-triggered full-packet second reads, vision OCR and a staff-triggered Thai/English fee-clause reader for an original payer decision. The agentic comparison used a read-only page-zoom tool in the benchmark. The policy research suite separately uses embeddings, Vector Stores and hosted retrieval. These are hosted services with their own terms and metering. Digital workspace screening runs locally. The project key stays server-side. [Configuration](.env.example) · [Research modes](docs/cloud-rag.md) · [Service terms](https://openai.com/policies/services-agreement/) |
| Local and release builds | CPython, uv, Node.js, npm, TypeScript, the Vite React plugin and Vite. Docker builds use the Node and Python Debian Bookworm images and Astral's uv build image. Python’s base image also includes pip. PostgreSQL runs separately. [Dockerfile](Dockerfile) · [Release guide](docs/deployment.md) |
| CI and source control | Git, GitHub, GitHub Actions hosted runners, actions/checkout, actions/setup-node and astral-sh/setup-uv. The workflow pins action revisions. [Workflow](.github/workflows/preflight.yml) |
| Rehearsal tools | Python unittest, HTTPX, PostgreSQL command-line tools and OpenSSL for local TLS release testing. Poppler utilities inspect or rasterize selected research samples. Browser verification uses Playwright and Chromium on the development machine. |
| Public walkthrough authoring | Playwright automated the click-through with its Chromium driver and the installed Google Chrome browser. FFmpeg encoded the walkthrough video and animated GIF. These authoring tools run separately from the release and its package inventories. Playwright uses Apache-2.0. Chromium’s main license is BSD-3-Clause and bundled components carry their own notices. FFmpeg’s upstream base is LGPL-2.1-or-later, with GPL terms for builds enabling GPL components. [Playwright project and license](https://github.com/microsoft/playwright/blob/main/LICENSE) · [Chromium source license](https://chromium.googlesource.com/chromium/src/+/HEAD/LICENSE) · [Chrome terms](https://www.google.com/chrome/terms/) · [FFmpeg licensing](https://ffmpeg.org/legal.html) |
| Development and team materials | OpenAI Codex assisted development. The team walkthrough uses the presentation tooling in Codex. Neither service handles a claim in the running workspace. |

## Source documents and design references

- The original policy evaluation uses the US OPM 2026 BCBS Service Benefit Plan brochure and Thailand's Allianz Ayudhya Superior Health Plus wording. Their owners publish the originals. The [research source register](docs/document-research.md) records the editions and what was tested.
- The discharge rehearsal uses AIA Thailand's Thai and English claimant/physician forms, the CMS-hosted institutional CMS-1450/UB-04 specimen and the Blue Cross Blue Shield FEP Overseas Medical Claim Form. Templates, logos, form designs and coding material remain subject to their respective terms. The repository contains the harness and fictional case values. Downloaded templates and completed copies stay in the ignored local workspace. [AIA Thailand form library](https://www.aia.co.th/th/help-support/form-library) · [CMS-1450](https://www.cms.gov/regulations-and-guidance/legislation/paperworkreductionactof1995/pra-listing-items/cms-1450) · [FEP forms](https://www.fepblue.org/claim-forms)
- The training-sample folder describes synthetic text conversations. The project also generates fictional bills, clinical exhibits, payer replies, amounts and identifiers for rehearsal. [Fixture guide](fixtures/README.md) · [Document evaluation](docs/document-research.md)
- The review interface adapts worklist and evidence-review patterns described by Linear, Stripe and Availity. The NHS design system informs status label research. These organizations are design references. [Linear triage](https://linear.app/docs/triage) · [Stripe disputes](https://docs.stripe.com/disputes/responding) · [Design references, including Availity](docs/ux-redesign.md) · [Color research](docs/workspace-colors.md)

## Refresh the inventories

Run from the repository root. The first command queries version-specific PyPI metadata and reads npm's lockfile. The optional image inventory also uses the local Docker engine.

```sh
uv run --locked python scripts/dependency_inventory.py
docker build -t zeroupfront:release .
uv run --locked python scripts/dependency_inventory.py --image zeroupfront:release
```

The Pattaya settlement rehearsal uses the published THB 239,000 price and the hospital’s description of direct billing. All case exhibits, bank quotes and receipts were created for the rehearsal. [Hospital package](https://www.bangkokhospital.com/en/pattaya/package/lens-replacement-surgery-package-bph) · [Hospital billing process](https://www.bangkokhospital.com/en/pattaya/visit/insurance-bph)

This register attributes third-party work. The repository currently has no top-level license for the team's original code.
