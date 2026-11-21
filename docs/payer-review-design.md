# How ZeroUpfront should review a discharge packet

The initial checker depended on the layout of our fictional hospital exhibits. On 16 synthetic discharge packets assembled from official AIA, CMS and FEP form editions, it held every packet and explained one of 12 deliberately changed facts or missing exhibits. An OCR transcript could contain both the wrong admission number and the claimed amount without the checker connecting either to the case. The revision history, original PDFs and payment ledger worked independently of that failure. [Thailand baseline](thai-payer-forms.md) · [US baseline](us-payer-forms.md)

## Paired experiment

On November 21, 2026, we sent the same scoped encounter metadata and complete role-named PDFs to the same configured OpenAI model, `gpt-6.2-astra`. A structured rubric asked for administrative facts, source roles and physical pages. File names identified only the document role. The model never received the case variant name, expected answer or scoring manifest. The single-pass method returned its assessment directly. The agent had to pick one source page or half-page to magnify and could request a second look before responding. In this run it used one read-only tool call per packet. The request included both the page image and selectable document text. [OpenAI file inputs](https://developers.openai.com/api/docs/guides/pdf-files) · [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)

| Paired set | Packets | Checks matching the expected state and required physical pages, single pass / agent | Median seconds, single pass / agent |
| --- | ---: | ---: | ---: |
| Original AIA, CMS and FEP examples, including aligned comparisons | 16 | 63/63 · 63/63 | 7.34 · 12.04 |
| Independent cases with new values, signatures, payees, decoys and cent differences | 14 | 51/51 · 51/51 | 7.09 · 10.69 |
| Missing evidence, conflicting elections and an image-only Thai exhibit | 5 | 6/6 · 6/6 | 7.54 · 12.86 |

The two arms had identical PDF hashes for each pair. Across 35 packets the medians were **7.30 and 12.01 seconds**. The API reported 334,670 input tokens for the single reads and 740,392 for the agent. Those totals include 28,448 and 364,297 cached input tokens respectively. They measure input volume and cannot be used as invoice totals. These were individual latency measurements under concurrent load, with one measured run per packet and arm. An earlier three-packet tool-availability pilot is excluded. [Per-field outcomes, times and token counts](../bench/results/payer-form-ai-comparison.json)

Both methods correctly withheld a payee decision when two apparently executed FEP forms in the same packet elected different recipients. They cited records pages 1 and 3. Both recognized the changed claimed amount on a raster-only Thai form. They returned unknown for fields whose independent invoice or physician page was unavailable. The stress rubric scores six specified outcomes across five packets. Other incidental narrative statements on those packets are outside that denominator.

The grading rubric accepted the form page for CMS member ID. Both reviewers named the correct IDs but cited only bill page 1. The independent hospital account showed the registered ID on bill page 3. The staff workflow now rereads the original documents for the selected revision, links the form and the hospital record, and uses the numbers from those pages. If it cannot support the comparison, the field goes to staff for verification. An offline replay recovered both physical citations on all four saved CMS reads from two distinct packets. The AIA admission match also links the form and the bill on both saved reads, while its separate graphic consent mark still requires staff review. A live CMS read returned both pages and preserved the claim hold. [Narrative audit](payer-model-fidelity.md) · [Offline replay](../bench/payer_citation_replay.py)

Two additional regression cases injected contradictory observations into the advisory reader. One assigned reimbursement to the member despite the identified hospital assignment. The other reported a missing CMS identifier despite the verified field on the form. Both now return **unknown** with a request for staff verification. A new live CMS read returned the member discrepancy on bill pages 1 and 3 in 6.83 seconds. A separate three-page Thai scan took 66.89 seconds, preserved seven tested text probes and remained held for the amount discrepancy. Each live time is one observation. [Reader regression tests](../tests/test_payer_ai_reader.py)

The initial evaluation label located a Thai printed bill total on page 2. Inspection showed it on page 1. Both model arms were rescored on their saved outputs using the corrected page. [Frozen challenge and expected facts](../bench/payer_challenge_cases/gold.json)

## Product decision

1. Keep the original PDFs by revision. Resolve identity, exhibit role and form edition before combining information. A payer form, an admission letter and a remittance establish different facts.
2. For supported editions, read fixed fields from the original layout and compare each with the independent hospital record. Use exact currency and cents. Give staff the field and physical source pages. The current regression locates all 11 target outcomes and all six exact printed values. [Independent holdout](payer-holdout.md) · [AIA field reader](thai-form-accuracy.md) · [US field readers](us-form-accuracy.md)
3. Use one multimodal read for proposed observations when staff need help. It can inspect form fields and clinical exhibits together. Its notes belong beside the original pages for human verification. Keep automatic financial comparisons, known missing evidence, writable case state, payer approval and actual receipts independent of the model.
4. Let a reviewer or an evidence check trigger additional inspection when facts conflict, a signature box is ambiguous, a source is missing or the edition is unrecognized. Our forced-zoom agent added latency without improving the specified field score. This experiment does not compare every possible agent design. Reserve additional tools for demonstrable gaps, and benchmark the selection and interpretation of those tools separately. A coordinator can already open the original at a cited page and inspect it directly.
5. Track unresolved claims and how long they remain held. The exact readers still hold real-form packets for staff review. The case status can only become automatically ready under the supported overall workflow. Pilot success requires resolving ordinary, aligned packets as well as identifying dangerous exceptions.

Document extraction research evaluates locating a field on a page and associating a value with its row. A single text transcription loses information relevant to both. DocILE evaluates localization and line items across known and unseen layouts. XFUND shows the value of manually labeled key-value pairs for multilingual forms. Its seven languages exclude Thai. Our local evidence is needed for the Thai editions. OpenAI's guidance calls for separate evaluations of tool selection and functional correctness. Anthropic distinguishes predictable workflows from model-directed exploration and recommends measuring the additional complexity. [DocILE](https://arxiv.org/abs/2302.05658) · [XFUND](https://www.microsoft.com/en-us/research/publication/xfund-a-benchmark-dataset-for-multilingual-visually-rich-form-understanding/) · [OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices) · [Anthropic agent design](https://www.anthropic.com/research/building-effective-agents)

## Which search belongs where

For a member or encounter comparison, look up the labeled field on the identified form edition and match the hospital's reference on an independent page for the same encounter and file revision. Repeated IDs on an instruction page, a different encounter, or a second copy of the claim do not establish the comparison. This lookup runs in the application even when the model omits a citation. It takes no additional model or vector-store request. The clinician's mark and the choice of payee may depend on box placement, so staff can open the original image. PDF inputs to a vision-capable OpenAI model include both the extracted text and page images. [OpenAI PDF inputs](https://developers.openai.com/api/docs/guides/file-inputs)

We also gave the model a tool to find a literal string in the current case and return its physical page and nearby text. After strengthening the citation instructions, the PDF-only arm and the forced-search arm each supported all four targeted fields in four synthetic packets. Median time was 8.50 seconds for PDF only and 12.94 seconds with the search tool. The lookup returned nine matching pages for one admission number. Interpreting which document establishes that number still required checking the form and the independent hospital record. [Text-search experiment](payer-text-lookup.md)

For coverage questions, limit search to the applicable policy edition and riders. Hybrid lexical and semantic search can find related wording across languages. Use the full edition and field-specific verification where tested, and show the controlling clause, exceptions, table headers and physical pages. On one 168-page US policy, the Thai questions produced 24 of 35 correct and locally supported fields with hybrid retrieval alone and 31 of 35 with the full policy. English yielded 31 of 35 in both conditions. These are policy questions on one edition. [Independent citation audit](us-citation-audit.md) · [Field-by-field verification](us-hybrid-decision.md) · [OpenAI File Search](https://developers.openai.com/api/docs/guides/tools-file-search)

## What would justify a near-100% claim

Define the target with the pilot hospital and one payer. Score exact amount and currency, payee, member/encounter identity, required evidence, source accuracy, unnecessary holds and unsupported clearances separately. Include the proportion actually resolved and staff review time. Preserve the gold assessor's independent judgment when a form is legitimately ambiguous. The measured cases contain fictional entries on real forms, synthetic signatures and a small number of form editions. Hospital staff have not independently adjudicated them.

The next evidence should come from a consecutive, authorized, de-identified series with independent hospital billing and payer-operations review, held-out facilities or document editions, and adjudication of disagreements. Include alternate layouts, handwriting, genuine redactions, partial packets, corrected bills, successful routine discharges and queries. Keep the final test frozen before adapting to it. As a statistical illustration, 299 independent, representative cases with zero errors would give a one-sided exact 95% lower bound of about 99% for **one prespecified binary metric**. Correlated fields and variants of one form cannot be counted as independent cases for that claim. [NIST exact binomial interval](https://itl.nist.gov/div898/software/dataplot/refman2/auxillar/exacbino.htm)

## Reproduce

Prepare the two native suites and the frozen challenge first. The three `--live` invocations send synthetic records to the configured OpenAI project and consume API credit. Magnification uses Poppler to render a page for the benchmark. The staff release uses direct PDF inputs.

```sh
uv run --locked python bench/payer_forms.py
uv run --locked python bench/payer_challenge.py --prepare-only
uv run --locked --env-file .env python bench/payer_ai_review.py --live --workers 6 --output .local/payer-ai-required
uv run --locked --env-file .env python bench/payer_ai_challenge.py --live --workers 6
uv run --locked --env-file .env python bench/payer_ai_stress.py --live
uv run --locked python bench/payer_ai_results.py
```
