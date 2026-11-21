# ZeroUpfront hackathon declaration

ZeroUpfront is a hospital billing prototype developed for the Sea x OpenAI Regional Codex Hackathon Thailand at Singha Complex, Bangkok, on 21 November 2026. The event agenda sets a 10:00 start and 17:00 code freeze, Bangkok time (UTC+7). The organizers allow existing projects and judge substantial new work completed at the event. [Organizer agenda and FAQ](https://luma.com/39zve8ph)

## What existed before the build

The team’s preparation pack dated 18 November described the product idea. On 21 November the 09:02 repository scaffold contained a README, demo outline, ignore file and empty application directory. The project was renamed at 09:28. Both commits preceded the 10:00 start. The next commit at 11:06 added synthetic fixtures and imported a supplied sample corpus. Repository timestamps record when those files entered Git. The original author and creation date of the supplied corpus remain unverified. [Scaffold](https://github.com/aowngong/ZeroUpfront/commit/47b6efc99bc49e341b5d9dedd339f73f12d60eeb) · [Rename](https://github.com/aowngong/ZeroUpfront/commit/2bdede36e2df9f917025d415e4c8bc5b5e5c452c) · [Fixtures and supplied examples](https://github.com/aowngong/ZeroUpfront/commit/fcc32aaa5e99d52650fa6f380c3e1f1f9f2a763b)

## What the team built

The workspace lets hospital staff reconcile an inpatient discharge claim against its original documents. The recorded example uses a fictional admission and a repeated pharmacy charge. A coordinator finds the duplicate on the invoice, reviews a corrected revision and exports the reviewed packet. The longer rehearsal records a simulated payer decision and two partial receipts. [Recorded walkthrough](figures/discharge-walkthrough.gif) · [Full rehearsal](demo.md)

| Component | What we added to the existing tools | Evidence |
| --- | --- | --- |
| Coordinator worklist | Using React and PDF.js, linked each finding to its original PDF page and added bill correction, revision review and clickable export attachments. | [Interactive flow](demo.md) · [Review interface](../web/src/Discharge.tsx) |
| Claim revisions and settlement | Using FastAPI and PostgreSQL, bound approval to a specific revision, preserved original documents and tracked submission, payer decisions and receipts separately. | [Revision and settlement code](../app/discharge_store.py) · [Rehearsal](discharge-journey-results.md) |
| Thai and US payer-form checks | Built edition-specific comparisons for IDs, totals and payment recipients on AIA, CMS and FEP forms. Created synthetic cases with frozen expected results, including manual review for ambiguous fields. | [AIA reader](../app/payer_aia.py) · [US reader](../app/payer_us.py) · [First-run results and misses](payer-holdout.md) |
| Optional OpenAI second read | Added a staff-triggered multimodal read with citations. A Codex-assisted fix recovered the supporting invoice page when the model found conflicting member IDs but cited only the form. | [Reader](../app/payer_ai_reader.py) · [Fix](https://github.com/aowngong/ZeroUpfront/commit/b4d21f1334f96a03d87c93addf2d5188b2caca9b) · [Evidence replay](../bench/payer_citation_replay.py) |

The live hospital app adopts the team’s DM Sans typography, forest-green case header, horizontal navigation and document-first review layout. The standalone hospital and insurer design prototype demonstrates pre-arrival review and the guarantee handoff with synthetic cases. It embeds the project’s Z002 documents, Solar icons and the Archivo, DM Sans and IBM Plex Mono fonts. Both HTML pages include the asset notices. [Prototype and review guide](workspace-review/README.md)

The team also built repeatable 10,000-claim database, API process and CPU-quota benchmarks, and tested search privacy, request-size controls and certificate-verified database transport. The single-hospital release and these synthetic rehearsals are the scope of the security evidence. [Benchmarks](scaling.md) · [Security controls](security-and-encryption.md)

## What we used

- **Software and services.** React, TypeScript, Vite, Mozilla PDF.js, Lucide, FastAPI, PostgreSQL, pypdf and ReportLab provide application and PDF infrastructure. OpenAI Responses provides optional transcription and second reads. The separate policy experiments used OpenAI embeddings and hosted retrieval. Codex also assisted development and presentation work. [Component, asset and license register](../THIRD_PARTY.md)
- **Published materials.** The AIA Thailand inpatient forms, CMS-1450/UB-04 specimen and Blue Cross Blue Shield FEP Overseas Medical Claim Form supplied the layouts. Our test harness populated them with fictional identifiers, amounts and marks. The downloaded and completed PDFs stay local. Policy research used the OPM-hosted 2026 BCBS Service Benefit Plan brochure and Allianz Ayudhya Superior Health Plus wording. [Thai forms](thai-payer-forms.md) · [US forms](us-payer-forms.md) · [Policy editions](document-research.md)
- **Supplied examples and design references.** The project received 14 synthetic training conversations and seven evaluation conversations. Their source notes describe layout observations from sample hospital documents and the use of invented patient details. Linear, Stripe and Availity informed the worklist and evidence-review interaction. [Training sample provenance](../ZeroUpfront-training-samples/README.md) · [Design references](ux-redesign.md)
