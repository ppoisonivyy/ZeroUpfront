# Passage retrieval on a 42-page Thai insurance policy

On 21 November 2026, embedding smaller passages of the Allianz Ayudhya Superior Health Plus policy improved complete top-four evidence for Thai questions from **3/6 to 4/6**. English remained at **4/6**, with a different set of misses. The insured-dependent question still failed in both languages. A promising first hit alone would leave a coordinator without the evidence needed to review some requests. [Official Thai policy PDF](https://www.allianz.co.th/content/dam/onemarketing/azay/allianz-co-th/document-download/forms/Allianz-Policy-Superior-Health-Plus-TH.pdf)

## What changed

Both methods used exactly the same 42 physical pages and the same six staff questions in Thai and English. The cached reader had accepted Astra transcriptions on 41 pages and native text on one. This experiment reused that text. Each method used text-embedding-3-large at its default 3,072 dimensions and the same 12 query vectors. The source policy digest and six sets of acceptable evidence pages were fixed in advance. [Benchmark](../bench/thai_passage_recall.py) · [Questions and evidence groups](../bench/thai_public_queries.json)

The baseline embedded one text per page. The alternative divided each page into overlapping windows of up to 900 Unicode code points, targeting a 160-character overlap. It preferred a newline within the last third of the window, then a space, and otherwise cut at the window limit. It avoided splitting before a combining mark. This works on text with few spaces and keeps each excerpt associated with one physical page. It produced 132 passage vectors. For each question, the highest passage cosine on a page became that page’s score. The four highest-scoring distinct pages were returned. Every page participated in every query. Questions and answer labels had no role in splitting or page scoring.

## Measured results

A hit means at least one acceptable page appeared at the cutoff. Completion requires a page from **every** required evidence group. The six questions have seven required groups. The accident question requires both the exclusion and rider. Either of two pages satisfies the intensive-care question.

| Question language | Indexed text | Hit @1 | Complete @1 | Hit @4 | Evidence groups @4 | Complete @4 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Thai | Whole page | 2/6 | 1/6 | 4/6 | 4/7 | 3/6 |
| Thai | Overlapping passages | 4/6 | 3/6 | 5/6 | 5/7 | 4/6 |
| English | Whole page | 3/6 | 2/6 | 4/6 | 5/7 | 4/6 |
| English | Overlapping passages | 5/6 | 4/6 | 5/6 | 5/7 | 4/6 |

The short-admission exception on physical page 4 moved from outside the top four to first place in both languages. For the motorcycle-passenger question, English whole-page retrieval supplied the rider on page 36 and the exclusion on page 33. Passage retrieval retained the rider and lost the exclusion. Thai retrieved the rider alone in both runs. Both methods missed physical page 7 for the dependent who was already hospitalized when cover began.

The run embedded 809 query tokens, 76,773 whole-page tokens and 90,061 passage tokens. Together these total **167,643 tokens**, an estimated **USD 0.02179** at the standard embedding price of USD 0.13 per million input tokens. Both the original OCR cost and a deployed index's storage costs fall outside this incremental estimate. [Embedding model pricing](https://developers.openai.com/api/docs/models/text-embedding-3-large)

## Reproduce

With the pinned policy's 42 reader-approved checkpoints in the Git-ignored cache, run the following command from the repository root. The script checks the source digest recorded in the cache, requires all 42 accepted pages and prints the four retrieved pages for each query. It makes paid embedding requests. The insurer text and vectors remain outside Git. [Reader benchmark for populating the cache](../bench/thai_ocr_recall.py)

```sh
uv run --locked --env-file .env python bench/thai_passage_recall.py
```

This test covers one Thai policy and six project-authored intents expressed in two languages. It measures retrieval of labeled pages. It leaves OCR transcription accuracy, clause interpretation, amount calculation and retrieval on other insurers unmeasured. Given the observed loss of a governing exclusion, test retrieval of the base clause and the rider together on independently labeled cases before choosing a production default.
