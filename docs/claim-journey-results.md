# Synthetic claim journey results

On 2026-11-21, **120/120 checks passed** against a Uvicorn HTTP server and an isolated PostgreSQL database. The cases combine synthetic hospital exhibits with fictional policies. The payer responses and hospital decisions are simulated. This run used digital processing and held unreadable scans for review with cloud OCR disabled.

Allianz lists the treatment details and estimated costs needed for preauthorization and separately describes patient shares, guarantees and settlement. Bangkok Hospital Phuket describes seeking an adjustment for changes in treatment or cost. CMS describes specific denial reasons for impacted US payers. These sources informed the scenarios. The fictional rulebooks supply their thresholds and exclusions. [Allianz preauthorization](https://www.allianzcare.com/en/support/healthcare-provider-resources/medical-provider-preauthorisation-process.html) · [Allianz direct settlement](https://www.allianzcare.com/en/healthcare-providers/direct-settlement-process.html) · [Bangkok Hospital Phuket](https://www.bangkokhospital.com/en/phuket/page/international-patient-services-bpk) · [CMS prior authorization](https://www.cms.gov/newsroom/fact-sheets/cms-interoperability-prior-authorization-final-rule-cms-0057-f)

| Scenario | Expected | Observed | Coordinator action |
| --- | --- | --- | --- |
| clean | ready_for_review | ready_for_review | Have staff review the source pages before sending. |
| wrong-member | HTTP 422 | HTTP 422 | Obtain the estimate issued for this member. |
| missing-member | needs_review | needs_review | Ask the provider to identify the member on the exhibit. |
| missing-member approval guard | 409 | 409 | Resolve the recorded findings first. |
| wrong-edition | HTTP 422 | HTTP 422 | Reconcile the edition on the estimate against the schedule. |
| missing-edition | needs_review | needs_review | Supply the applicable edition and check its effective dates. |
| missing-edition approval guard | 409 | 409 | Resolve the recorded findings first. |
| wrong-encounter | HTTP 422 | HTTP 422 | Return the other encounter's estimate and request the correct visit. |
| over-limit | needs_review | needs_review | Ask the payer to confirm excess charges or an exception. |
| over-limit approval guard | 409 | 409 | Resolve the recorded findings first. |
| possible-exclusion | possible_exclusion | possible_exclusion | Ask the payer about the documented cosmetic purpose. |
| possible-exclusion approval guard | 409 | 409 | Resolve the recorded findings first. |
| unknown-indication | needs_review | needs_review | Obtain the medical indication from the provider. |
| unknown-indication approval guard | 409 | 409 | Resolve the recorded findings first. |
| missing-estimate | needs_itemization | needs_itemization | Supply priced services and check their sum. |
| missing-estimate approval guard | 409 | 409 | Resolve the recorded findings first. |
| mixed-currency | needs_review | needs_review | Reconcile every amount in its stated currency. |
| mixed-currency approval guard | 409 | 409 | Resolve the recorded findings first. |
| unsupported-currency | needs_review | needs_review | Have staff verify the source currency and applicable limit. |
| unsupported-currency approval guard | 409 | 409 | Resolve the recorded findings first. |
| duplicate-total | needs_review | needs_review | Clarify which total is authoritative. |
| duplicate-total approval guard | 409 | 409 | Resolve the recorded findings first. |
| arithmetic-error | needs_review | needs_review | Obtain a corrected estimate whose service rows reconcile. |
| arithmetic-error approval guard | 409 | 409 | Resolve the recorded findings first. |
| unreadable-scan | needs_review | needs_review | Obtain a readable copy or opt in to OCR and verify the original. |
| unreadable-scan approval guard | 409 | 409 | Resolve the recorded findings first. |
| mixed-scan | needs_review | needs_review | Inspect the rendered page, including its image area. |
| mixed-scan approval guard | 409 | 409 | Resolve the recorded findings first. |
| unknown-policy | needs_review | needs_review | Cite the applicable wording and prepare a clarification request. |
| unknown-policy approval guard | 409 | 409 | Resolve the recorded findings first. |
| inactive-plan | needs_review | needs_review | Verify eligibility and effective status before proceeding. |
| inactive-plan approval guard | 409 | 409 | Resolve the recorded findings first. |
| outpatient | needs_review | needs_review | Obtain the policy and clinical plan for the applicable care setting. |
| outpatient approval guard | 409 | 409 | Resolve the recorded findings first. |
| conflicting-admission-date | HTTP 422 | HTTP 422 | Ask the provider to reconcile the two dates. |
| conflicting-procedure | HTTP 422 | HTTP 422 | Confirm which procedure and services this admission covers. |
| reissued-policy | needs_review | needs_review | Review the newly issued schedule and its exceptions. |
| reissued-policy approval guard | 409 | 409 | Resolve the recorded findings first. |
| embedded-rider | needs_review | needs_review | Inspect the attached rider before applying the base schedule. |
| embedded-rider approval guard | 409 | 409 | Resolve the recorded findings first. |
| form-field | needs_review | needs_review | Inspect the completed form fields before treating the estimate as verified. |
| form-field approval guard | 409 | 409 | Resolve the recorded findings first. |
| Worklist example missing-estimate | needs_itemization | needs_itemization | Inspect the timeline and original evidence. |
| Worklist example possible-exclusion | possible_exclusion | possible_exclusion | Inspect the timeline and original evidence. |
| Worklist example partial-guarantee | partial | partial | Inspect the timeline and original evidence. |
| Worklist example admission-mismatch | mismatch | mismatch | Inspect the timeline and original evidence. |
| Concurrent intake replay | 1 | 1 | Retry the unchanged packet with the same key. |
| Changed intake reuses a submitted key | 409 | 409 | Give the changed packet a new submission key. |
| Competing same-base replacements | [200, 412] | [200, 412] | Reload the active revision before submitting a competing revision. |
| Superseded itemization evidence | needs_itemization | needs_itemization | Open revision history to inspect the original. |
| Corrected estimate, unchanged total | ready_for_review | ready_for_review | Review the added priced service rows. |
| Stale approval | 412 | 412 | Review the current revision. |
| Submission before staff review | 409 | 409 | Approve the reviewed current revision first. |
| Approved but unsent | not_sent | not_sent | Record submission only after an external send. |
| Exported originals match the revision | True | True | Compare all three embedded PDFs to the review sources. |
| Reply before submission | 409 | 409 | Associate the response with an actually submitted revision. |
| Manual submission | submitted | submitted | Retain the actual transmission reference. |
| Duplicate stale submission | 409 | 409 | Reload the recorded timeline. |
| Unattached payer assertion | 422 | 422 | Attach the original letter and confirm its identity. |
| Information requested | query | query | Collect the requested exhibit. |
| Supplement attached to the query | supplement_sent | supplement_sent | Keep the response and original documents together. |
| Payer reply denied | denied | denied | Review the actual written decision and its limitations. |
| denied admission comparison | no_guarantee | no_guarantee | Check the letter, admitted encounter and amount. |
| denied creates no hospital waiver | None | None | Hospital finance records its deposit decision independently. |
| Payer reply authorized | authorized | authorized | Review the actual written decision and its limitations. |
| authorized admission comparison | no_guarantee | no_guarantee | Check the letter, admitted encounter and amount. |
| authorized creates no hospital waiver | None | None | Hospital finance records its deposit decision independently. |
| Payer reply partial | partial | partial | Review the actual written decision and its limitations. |
| partial admission comparison | mismatch | mismatch | Check the letter, admitted encounter and amount. |
| Partial guarantee leaves an amount above the ceiling | 22000 | 22000 | Confirm the remaining THB 22,000 and any deductible with finance. |
| Within a partial ceiling | partial_scope | partial_scope | Check the excluded services and patient-share terms. |
| partial creates no hospital waiver | None | None | Hospital finance records its deposit decision independently. |
| Payer reply guaranteed | guaranteed | guaranteed | Review the actual written decision and its limitations. |
| guaranteed admission comparison | matched | matched | Check the letter, admitted encounter and amount. |
| guaranteed creates no hospital waiver | None | None | Hospital finance records its deposit decision independently. |
| Expired letter | mismatch | mismatch | Seek an amended letter before relying on the previous terms. |
| Expired letter reason | True | True | Use this specific difference in the clarification. |
| Admission before effective date | mismatch | mismatch | Seek an amended letter before relying on the previous terms. |
| Admission before effective date reason | True | True | Use this specific difference in the clarification. |
| Different planned day | mismatch | mismatch | Seek an amended letter before relying on the previous terms. |
| Different planned day reason | True | True | Use this specific difference in the clarification. |
| Procedure changed | mismatch | mismatch | Seek an amended letter before relying on the previous terms. |
| Procedure changed reason | True | True | Use this specific difference in the clarification. |
| Facility changed | mismatch | mismatch | Seek an amended letter before relying on the previous terms. |
| Facility changed reason | True | True | Use this specific difference in the clarification. |
| Price exceeds ceiling | mismatch | mismatch | Seek an amended letter before relying on the previous terms. |
| Price exceeds ceiling reason | True | True | Use this specific difference in the clarification. |
| Currency changed | mismatch | mismatch | Seek an amended letter before relying on the previous terms. |
| Currency changed reason | True | True | Use this specific difference in the clarification. |
| Missing staff verification | needs_review | needs_review | A coordinator verifies the actual letter conditions. |
| Confirmed admission | matched | matched | Route to hospital finance for its independent decision. |
| Explicit hospital deposit waived | waived | waived | Explain the hospital's recorded decision and retain its rationale. |
| Explicit hospital deposit required | required | required | Explain the hospital's recorded decision and retain its rationale. |
| Letter omits member receipt | guaranteed | guaranteed | Keep the letter's actual contents and original document. |
| Letter omits member comparison | needs_review | needs_review | Ask the payer to clarify the missing or inconsistent term. |
| Letter omits member reason | True | True | Verify the specific member, patient-share or effective-date field. |
| Letter names another member receipt | guaranteed | guaranteed | Keep the letter's actual contents and original document. |
| Letter names another member comparison | mismatch | mismatch | Ask the payer to clarify the missing or inconsistent term. |
| Letter names another member reason | True | True | Verify the specific member, patient-share or effective-date field. |
| Letter omits patient share receipt | guaranteed | guaranteed | Keep the letter's actual contents and original document. |
| Letter omits patient share comparison | needs_review | needs_review | Ask the payer to clarify the missing or inconsistent term. |
| Letter omits patient share reason | True | True | Verify the specific member, patient-share or effective-date field. |
| Letter effective after admission receipt | guaranteed | guaranteed | Keep the letter's actual contents and original document. |
| Letter effective after admission comparison | mismatch | mismatch | Ask the payer to clarify the missing or inconsistent term. |
| Letter effective after admission reason | True | True | Verify the specific member, patient-share or effective-date field. |
| consent operational hold | 1 | 1 | Assign staff to obtain the missing evidence. |
| consent guards approval | 409 | 409 | Resolve the active hold before approval. |
| consent recorded release | 0 | 0 | Retain the staff resolution and audit trail. |
| eligibility operational hold | 1 | 1 | Assign staff to obtain the missing evidence. |
| eligibility guards approval | 409 | 409 | Resolve the active hold before approval. |
| eligibility recorded release | 0 | 0 | Retain the staff resolution and audit trail. |
| network operational hold | 1 | 1 | Assign staff to obtain the missing evidence. |
| network guards approval | 409 | 409 | Resolve the active hold before approval. |
| network recorded release | 0 | 0 | Retain the staff resolution and audit trail. |
| policy operational hold | 1 | 1 | Assign staff to obtain the missing evidence. |
| policy guards approval | 409 | 409 | Resolve the active hold before approval. |
| policy recorded release | 0 | 0 | Retain the staff resolution and audit trail. |
| timing operational hold | 1 | 1 | Assign staff to obtain the missing evidence. |
| timing guards approval | 409 | 409 | Resolve the active hold before approval. |
| timing recorded release | 0 | 0 | Retain the staff resolution and audit trail. |

## Reproduce

Run the checks with PostgreSQL's `initdb` and `pg_ctl` on PATH. To produce example PDFs for manual upload, add `--write-examples /path/to/new-directory`. Each folder includes the three exhibits and case metadata. The payer examples include their fictional letter.

```sh
uv run --locked python bench/claim_journey.py
```

The run measures application behavior on planned admission and financial confirmation. It does not measure population accuracy, insurer turnaround, human time saved, final claim payment or adjudication of real benefits.
