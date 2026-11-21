# Independent payer-form holdout

ZeroUpfront identified **10 of 11** requested field outcomes with the right source page on the first blinded run. The eleventh case named a different provider as the recipient of payment. The reader requested a general payee review and missed the specific discrepancy. A separate limitation surfaced on a CMS bill where the message reported an 11-cent difference, but its form citation showed only dollars. After two fixes, a regression run on the same cases returned **11 of 11** target outcomes and cited all six tested printed values in full. [First HTTP observations](../bench/payer_challenge_cases/first-observations.json) · [Regression observations](../bench/payer_challenge_cases/retest-observations.json)

## Results

| Measure | First blinded run | Regression run on the same inputs |
| --- | ---: | ---: |
| Target outcome with correct role and physical page | 10 / 11 | 11 / 11 |
| Exact printed value in original-form citations | 4 / 6 | 6 / 6 |
| Exact printed value in the finding message | 5 / 6 | 6 / 6 |
| False targeted alerts across aligned-field expectations | 0 / 45 | 0 / 45 |
| Aligned fields with an explicit corroborating check and matching source page | 11 / 45 | 11 / 45 |
| Aligned fields with a manual-review response | 9 / 45 | 9 / 45 |
| Aligned fields with neither a targeted alert nor an affirmative check | 25 / 45 | 25 / 45 |
| Held with null payable, no allowed workflow action, approval and export both blocked | 14 / 14 | 14 / 14 |
| Uploaded PDFs retrieved byte-for-byte from each claim | 52 / 52 | 52 / 52 |

A single affirmative check can corroborate related fields, such as a matching provider and populated assignment signature. The 25 silent field observations include CMS alignment and totals where the API exposes a discrepancy only when it finds one. Staff cannot infer that each of those fields was positively verified. Even a correct typed signature or a visible ink mark requires human review of execution and authority.

A later update increased explicit corroboration to **22 of the same 45 fields**. The original blinded and immediate-fix scores above remain available for comparison. [Corroboration follow-up and model audit](payer-model-fidelity.md)

A separately frozen follow-up passed five new payee decisions and three new amount comparisons on the first attempt. [New cases and outcomes](payer-confirmation.md)

## What the packets tested

| Published specimen and case | Required outcome | Form page | First run | Retest |
| --- | --- | --- | --- | --- |
| AIA Thai, amount | THB 87,513.42 differs from THB 87,500.00 on the final bill | Records 2 | Found | Found |
| AIA English, near-match encounter | Certificate says AN-HO825, case and support say AN-HO852 | Records 2 | Found | Found |
| AIA Thai, aligned | New encounter, matching amount, distinct typed patient and clinician marks | Records 2–3 | No false field alert | Same |
| AIA English, graphic consent | Refer the visible vector-only patient mark for staff verification | Records 1 | Found | Found |
| AIA Thai, blank certification | Identify missing clinician mark despite a patient mark, clinician licence and date | Records 3 | Found | Found |
| CMS, near-match insured ID | FL60A HM0130891 differs from the registered HM0130871 | Bill 1 | Found | Found |
| CMS, dollar and cents cells | FL47 USD 12,345.78 differs from the line sum and invoice of USD 12,345.67 | Bill 1 | Found, cents absent from excerpt | Found, cents cited |
| CMS, valid replacement | Type 0117 includes the prior document control number in FL64A | Bill 1 | No false field alert | Same |
| CMS, primary insured ID blank | Require verification even though the invoice includes a member ID on page 3 | Bill 1 | Found | Found |
| FEP, signed assignment to a different provider | Section 5D names Saffron Bay Rehabilitation. The hospital record names Lantern Quay Hospital | Records 1 | General payee review only | Both providers cited |
| FEP, wrong signature role | Main claim signature and a page 2 note cannot fill the blank 5D assignment field | Records 1 | Found | Found |
| FEP, minor currency units | Section 4 THB 158,050.07 differs from THB 158,050.00 on the final bill | Records 1 | Found | Found |
| FEP, member reimbursement | Recognize the two reimbursement selections despite a provider and signature in a page 2 note | Records 1 | Found | Found |
| FEP, aligned | Correct member, named provider, arbitrary typed assignment mark and matching total | Records 1 | No false field alert | Same |

The ten initial hits include an appropriate human referral for a graphic-only mark and a member-reimbursement routing check. Generic layout holds receive no field credit. For split CMS fields, both quoted cells on the same form page must together express the exact amount. Summaries, letter evidence and physical page labels come from the actual uploads. The first failed FEP case received no field credit for a generic payee referral. The specific finding in the retest links the printed recipient to records page 1 and the treating facility to discharge-summary page 1.

## Method and limits

On 21 November 2026 at 05:40 UTC, the evaluator fixed the case inputs, expected fields, role and physical page, aligned controls and safety gates before examining field-reader implementation or querying the integrated application. The golden manifest has SHA-256 `01180c15d91602f24d4fc3e2ebf82c16d891b0f669483bf7ddada784dd3002ce`. The generator changes fictional identifiers, amounts, payee names and signature placement on checksum-pinned public templates. The evaluator rendered and inspected the Thai amount, graphic consent, printed FEP assignment, and CMS FL47 and FL64 cells. All 52 PDFs were byte-identical between runs. The public response vocabulary maps to the same frozen assertions in both scores. [Gold manifest](../bench/payer_challenge_cases/gold.json) · [Field scoring](../bench/payer_challenge_cases/scoring.py)

The runner starts an isolated PostgreSQL database, exercises intake and retrieval over HTTP, attempts review and export, and grades the returned findings and checks. Four concurrent workers exercised the 14 local packets with cloud OCR disabled. Intake latency was 494 ms median and 2.01 s worst on the first run, then 446 ms median and 2.02 s worst on the retest. These times include uploading and screening. They exclude fixture generation and human review.

The field readers had previously seen these form editions and related synthetic generators. The holdout tests new values, combinations and misleading evidence on those editions. The regression inputs became known when the two issues were fixed. Neither score estimates accuracy on unseen payer forms, handwriting, photographs, case approvals or real insurer payments. [Thai form sources and limitations](thai-payer-forms.md) · [US form sources and limitations](us-payer-forms.md)

## Reproduce

Run the current application on the frozen cases from the repository root. The script fetches published blanks if the checksum-verified local cache is empty. The outputs under `.local` include the generated PDFs, preserved return values and score by field.

```bash
uv run --locked python bench/payer_challenge.py --workers 4
```

Recompute either historical score directly from the saved HTTP observations.

```bash
uv run --locked python bench/payer_challenge.py --score-observed bench/payer_challenge_cases/first-observations.json --out .local/holdout-first
uv run --locked python bench/payer_challenge.py --score-observed bench/payer_challenge_cases/retest-observations.json --out .local/holdout-retest
```
