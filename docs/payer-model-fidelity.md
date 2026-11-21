# Fidelity of the two PDF review methods

The full-PDF pass and the reviewer with a page-inspection tool both located **11 of 11** targeted outcomes on the intended physical pages. Both handled the three aligned controls correctly. Across five separate stress cases, each met all six prespecified expectations. A second local audit compared the saved answers to the original synthetic exhibits. It made no model requests. [Frozen holdout](payer-holdout.md) · [Offline audit](../bench/payer_challenge_cases/model_audit.py)

| Test | Full-PDF pass | PDF reviewer with inspection tool |
| --- | ---: | ---: |
| Frozen target, expected physical role and page | 11 / 11 | 11 / 11 |
| Aligned control packets with expected states | 3 / 3 | 3 / 3 |
| Both original and comparison values correctly named on six changed-value targets | 6 / 6 | 6 / 6 |
| Individual observed field states across the 14 holdout packets | 51 / 51 | 51 / 51 |
| Stress expectations with appropriate evidence or contextual page | 6 / 6 | 6 / 6 |
| Citations to an actual role and physical page across both suites | 108 / 108 | 108 / 108 |
| Saved PDF bundle digests matched the generated originals | 19 / 19 | 19 / 19 |

The six paired values include the two AIA admission references, two CMS insured identifiers, two provider names and three amount comparisons. Both narratives correctly reported USD 12,345.78 versus USD 12,345.67 in CMS FL47 and the final invoice, and THB 158,050.07 versus THB 158,050.00 on the FEP claim and bill. The aligned CMS replacement identified original DCN **83944167021**. The AIA graphic-only consent went to visual review, and the typed marks were described as visible entries. Those answers establish what appears on the page. They cannot authenticate the signer or authorize settlement.

## What a page citation establishes

For the wrong CMS member, both reviewers accurately wrote that the form shows **HM0130891** and intake says **HM0130871**. Both cited only bill page 1. That page shows the disputed form value. The independent invoice header containing the intake value appears on bill page 3. The intake metadata was also supplied to the model. A coordinator opening the sole citation cannot verify the comparison from that page alone. In the English graphic-consent case, the single-pass admission check likewise cited the certificate page only. The tool-assisted answer also cited the discharge summary containing the comparison number.

A controlled negative check changed the final digit in a copy of the CMS answer to **HM0130897**, kept its `conflict` state, and kept bill page 1. Both the state check and page-range check still passed. The value check failed. The original saved answers contained the correct digit. This illustrates why a well-formed citation count alone overstates the evidence. The PDF digest covers the uploaded files. It does not authenticate independently supplied intake metadata or the prompt.

## Stress cases

| Packet | Observed behavior in both modes |
| --- | --- |
| FEP form with no independent bill | Read THB 158,050.00 from section 4 and left the comparison unknown. |
| CMS claim without its invoice annex | Read USD 11,285.00 from FL47. The supporting service register contained no amounts, so both left the comparison unknown. |
| Conflicting FEP payee elections | Cited records pages 1 and 3. The dated provider assignment on page 1 names Lantern Quay Hospital. Page 3 selects member reimbursement by check and leaves 5D blank. Both declined to choose a payee. |
| AIA packet missing Part B | Left the admission number comparison and physician certification unknown. The physician mark on Part A did not satisfy the separate Part B requirement. |
| AIA amount on an image-only page | Cited records page 2 and bill page 1 for THB 92,750.00 versus THB 87,500.00. Both reported the THB 5,250.00 difference. |

The audit checked the actual page counts and original bytes, inspected the affected images, and compared the changed identifiers, amounts and payees to the frozen manifest. Each mode supplied one saved answer per packet. These samples show no field-accuracy advantage for the inspection tool. They cannot estimate production error rates or performance on other payer editions. [Stress construction and preregistered targets](../bench/payer_ai_stress.py) · [Synthetic packet definitions](../bench/payer_challenge_cases/packets.py)

## Deterministic corroboration after the field-reader changes

A separate HTTP rerun used the same 45 known aligned fields. The reader now returns **22 explicit corroborations** with a matching original page, up from **11** in the first run and immediate-fix retest. The remaining 23 comprise **nine manual referrals** and **14 fields with no targeted result**. Most new evidence came from matched US identifiers, discharge dispositions, bill frequencies, original reference presence and invoice totals. Some CMS checks stop after a missing or inconsistent insured identifier. The run maintained 11/11 targeted outcomes, 6/6 complete changed-value citations, 0/45 false targeted alerts, and 14/14 safely held cases. This rerun uses cases the authors had already seen. [Latest corroboration snapshot](../bench/payer_challenge_cases/affirmative-observations.json) · [First two runs](payer-holdout.md)

To rescore the historical deterministic snapshot or audit saved model runs without remote calls, run these commands from the repository root. The model audit expects the two original local output directories and their PDF fixtures. Its `--help` lists path overrides.

```bash
uv run --locked python bench/payer_challenge.py --score-observed bench/payer_challenge_cases/affirmative-observations.json --out .local/holdout-affirmative
uv run --locked python bench/payer_challenge_cases/model_audit.py
```
