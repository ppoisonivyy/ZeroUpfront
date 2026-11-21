# ZeroUpfront benchmark comparison

Measured 21 November 2026. **Preprocess a supported policy edition once. For a bounded edition like the 42-page policy tested here, let Astra consult the whole page-numbered text on an open question. Use explicit rule lookups for known coordinator tasks.** Keep the original PDF accessible for reading table cells and verifying every cited page. These measurements support parallel extraction of independent exhibits, followed by a case-revision check before a draft becomes available to staff.

## One real 42-page Thai policy

Six questions tested definition exceptions, an already-admitted dependent, ICU limits, an occupation change, a motorcycle endorsement and a claims rebate. Each question was asked in Thai and English. Success required *all* labeled evidence, including both physical pages 33 and 36 for the motorcycle scenario. Pages 20 and 23 were accepted alternatives for the ICU question. These are source-location tasks. No arm was graded on a coverage verdict or clinical reasoning. [Questions, visual labels and official policy](thai-public-eval.md)

| Method | Thai complete | English complete | What the model or retriever saw |
| --- | ---: | ---: | --- |
| Native digital text, whole-page embeddings | 2/6 | 2/6 | All 42 page vectors. Return the top four. |
| Preprocessed text, whole-page embeddings | 3/6 | 4/6 | Same pages with Astra transcription where the native text was damaged or scanned. |
| Preprocessed text, smaller passage embeddings | 4/6 | 4/6 | 132 passages. Rank unique physical pages and return four. |
| Original PDF directly to Astra | 6/6 | 6/6 | Entire PDF with text and page images. One call per language. |
| Preprocessed full text to Astra | 6/6 | 6/6 | All 42 numbered pages. One call per language. |

Both full-context methods returned seven relevant page citations out of seven predictions in each language. Search returned fixed-size lists per query and the model could select a variable number of pages. The score compares whether evidence was available in each output. Six queries were batched together per language in each full-context arm, so timing below is **per six-question request**. The gold pages stayed outside model inputs. Source questions were authored after inspecting this edition. [Passage experiment](thai-passage-eval.md) · [Full-context benchmark script](../bench/thai_context_recall.py)

| Full-context input | Thai wall time | English wall time | Input tokens per batch | Estimated inference per batch |
| --- | ---: | ---: | ---: | ---: |
| Original PDF | 8.77 s | 7.03 s | 76,089–76,244 | $0.61 |
| Full preprocessed text | 3.25 s | 3.17 s | 35,822–35,977 | $0.29 |

Astra accepted 41 OCR pages and one native page. The one-time page processing was approximately $2.09, plus about one cent to embed the recovered text. The full-text inference arm used zero embedding requests. Its input was about 53% smaller. At these measured uncached input sizes and standard prices, roughly seven similar batches would recover the initial OCR spend through lower input cost. Actual cache pricing, response length and future model prices change that estimate. A first encounter with an unprocessed policy can use the original PDF directly. [Token rates](https://developers.openai.com/api/docs/pricing) · [How OpenAI processes PDF inputs](https://developers.openai.com/api/docs/guides/file-inputs)

As a check on batching, we sent each of the two difficult scenarios (dependent already admitted and motorcycle passenger) alone in Thai and English using the complete preprocessed text. All four calls returned the exact labeled pages, including both the exclusion and its endorsement. These are repeats on the same edition. [Whole-request context sizing](context-budget.md)

## Short editions and staff-selected tasks

A second comparison used two eight-page synthetic editions and four tasks, each asked independently in Thai and English. Both model arms used the same Astra prompt and model. Seeing all eight pages produced **8/8 exact evidence sets**, 14/14 page precision and 14/14 required pages. With the current hosted-search top four, Astra produced **6/8 exact sets**, 11/12 page precision and 11/14 required pages. Median elapsed time was 2.22 s with all eight pages and 3.95 s with retrieval and selection. Estimated token cost was $0.0164 and $0.0081 per question respectively. Search saved input tokens and added a network step. Both Thai misses involved omitted evidence. [Paired context comparison](context-comparison.md)

With a staff-selected workflow key, the project-authored JSON clause map returned **4/4 complete tasks and 7/7 required pages** and verified every quote, edition and file digest. This evaluates lookup on deliberately supported tasks. A wrong mapping or an omitted rider still requires review by someone who understands the policy. An unseen new insurer cannot inherit these results. [Lookup benchmark](policy-representation.md#working-example-of-a-curated-clause-map)

## Supplementary document processing

Two one-page synthetic scans were extracted in alternating sequential and parallel runs. Two workers completed the pairs in **4.24 s and 4.21 s**. Sequential runs took **7.37 s and 8.21 s**. Pooled wall time decreased **45.8%**, with the same source and fact checks passing on all eight extractions. Most input was cached. The two scans were independent exhibits from different synthetic cases. Process an arriving supplement immediately, preserve its revision, and wait for the current case's required documents before publishing a result. The subsequent [same-case revision benchmark](same-case-revision.md) tested concurrent replacement and a live OCR request. Representative production throughput remains unmeasured. [Parallel benchmark](parallel-intake.md)

## Whole-request size

The OpenAI input-count endpoint reported **36,181 tokens** for the complete page-numbered Thai text, instructions, a question and a five-page synthetic case. The same measurement on the 168-page US brochure with a five-page case was **119,372 tokens**. The original high-detail US PDF by itself used **373,397 tokens**. The model accepts up to 922,000 input tokens and changes price above 272,000. All three fit, with the original US PDF falling into the higher pricing tier. These counts measure fit. A later [168-page US policy evaluation](us-hybrid-decision.md) tested typed benefit facts, abstention and field-level evidence on the same public edition. [Reproducible token counts](context-budget.md) · [Astra limits and pricing](https://developers.openai.com/api/docs/models/gpt-6.2-astra)

## Reproduce the real-policy comparison

Follow the source download and checksum instructions in the public-policy report. Run from the repository root using a funded project key in the private environment file. The OCR script caches its completed pages in the ignored local directory. The other runs reuse that text.

```sh
uv run --locked --env-file .env python bench/thai_public_recall.py
uv run --locked --env-file .env python bench/thai_ocr_recall.py
uv run --locked --env-file .env python bench/thai_passage_recall.py
uv run --locked --env-file .env python bench/thai_context_recall.py
uv run --locked --env-file .env python bench/thai_context_recall.py --isolated
```

Keep retrieval for discovering the right edition, searching larger libraries, and suggesting clauses to a rulebook reviewer. Scope every request by edition and digest and reserve enough context for the case exhibits and answer. If the edition exceeds the model's input or operating budget, load mandatory dependencies from the reviewed rulebook, add search results, and flag unresolved scope to staff. Build evidence for longer or unfamiliar editions before choosing a page-count cutoff.
