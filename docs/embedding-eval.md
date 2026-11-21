# Bilingual policy retrieval experiment

Live run on 21 November 2026. Use `text-embedding-3-large` as the current candidate for multilingual retrieval. On the Thai questions it placed a relevant page first on 12 of 16 attempts, compared with 7 of 16 for `text-embedding-3-small`. The advantage varied by source language and question.

## Test design

The benchmark has 16 administrative questions with paired natural Thai and English wording, including colloquial descriptions of a theatre booking after an accident, a companion bed billed with the room and a missing statement sheet. The pairs share the same page labels. These are project-authored questions with topics derived from the fictional policies. They have not been independently validated by Thai hospital staff.

Eight intents target the fully English US policy. Eight target the Thai-origin policy, which has bilingual headings and predominantly English operative wording. For each query, the selected policy edition supplies eight candidate pages. The default passage splitter produces one passage per page for these fixtures. The same passages and queries go to each embedding model. Case files, expected answers and page labels stay outside the API input.

Each API request embeds 16 passages and 32 query strings as separate inputs. The benchmark normalizes vectors and ranks them by exact cosine similarity. It uses default dimensions: 1,536 for small and 3,072 for large. Each model reported 5,004 input tokens. This experiment isolates vector retrieval. The demo also includes a lexical ranker, whose fusion scores could change ordering.

## Results

“First hit” counts queries where rank one is a labeled page. “Complete” requires *all* labeled pages within the specified cutoff. Page recall counts individual labeled pages recovered. Nine questions require two pages, so a single result can complete at most seven questions in either language.

| Query language | Model | First hit | Page recall @1 | Complete @1 | Hit @4 | Page recall @4 | Complete @4 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| English | Small | 14/16 | 14/25 | 6/16 | 15/16 | 22/25 | 13/16 |
| English | Large | 15/16 | 15/25 | 7/16 | 16/16 | 25/25 | 16/16 |
| Thai | Small | 7/16 | 7/25 | 2/16 | 15/16 | 21/25 | 12/16 |
| Thai | Large | 12/16 | 12/25 | 5/16 | 14/16 | 22/25 | 14/16 |

| Cross-language subset | Model | First hit | Complete @1 | Page recall @4 | Complete @4 |
| --- | --- | ---: | ---: | ---: | ---: |
| Thai question → English US policy | Small | 4/8 | 1/8 | 12/13 | 7/8 |
| Thai question → English US policy | Large | 6/8 | 2/8 | 11/13 | 7/8 |
| Thai question → bilingual-heading Thai policy | Small | 3/8 | 1/8 | 9/12 | 5/8 |
| Thai question → bilingual-heading Thai policy | Large | 6/8 | 3/8 | 11/12 | 7/8 |

The larger model retrieved both the base rule and the current rider for the Thai-language overseas notification and room-limit questions. The smaller model missed the rider in both cases. Conversely, large missed both pages for the Thai question combining insurer acknowledgment with proof of payment; small recovered both. Large also missed the governing page for the Thai midnight-observation question. Splitting questions with distinct evidence requirements is worth testing on new blind cases.

This measures page retrieval on short, mostly English policies. It does not establish Thai OCR character error, Thai-to-Thai performance on complete Thai contracts, draft correctness, real-hospital recall or a statistically stable model advantage. Retrieving four of eight pages is a generous cutoff. The English and Thai paraphrases share topics with existing test fixtures and should remain a development comparison.

## Reproduce

```sh
uv run --locked --env-file .env python bench/bilingual_embeddings.py --details
```

This uses two live embedding requests. It does not persist embeddings or change the application's policy cache. The [fixture questions and labels](../bench/bilingual_queries.json) and the [benchmark script](../bench/bilingual_embeddings.py) disclose the inputs and metric calculations.
