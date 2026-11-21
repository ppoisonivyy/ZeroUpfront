# Answer accuracy on the 168-page US policy

The source is the OPM-hosted *2026 Blue Cross and Blue Shield Service Benefit Plan*, brochure RI 71-005. This comparison answers coordinator questions about the published Standard and Basic options. Both arms received the same page-numbered native text and used the same high-reasoning GPT-6.2 Astra model, instructions and structured answer schema. Each question ran in its own fresh API request, with no other questions, answer keys, previous answers or case records in context. [Official PDF](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/71-005.pdf) · [Frozen questions and physical page groups](../bench/us_policy_questions.json)

The [field-specific comparison](us-hybrid-decision.md) provides the stricter audit of where each individual value is supported.

## Protocol

Eighteen authored scenarios were paired in English and Thai. Sixteen ask answerable questions about US and overseas authorization, direct billing, skilled nursing, transportation, deadlines, appeals, catastrophic limits, hearing aids, therapy, equipment, dentistry, observation, prescriptions and enrollment rates. Two deliberately ask for unavailable case-specific financial facts. Both languages ask about the same English policy. Neither the translations nor the 72 model calls constitute 72 independent policy scenarios.

- **Full text.** Send all 168 numbered pages for each question and require typed responses and cited short excerpts. The question follows the source, allowing prefix caching if the provider serves a cache hit.
- **Hybrid retrieval.** Search 369 page-bounded passages of up to 340 words with 40-word overlap. Embed each source passage and staff question with OpenAI text-embedding-3-large. Rank pages by their best passage in each of two rankings, cosine similarity and BM25-style lexical relevance. Combine unique page ranks using equal-weight reciprocal rank fusion with a constant of 60. Send all text from the first eight distinct physical pages in document order. The cutoff and fusion parameters were fixed before generating the answers.
- **Evaluation.** Compare each JSON primitive to its expected type and value. A question is exact only when every expected field and the answerability flag match, including nulls. For answerable questions, a citation must come from a supplied page, match the normalized wording, and contain at least four words. The joint pass also requires every necessary page group, no missing or extraneous fields, no unverified quotes and no cited pages outside the accepted options. This is page-level attribution. An exact quote on the right page can still be too narrow to support every field on its own.
- **Blinding.** Staff question, output field names, neutral descriptions, types and any allowed enum values were the only question metadata shown. Neither required pages nor expected values entered search, prompts or the model. The initial corpus SHA-256 starts with `03150efda997`. An independent source review before inspection of predictions recorded alternatives for three questions about ordinary overseas admission, observation and overseas drugs. Both page rubrics score the same model outputs. [Page review](../bench/us_policy_gold_review.json)

## Results from 72 independently generated answers

Measured 21 November 2026. **Full text passed all 36 answer-and-evidence checks. Hybrid retrieval passed 34/36.** On English the methods tied at 18/18. On Thai the full edition supplied evidence for the two questions where the top-eight pages missed the governing benefit schedule.

| Verified measure | Full edition | Hybrid RAG, eight pages |
| --- | ---: | ---: |
| English, all typed fields, status and source evidence | 18/18 | 18/18 |
| Thai, all typed fields, status and source evidence | 18/18 | 16/18 |
| Exact individual fields, including explicit unknowns | 74/74 | 67/74 |
| Answerable questions with every field correct | 32/32 | 30/32 |
| Correct abstentions on missing case facts | 4/4 | 4/4 |
| Abstentions on answerable questions | 0/32 | 2/32 |
| Answerable questions with all required evidence somewhere in input | 32/32 | 30/32 |
| Answerable questions citing all required page groups | 32/32 | 30/32 |
| Required evidence groups found, reviewed rubric | 44/44 | 42/44 |
| Page precision on answerable questions | 40/40 | 38/40 |
| Reported quote anchors found on a supplied page, all questions | 44/44 | 43/43 |

