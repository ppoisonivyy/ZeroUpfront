# Which reading strategy should ZeroUpfront use?

For this 168-page US edition, use full preprocessed text to find the rules and draft the typed facts. In parallel with that first read, retrieve likely policy pages. Give a second reader the union of the retrieved pages and the pages cited by the first reader. Ask it to reconstruct each material value and cite the specific operative paragraph or table row. Withhold a field for review if the two values disagree or source validation fails. Keep the coordinator's final review and all deterministic amount and revision checks. [US benchmark protocol](us-evaluation-protocol.md) · [Public policy](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/71-005.pdf)

## Paired results

The 18 underlying scenarios comprised 16 answerable benefit questions and two individual financial questions that the brochure could not settle. We asked each in English and Thai. Across the languages there were 32 answerable outputs, 70 substantive field values and four correct opportunities to abstain. In the table, “located” requires that a returned source anchor actually take staff to the provision or table row for that field. Just matching words on the correct page is a weaker test. The audit was conducted by a project AI reviewer against the original PDF. The insurer has not validated these labels. [Original source audit](us-citation-audit.md) · [Field-specific source audit](us-field-source-audit.md)

| Method | Answerable cases given correct values | Answerable cases with every value located in its operative provision | Correct case-specific abstentions |
| --- | ---: | ---: | ---: |
| Lexical plus vector retrieval, eight pages and one answer | 30/32 | 22/32 | 4/4 |
| Full edition and one answer | 32/32 | 24/32 | 4/4 |
| Release only when the full and retrieval answers agree and share a verified page | 29/32 | 22/32 | 4/4 |
| Full edition followed by a field-specific verification read | **32/32** | **32/32** | **4/4** |

The simple agreement rule released 29 factually correct cases and sent three to staff. On one English question the two readers cited different valid pages for observation care. On two Thai questions the search missed the controlling hearing-aid and therapy schedules. Among the three withheld cases, the full reader had the right values in all three. Requiring agreement has an opportunity cost even when it lets through no wrong value.

The field-specific verifier made **36 additional independent API calls**. It saw the original question, contract and selected pages. The primary answer's values and the gold labels were hidden. It reconstructed all 70 substantive values with an operative source for each. The primary reader’s pages supplied the benefit schedules missing from the Thai search results. The verifier supplied separate anchors for the overseas deductible and the filing deadline even when both were on one page. In the rate table, the reviewer checked the employee column against the original layout after native extraction split digits. [Per-field annotations](../bench/us_field_source_audit.json)

Under the fixed page-only rubric, the field-specific route passed **31/32** answerable cases. For the English enrollment question it cited the cover for code 113 and the rate table on physical page 168 for the biweekly premium. The rubric accepted page 168 alone and treated the cover as an extra. Reviewing the cover verified the code directly. Both the reproducible rubric result and the independent source interpretation are preserved. Valid quote text can still point to an unrelated benefit, so automatic validation alone cannot establish the stronger 32/32 result. [Cover](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/71-005.pdf#page=1) · [Rate table](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/71-005.pdf#page=168)

The [recorded predictions](../bench/results/us-policy-2026.json) include all 36 paired language/question outputs for each of the three generation methods, page references and measured timings. They can be inspected without an API key. The record contains no insurer text. [Snapshot generator](../bench/us_policy_snapshot.py)

## Performance and limits

The observed full-policy generation median was **6.35 seconds**, with **3.82 seconds** for top-eight retrieval plus generation excluding query embedding. The field verifier's own median was **5.45 seconds**. Summing the measured full and field-specific times per question gave median **12.50 seconds** and p95 **35.75 seconds** for the two generation stages. These are paired stage sums from separate experimental runs. Queue wait, OCR, front-end loading, human review and actual concurrent orchestration are outside that timing.

Estimated generation charges across 36 questions were **$43.14** for the full read, **$2.46** for the standalone RAG answers and **$2.72** for field-specific verification at the reported token rates. The proposed two-stage path needs the candidate search but can skip generating a separate standalone RAG answer. This makes its observed two generation stages approximately **$1.27 per question**. Indexing and query embeddings for the experiment were approximately two additional cents. These are estimates derived from returned usage and applicable rates; grant billing was not verified. [Token accounting and retry details](us-policy-accuracy.md)

A second read using the same model can reproduce the same mistake. This exploratory verification design followed a failure observed on these same examples. The benchmark measures published benefit facts and case-specific abstention, with English field descriptions available in both languages. It does not establish the correctness of a clinical or payment decision. Independently authored scenarios on additional plan editions, reviewed by a qualified coordinator or insurer, are needed before using the results as a pilot accuracy claim.

## Reproduce

Prepare the pinned source and run the two primary arms first. Their command prints the ignored run directory. Substitute that path for RUN_DIR below. The field verifier sends additional live API requests. Both agreement scorers run offline from completed checkpoints.

```sh
uv run --locked --env-file .env python bench/us_policy_accuracy.py --workers 2
uv run --locked --env-file .env python bench/us_field_verifier.py RUN_DIR --workers 2
uv run --locked python bench/us_policy_consensus.py RUN_DIR/scores.json
uv run --locked python bench/us_policy_consensus.py RUN_DIR/scores.json --field-verifier
```
