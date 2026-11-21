# Independent payer-form holdout

On the frozen 14-packet regression, the current reader locates **11 of 11** target outcomes on their required physical pages. It identifies when a form names a different receiving provider and cites both dollar and cents cells for a split CMS amount. [Regression observations](../bench/payer_challenge_cases/retest-observations.json)

## Results

| Measure | Current result |
| --- | ---: |
| Target outcome with correct role and physical page | 11 / 11 |
| Exact printed value in original-form citations and finding messages | 6 / 6 |
| False targeted alerts on aligned fields | 0 / 45 |
| Aligned fields with explicit corroboration and matching source page | 22 / 45 |
| Aligned fields referred to manual review | 9 / 45 |
| Aligned fields without an explicit finding or corroboration | 14 / 45 |
| Unverified cases held with approval and export blocked | 14 / 14 |
| Uploaded PDFs retrieved byte-for-byte | 52 / 52 |

The absence of an alert does not establish that a field was positively verified. A signature still requires human review of execution and authority. [Corroboration and model audit](payer-model-fidelity.md)

A separately frozen follow-up passed five new payee decisions and three new amount comparisons on the first attempt. [New cases and outcomes](payer-confirmation.md)

## What the packets tested

| Published specimen and case | Required outcome | Form page | Current result |
| --- | --- | --- | --- |
| AIA Thai, amount | THB 87,513.42 differs from THB 87,500.00 on the final bill | Records 2 | Found |
| AIA English, near-match encounter | Certificate says AN-HO825, case and support say AN-HO852 | Records 2 | Found |
| AIA Thai, aligned | New encounter, matching amount, distinct typed patient and clinician marks | Records 2–3 | No false field alert |
| AIA English, graphic consent | Refer the visible vector-only patient mark for staff verification | Records 1 | Found |
| AIA Thai, blank certification | Identify missing clinician mark despite a patient mark, clinician licence and date | Records 3 | Found |
| CMS, near-match insured ID | FL60A HM0130891 differs from the registered HM0130871 | Bill 1 | Found |
| CMS, dollar and cents cells | FL47 USD 12,345.78 differs from the line sum and invoice of USD 12,345.67 | Bill 1 | Found, cents cited |
| CMS, valid replacement | Type 0117 includes the prior document control number in FL64A | Bill 1 | No false field alert |
| CMS, primary insured ID blank | Require verification even though the invoice includes a member ID on page 3 | Bill 1 | Found |
| FEP, signed assignment to a different provider | Section 5D names Saffron Bay Rehabilitation. The hospital record names Lantern Quay Hospital | Records 1 | Both providers cited |
| FEP, wrong signature role | Main claim signature and a page 2 note cannot fill the blank 5D assignment field | Records 1 | Found |
| FEP, minor currency units | Section 4 THB 158,050.07 differs from THB 158,050.00 on the final bill | Records 1 | Found |
| FEP, member reimbursement | Recognize the two reimbursement selections despite a provider and signature in a page 2 note | Records 1 | Found |
| FEP, aligned | Correct member, named provider, arbitrary typed assignment mark and matching total | Records 1 | No false field alert |

The scoring accepts a human referral for a graphic-only mark. Generic layout holds earn no field credit. For split CMS fields, the quoted cells must together express the exact amount. For the FEP recipient comparison, the finding links the printed recipient on records page 1 and the treating facility on discharge-summary page 1.

## Method and limits

On 21 November 2026 at 05:40 UTC, the evaluator fixed the case inputs, expected fields, role and physical page, aligned controls and safety gates before examining field-reader implementation or querying the integrated application. The golden manifest has SHA-256 `01180c15d91602f24d4fc3e2ebf82c16d891b0f669483bf7ddada784dd3002ce`. The generator changes fictional identifiers, amounts, payee names and signature placement on checksum-pinned public templates. The evaluator rendered and inspected the Thai amount, graphic consent, printed FEP assignment, and CMS FL47 and FL64 cells. All 52 PDFs were byte-identical between runs. The scorer checks the API response against the frozen assertions. [Gold manifest](../bench/payer_challenge_cases/gold.json) · [Field scoring](../bench/payer_challenge_cases/scoring.py)

The runner starts an isolated PostgreSQL database, exercises intake and retrieval over HTTP, attempts review and export, and grades the returned findings and checks. Four concurrent workers exercised the 14 local packets with cloud OCR disabled. The measured regression intake latency was 446 ms median and 2.02 s worst. These times include uploading and screening. They exclude fixture generation and human review.

The field readers had previously seen these form editions and related synthetic generators. The holdout tests new values, combinations and misleading evidence on those editions. The regression inputs became known when the two issues were fixed. Accuracy on unseen payer forms, handwriting and photographs needs a separate evaluation. Real insurer acceptance and payment remain unmeasured. [Thai form sources and limitations](thai-payer-forms.md) · [US form sources and limitations](us-payer-forms.md)

## Reproduce

Run the current application on the frozen cases from the repository root. The script fetches published blanks if the checksum-verified local cache is empty. The outputs under `.local` include the generated PDFs, preserved return values and score by field.

```bash
uv run --locked python bench/payer_challenge.py --workers 4
```

The live command exits successfully only when all 11 targets appear on their required form pages, all six values appear in both the form citations and finding messages, and the 45 aligned expectations produce zero false targeted alerts. Every one of the 14 cases must remain held with approval and export blocked, with all 52 original documents intact. An incomplete or duplicated case set is rejected. Inspect `scored.json` for the case and field behind a failure.

To rescore saved regression observations without re-uploading the PDFs:

```bash
uv run --locked python bench/payer_challenge.py --score-observed bench/payer_challenge_cases/retest-observations.json --require-current --out .local/holdout-retest
```