Of 36 paired comparisons, full text won two and the methods tied on 34. Raw substantive answer accuracy and the joint pass count happened to be equal. Each of the four deliberately unanswerable requests required an explicit abstention and null field. For example, the source can establish a plan maximum but cannot show how much a fictional member has accumulated. On the frozen original rubric, full text recovered 40/40 required page groups and retrieval recovered 38/40. The independent citation amendments increased the denominator to 44 and left the pass counts unchanged.

**Two retrieval failures.** For Thai question us09, page 58 gives the hearing-aid limits, age-specific benefit periods and approval requirement. The retrieved pages included a cross-reference to hearing aids on page 56 and omitted page 58. Astra withheld all five fields. For Thai us10, page 56 contained a therapy continuation heading, while the visit limits were on pages 55 and 81. The retrieved set contained neither operative page. Astra withheld both numbers. Both English versions found the governing provisions. The two errors therefore affected seven fields and did not produce an invented benefit. [Question specifications](../bench/us_policy_questions.json)

**Citation spot check.** On English us09, a correct retrieval answer gave all five fields and cited the correct page. Its brief quotation captured only the adult amount and frequency. A reviewer can inspect the rest of that page to verify the child's cycle and approval requirement. A patient-facing explanation would need field-level supporting spans. These scores establish typed facts and traceable page evidence on one authored suite. They do not establish clinical validity, insurer approval or generalization to other editions and real staff questions.

## Latency and cost

| Successful-cell measure | Full edition | Hybrid RAG, eight pages |
| --- | ---: | ---: |
| Input tokens per request | 118,985–119,123 | 4,546–7,489 |
| Total input / output tokens | 4,285,560 / 7,424 | 225,992 / 5,416 |
| Cache write / cache read tokens | 4,279,404 / 0 | 219,836 / 0 |
| Median / observed nearest-rank p95 | 6.35 s / 30.76 s | 3.82 s / 5.24 s |
| Estimated total generation cost, 36 calls | $43.1402 | $2.4642 |
| Estimated generation cost per question | $1.198 | $0.068 |

Astra reported cache writes on most input tokens and zero cache reads. Cost estimates apply the published standard short-context ordinary input, 30-minute cache-write, cache-read and output rates to the reported token classes. The timing covers ranking and generation for a completed cell. It excludes upfront indexing and embedding requests, time waiting between benchmark invocations, and time spent on earlier unsuccessful attempts. The first five-worker invocation returned 16 rate-limit errors after SDK retry handling. A successful one-cell probe, a two-worker resume and a final one-worker resume recovered all cells. SDK retries inside individual calls were enabled but not counted separately. The p95 describes these completed calls on this project and includes any retries inside them. This run supplies no deployment SLA or billing invoice. [Astra pricing](https://developers.openai.com/api/docs/models/gpt-6.2-astra)

Index preparation embedded 128,829 previously uncached passage tokens for about $0.01675 at $0.13 per million tokens. A 36-query embedding batch used 3,947 tokens, about $0.00051, and was repeated during resume. We also timed the same questions independently after the experiment. With four workers their median embedding time was 0.237 s and p95 was 0.398 s. A separate one-request batch of all 36 took 6.41 s. The cached-vector RAG rank calculation in the main run had a median of 0.063 s and is included in the RAG times above. Total user-visible response time on an uncached query includes its embedding request. [Embedding model](https://developers.openai.com/api/docs/models/text-embedding-3-large)

## Reproduction

Download the official PDF to `.local/references/us-opm-2026.pdf`. The script checks the exact edition hash before reading it. The public-policy vector cache, native page texts and raw answer checkpoints stay under the ignored `.local` directory. The script resumes missing cells from the same protocol. The offline rescore uses existing checkpoints.

```sh
uv run --locked --env-file .env python bench/us_policy_accuracy.py --prepare-only
uv run --locked --env-file .env python bench/us_policy_accuracy.py --workers 5
uv run --locked python bench/us_policy_accuracy.py --rescore
```
