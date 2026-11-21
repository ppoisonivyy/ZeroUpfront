# Full-policy reading versus top-four retrieval

On 21 November 2026, GPT-6.2 Astra identified the exact labeled page set on **8/8 questions** when given all eight pages of the applicable synthetic edition. With the same prompt and four pages chosen by the demo's managed retrieval pipeline, Astra identified the exact set on **6/8**. The full-policy arm took less time and cost about twice as much per question. These are measurements of source selection on two short policies. The two Thai retrieval failures were already known when the team chose the tasks. [Paired questions and page labels](../bench/bilingual_queries.json)

| Input supplied to Astra | All required pages present in answer | Exact page set | Precision | Recall | Median / slowest query | Estimated token cost per query |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Eight policy pages | 8/8 | 8/8 | 14/14 | 14/14 | 2.217 / 2.337 s | $0.0164 |
| Four managed retrieval results | 6/8 | 6/8 | 11/12 | 11/14 | 3.949 / 4.875 s | $0.0081 |

Each question received one independent call in each arm, with standard service, low reasoning effort and the same 240-output-token ceiling. The input contained the original English or Thai question and numbered passages in physical page order. All 16 calls completed. Gold labels, staff task keys, case records and insurer verdicts were excluded from both prompts. A match requires a returned page to appear both in the supplied context and in that question's label set. Precision pools matches over all returned page numbers. Recall pools matches over all labeled page numbers. The denominator counts each distinct page once per question.

| Staff question | Labeled pages | English, full / retrieved | Thai, full / retrieved |
| --- | --- | --- | --- |
| US accident notice and rider | 3, 7 | 3, 7 / 3, 7 | 3, 7 / 3, 7 |
| US proof of insurer approval and patient payment | 6, 8 | 6, 8 / 6, 8 | 6, 8 / 1 |
| Thai base room allowance and rider | 4, 7 | 4, 7 / 4, 7 | 4, 7 / 4, 7 |
| Thai midnight observation | 3 | 3 / 3 | 3 / empty |

For both missed Thai questions, retrieval supplied pages 1, 2, 4 and 7 of the respective edition. In the US policy, page 1 mentions a written guarantee. Pages 6 and 8 explain why a submission acknowledgement and a statement of charges cannot establish insurer approval and payment. A fallback triggered only by an empty answer would miss that incomplete response. On midnight observation, Astra returned an empty list when retrieval omitted the governing page. [US policy](../fixtures/complex/us-policy.pdf) · [Thai policy](../fixtures/complex/th-policy.pdf)

## Runtime and cost

Full context consumed 12,867 Astra input and 108 output tokens. The provider reported 11,915 cache-write tokens within that input and zero cache reads. The retrieval arm consumed 7,394 Astra input and 105 output tokens, zero cache reads or writes, and 11,884 large embedding tokens. Retrieval added a median 1.753 seconds. The estimates are $0.1311 for full context and $0.0649 for retrieval, for **$0.1960 combined**. They apply published standard short-context input, output, 30-minute cache-write and embedding rates to the observed usage. Shared vector-store storage, prior indexing and tax are outside this estimate. Timing begins after loading and validating the PDFs and includes retrieval, reranking and generation as applicable. Four questions could be in flight. [OpenAI pricing](https://developers.openai.com/api/docs/pricing) · [Hosted retrieval](https://developers.openai.com/api/docs/guides/retrieval)

## When to read the full edition

For an open question on one verified eight-page policy like these, sending the whole edition is a reasonable default when its token cost fits the request budget. The reviewer can then open the cited original page. If a longer edition needs retrieval, a candidate fallback is to expand a short, verified section when a rider points to a missing base clause or one half of a multipart inquiry has no direct support. Apply a prompt-size limit and route unresolved cases to staff. That conditional strategy needs its own blind evaluation. A full-policy call following a failed search incurs the cost and time of both operations.

The separate structured lookup gives staff the referenced clauses after they explicitly select a supported workflow and edition. Its 4/4 completeness describes the project-authored mappings. These eight open questions assess page selection from natural language. Neither experiment measures the factual correctness of a generated insurance decision, performance on long Thai contracts or the quality of the models' OCR. The development set contains four topics with paired paraphrases, two selected for prior retrieval misses, so 8/8 is too little evidence for a general precision claim. [Structured lookup](../bench/rulebook_lookup.py) · [Policy design](policy-representation.md)

## Reproduce

Use the prepared hosted index, the same two policy PDFs, `text-embedding-3-large` for reranking and a project API key. The command makes eight managed searches and reranks, plus sixteen Astra calls. It prints the supplied and selected pages, token usage, per-question timings and aggregate scores. [Benchmark code](../bench/context_comparison.py)

```sh
uv run --locked --env-file .env python bench/context_comparison.py
```
