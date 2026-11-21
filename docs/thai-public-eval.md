# Retrieval from a public Thai insurance policy

On 21 November 2026, `text-embedding-3-large` retrieved all the evidence for **2 of 6 Thai questions** among its top four pages. Small found none. The same comparison on English translations of the six questions yielded **2 of 6 for each model**. The result identifies a gap before using the digital-text path on this policy in a hospital pilot.

## Source and labels

The candidate set comprised all 42 physical PDF pages of Allianz Ayudhya's Thai *Superior Health Plus* policy, including its covers. Six original questions were written in Thai and English after reading the policy. Every labeled page was visually checked in a render before scoring. The page labels below count from the first PDF page. The printed footer number is one lower on each labeled page. [Official Allianz PDF](https://www.allianz.co.th/content/dam/onemarketing/azay/allianz-co-th/document-download/forms/Allianz-Policy-Superior-Health-Plus-TH.pdf) · [Paired queries and labels](../bench/thai_public_queries.json)

| Scenario | Physical pages accepted | Evidence visible on the rendered page |
| --- | --- | --- |
| Registered inpatient dies soon after admission | 4 | Definition gives the usual six-hour minimum and the exception for death following admission. |
| Dependent was already hospitalized when cover began | 7 | Section 6.2 addresses recovery and discharge after the earlier admission. |
| ICU room benefit | Either 20 or 23 | Both pages give the multiplier and duration. Either fully satisfies this question. |
| Worker moves to a lower-risk occupation | 31 | The occupational-change clause states when a proportional premium refund begins. |
| Death of a motorcycle passenger | Both 33 and 36 | Page 33 states the base exclusion. Page 36 provides the extension and its percentage. |
| Late claim smaller than a claim-free rebate | 37 | The endorsement addresses the difference when the rebate exceeds the subsequent claim. |

## Method and results

Each physical page supplied one candidate. The locked pypdf version extracted its selectable text, and whitespace was collapsed. Both models received the same page strings and the 12 question strings through the Embeddings API. Page labels, gold groups and expected answers stayed local. The benchmark ranked the 42 L2-normalized page vectors by their dot product with each query. This run used default dimensions, 1,536 for small and 3,072 for large. It created no hosted search index. [Embeddings API reference](https://developers.openai.com/api/reference/resources/embeddings/methods/create)

“Hit” counts questions with at least one relevant page. “Recall” counts distinct evidence requirements satisfied, with seven per language across six questions. “Complete” counts questions for which every requirement was met.

| Question language | Model | Hit @1 | Recall @1 | Complete @1 | Hit @4 | Recall @4 | Complete @4 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Thai | Small | 0/6 | 0/7 | 0/6 | 0/6 | 0/7 | 0/6 |
| Thai | Large | 3/6 | 3/7 | 2/6 | 3/6 | 3/7 | 2/6 |
| English | Small | 0/6 | 0/7 | 0/6 | 2/6 | 2/7 | 2/6 |
| English | Large | 2/6 | 2/7 | 1/6 | 3/6 | 3/7 | 2/6 |

Large ranked the motorcycle endorsement first in both languages but missed the exclusion in the top four. Neither model found a complete answer for the short inpatient stay, the already-hospitalized dependent, or the change to a safer occupation in either language. Both topics that large completed were ICU costs and the rebate.

The extracted pages contained **1,571 Unicode replacement characters**. This comparison measures page retrieval from that damaged text layer. It cannot isolate the effects of extraction errors, page length, query language or the embedding model. One insurer and six hand-authored question pairs give a narrow test. The next comparison should repeat these frozen questions against visually verified OCR from the same pages and measure the change in complete evidence sets.

## Reproduce

Download the official PDF above as `.local/references/th-allianz-superior.pdf`. The evaluator checks SHA-256 `d5b4e3f8d3bbf2c524f0dabf9b2ed0e942f7e9bad02c8eb5a7120d0633e3fcd4` before sending extracted page text to the API. Provide a server-side key in `.env`.

```sh
uv run --locked --env-file .env python bench/thai_public_recall.py
```

The command prints the top four pages for each query. Both live calls reported **84,911 input tokens each**, giving an estimated **$0.01274 combined** at the published standard embedding prices. The local cache contained zero matching page vectors for either model at evaluation time. [OpenAI model pricing](https://developers.openai.com/api/docs/models/text-embedding-3-large)

## Preprocess the same edition with Astra

We pinned the same PDF digest and applied the existing reader to all 42 pages, independent of the question labels. It routed 41 pages to Astra because of damaged text or image content and accepted native text on physical page 41. All 42 pages completed, with zero pages dropped. No Unicode replacement characters remained in the resulting text. This measures a specific text-layer defect. Verifying every digit, cell association and Thai character would require a separate labeled transcription.

| Input to the large embedding model | Thai complete @4 | English complete @4 |
| --- | ---: | ---: |
| Native text, all pages | 2/6 | 2/6 |
| Astra-processed text, all pages | 3/6 | 4/6 |

This rerun used the same 12 questions, candidate pages, evidence groups, and cosine scoring. The Thai question about motorcycle passengers still found the endorsement on page 36 while missing the base exclusion on page 33. English found both. Both languages missed the applicable pages for a short admission and a dependent hospitalized before coverage. Even after repairing the text, page retrieval alone remains a weak basis for a coverage check.

The estimated standard API cost for this one edition was **$2.10**. Astra used 82,084 input and 35,757 output tokens, and the large embedding request used 77,582 tokens. Reuse that extraction across cases. Its source text and checkpoints stay in the ignored local cache. A page that fails is identified explicitly in benchmark output.

```sh
uv run --locked --env-file .env python bench/thai_ocr_recall.py --help
uv run --locked --env-file .env python bench/thai_ocr_recall.py
```
