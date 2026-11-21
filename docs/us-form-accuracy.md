# What the US discharge form checks can identify

On November 21, 2026, the discharge API identified all six deliberately introduced discrepancies and the one valid change to member reimbursement in the original nine US examples. The earlier version gave the same explanation for every packet in each form family. Both versions held all nine packets for staff review and left the payable amount blank. The improvement is the finding a coordinator can act on, with a link to the original physical page. [Original benchmark and form sources](us-payer-forms.md)

| Form and change | Action in the retest |
| --- | --- |
| CMS-1450 FL 60A, different insured identifier | Shows the primary payer's printed identifier and the encounter identifier. |
| CMS-1450 FL 17, transfer on the form and home in the discharge summary | Gives the meaning of the printed disposition code and cites the relevant form and discharge summary pages. |
| CMS-1450 FL 4/64A, Medicare replacement without the original claim reference | Asks for the prior document control number on the applicable primary-payer row. |
| CMS-1450 FL 47, USD 11,785 against a USD 11,285 itemized invoice | Shows the two amounts and cites both printed amount cells and the independent invoice total. |
| FEP section 4, THB 160,000 against a THB 158,050 invoice | Gives the currency, both amounts and both source pages. |
| FEP section 5D has a named hospital and a blank assignment signature, with a signed general claim | Asks the coordinator to inspect the section 5D mark or obtain the assignment. |
| FEP sections 5A and 5B select a member check | Records the selected member reimbursement route as a fact with its source. It creates no payee discrepancy. |

The two original comparison packets had no targeted discrepancy. The overseas comparison also recorded the presence of provider assignment text for staff verification. The existing manual review still required staff to inspect the rest of each packet. Both original same-case corrections kept their history and reached revision 2. Approval, export, submission, query, decision and payment each returned HTTP 409 on the unresolved real-form packets. The separate supported-format control completed the simulated settlement flow.

## Independent variants

We created a new encounter and a 27-case regression set with different identifiers, providers, currencies, document ordering and fractional amounts. All 27 returned the expected targeted findings, routing facts or requests for manual review over the normal multipart API with four parallel workers. Every case remained held and every attempted approval returned 409. The same 27 expectations also passed against compact locally authored test canvases and the publisher specimens. These examples were designed against the implementation requirements. Performance on unseen hospitals, documents or insurers remains unmeasured. [Test cases and expected actions](../tests/test_payer_us.py)

- A one-cent difference between 7,020.63 and 7,020.64 produced the correct discrepancy on each form. The CMS citation includes the two printed cells on the form's second physical page and the stated total on the third. The FEP example used EUR. A USD claim beside an EUR invoice called for verification of currency conversion.
- A present Medicare reference suppressed the missing-reference finding. Home with hospice was left outside the supported home/self-care comparison. A different member or an invoice with a different encounter withheld the associated external comparison. Multiple independent totals and a page giving only an estimated total each prompted manual verification.
- A separate holdout initially returned only a general payee review when a signed FEP assignment named another institution. We added a neutral question about the intended recipient. Tests with two new recipient names, Rainier Hospital Escrow and Summit Physician Partners, each cited the named recipient and the treating facility on the independent summary. A case-insensitive match to Twin Fir Clinic recorded the provider-assignment text for verification. An alternative institution may be the intended recipient.
- A general claim signature and a section 5D signature were evaluated separately. A blank, a placeholder, two conflicting payment choices, a check combined with an assignment, and an assignment alongside bank details each produced the relevant action. Additional graphic ink, a rotated page and two candidate form copies produced manual-review findings.

## Affirmative checks on aligned evidence

A subsequent version records the original insured ID and home/transfer disposition as corroborated only when an independent hospital record for that encounter agrees. It cites both physical pages. A matching stated total now cites the separate invoice as well as the amount on the form. The CMS amount cites both its dollars and its cents cells. Staff still have to reconcile the underlying service lines and credits.

For the supported Medicare payer row, the reader distinguishes an initial frequency-1 bill from an adjustment with a populated original reference. The latter records only that FL 64A contains the printed identifier. Verification against a payer acknowledgement remains a staff action. A blank or placeholder reference on an adjustment triggers review.

The affirmative-check retest preserved the first 27-case observations and added four controls. A packet without a separately labeled member ID withheld the member match. Competing explicit dispositions withheld the disposition match. A placeholder DCN prompted verification. An invoice with the same total printed twice withheld the one-to-one total comparison. Each control used an actual official background with a new fictional encounter. Both the CI canvases and publisher-paper runs passed all 31 expected combinations of findings and positive facts. A fresh four-worker multipart HTTP run matched those expectations on all 31, returned every supported original byte for byte and kept all 31 unapproved with a blank payable amount.

## Scope of the checks

The supported layouts are the CMS-hosted two-sided CMS-1450 specimen and the FEP Overseas Medical Claim Form CUT0159-1S 08/23. The reader checks page dimensions, original printed labels, fixed regions and the artwork of the publisher's front page before interpreting native text. It abstains on changed artwork, rotated/cropped fronts, interactive widgets and graphic marks it cannot interpret. The FEP reader can use typed text over the publisher logo. A visible signature field containing text still needs staff authentication. Generic review remains available for scans and newer editions. [CMS institutional claim guide](https://www.cms.gov/medicare/billing/electronicbillingeditrans/1450) · [FEP form and instructions](https://www.fepblue.org/-/media/PDFs/Forms/2024/Overseas-Medical-Claim-Form---GeoBlue-06082023.pdf)

The CMS reader currently cross-checks the primary payer row, disposition codes 01 and 02, and the specific Medicare replacement/cancellation reference requirement. Its amount check compares the stated final total with a separately identified itemized invoice in the same encounter. Field recognition does not validate every line item, benefit rule, diagnostic code, signature, exchange rate or payer requirement. Facility and member comparisons rely on identifiable source text. Physical pages, quotes, both cited amounts and the original files remain available for review. [CMS discharge status definitions](https://bluebutton.cms.gov/resources/variables/ptnt_dschrg_stus_cd/) · [CMS document control number](https://www.cms.gov/outreach-and-education/mln/wbt/mln7388180-mln-wbt-1450/1450/lesson05/20/index.html) · [Screening implementation](../app/payer_us.py)

## Reproduce

The first command downloads the hash-pinned public forms and uses disposable PostgreSQL. The second runs the independent regression set on the published editions and the smaller CI canvases. These checks use local digital PDFs and require no model key.

```sh
uv run --locked python bench/us_payer_forms.py --output .local/us-payer/us-after-form-screening.json
uv run --locked python -m unittest discover -s tests -p 'test_payer_us.py' -v
```
