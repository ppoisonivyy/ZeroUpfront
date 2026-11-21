# Discharge claim rehearsal

On 2026-11-21, all 22 synthetic packet scenarios returned the expected screening status and required findings. Staff approval was blocked on all 21 unresolved packets. All uploaded originals were retrieved byte for byte. The app left the payable amount blank in every case.

Multipart intake and screening over local HTTP with PostgreSQL took 37 ms median and 51 ms p95 with 4 concurrent workers and one request per example. This measures small digital PDFs on the development machine. It excludes OCR, staff time and the payer response.

| Uploaded example | Expected status | Observed status | Observed issues |
| --- | --- | --- | --- |
| aligned | ready_for_review | ready_for_review | None |
| duplicate_line | needs_review | needs_review | duplicate_line |
| orphan_credit | needs_review | needs_review | orphan_credit |
| total_mismatch | needs_review | needs_review | total_mismatch |
| over_cap | needs_review | needs_review | over_cap |
| share_mismatch | needs_review | needs_review | share_mismatch |
| member_mismatch | needs_review | needs_review | member_mismatch |
| encounter_mismatch | needs_review | needs_review | encounter_mismatch |
| unapproved_procedure | needs_review | needs_review | unapproved_procedure |
| stay_extension | needs_review | needs_review | stay_extension |
| late_reply | needs_review | needs_review | late_reply |
| mixed_currency | needs_review | needs_review | mixed_currency |
| missing_support | needs_review | needs_review | missing_support |
| unit_mismatch | needs_review | needs_review | unit_mismatch |
| unsupported_terms | needs_review | needs_review | unrecognized_layout, missing_or_ambiguous_field |
| excess_credit | needs_review | needs_review | excess_credit |
| date_mismatch | needs_review | needs_review | date_mismatch |
| missing_records | needs_review | needs_review | missing_records, missing_support |
| unreadable_summary | needs_review | needs_review | unreadable_summary |
| wrong_payer | needs_review | needs_review | payer_mismatch |
| credit_before_charge | needs_review | needs_review | credit_before_charge |
| discharge_in_future | needs_review | needs_review | discharge_in_future |

## One case from correction to payment

The duplicate-line bill blocked approval. Uploading the original corrected bill produced revision 2. Revision 1 retained its finding and a stale approval attempt returned HTTP 412. A staff reviewer approved revision 2 and its downloaded PDF contained all four exact originals.

The simulated payer queried the packet and later confirmed THB 80,000 as a partial decision. The app still showed unpaid. Recording THB 50,000 changed settlement to partially paid. A duplicate remittance reference returned HTTP 409. A second receipt for THB 30,000 completed settlement against the written decision. All submissions, responses and remittances here were synthetic.

Reproduce from the repo root with `uv run --locked python bench/discharge_journey.py`. Use `--report PATH` to save the observed results. The role-specific PDFs and scenario definitions are in [the discharge fixtures](../fixtures/discharge/expected.json). The [workflow research](discharge-workflow.md) describes the external steps and manual checks.

## Public policy in the wrong document slot

We uploaded each complete public plan brochure in place of the member-specific payer letter, keeping the three other exhibits synthetic. Cloud OCR was disabled. Both status and approval guards were exercised.

| Uploaded brochure | Physical pages | Observed result | Time including approval attempt |
| --- | --- | --- | --- |
| us-opm-2026.pdf | 168 | Needs investigation, payable blank, approval HTTP 409 | 922 ms |
| th-allianz-superior.pdf | 42 | Needs investigation, payable blank, approval HTTP 409 | 1060 ms |

Use one `--policy-as-letter PATH` per local brochure to reproduce this check. It tests document-role confusion. Clause-level question accuracy has a separate [US](us-hybrid-decision.md) and [Thai](thai-public-eval.md) evaluation.
