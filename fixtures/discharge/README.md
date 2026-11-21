# Discharge claim examples

The four baseline PDFs follow one fictional inpatient encounter from preauthorization to discharge. Every original has two physical pages and repeats its document, member, facility and encounter references. The 19 labeled scenarios in [expected.json](expected.json) reuse the unaffected exhibits and substitute a single altered document or omit a required exhibit.

The bill lists four charges totalling THB 89,300 and a THB 1,800 credit for returned supplies. Its printed final total is THB 87,500. The original preauthorization states a THB 90,000 ceiling on billed charges and a THB 5,000 fixed patient share. These figures have different meanings. The payer's final decision and payable amount remain open in all 19 scenarios.

| Review exercise | Scenarios |
| --- | --- |
| Review an aligned packet | `aligned` |
| Reconcile charges, credits and currency | `duplicate_line`, `unit_mismatch`, `total_mismatch`, `orphan_credit`, `excess_credit`, `mixed_currency` |
| Compare the final bill with written terms | `over_cap`, `share_mismatch`, `unsupported_terms` |
| Verify member, encounter and treatment | `member_mismatch`, `encounter_mismatch`, `date_mismatch`, `unapproved_procedure`, `stay_extension` |
| Follow up with the hospital or payer | `late_reply`, `missing_support`, `missing_records`, `unreadable_summary` |

The late-reply example keeps the original issue date on the payer letter and changes the hospital's documented receipt date to after discharge. It requires a coordinator to confirm retrospective applicability. The unsupported-terms letter substitutes a percentage after deductible for the fixed share, which requires the actual benefit and deductible evidence.

Run the offline checks from the repository root.

```sh
uv run --locked python -m unittest discover -s tests -p test_discharge_claim.py -v
```

The tests reproduce the PDFs in a temporary directory and compare their bytes with the committed originals. To intentionally regenerate those originals after changing the fixture definitions, run `uv run --locked python fixtures/discharge/build.py`.

Automatic screening covers the explicit English field layout in these exhibits, unambiguous two-decimal THB, USD or EUR amounts, and one fixed-share, billed-charge-ceiling letter. Unfamiliar layouts or narrative, percentage benefits, payer-payment caps, unsourced services, mixed currencies and missing or unreadable material require staff review. The examples exercise accounting and document consistency. Clinical necessity, authenticity, actual entitlement, provider settlement and payment receipt require independent evidence.
