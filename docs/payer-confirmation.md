# Prospective confirmation of US payees and cents

The first frozen holdout remains **10/11** for the requested field outcomes. Two changes followed: the FEP reader identifies a different named recipient when the encounter documents support the comparison, and the CMS reader cites the separate cents cell. On a newly frozen eight-packet panel, the current deterministic readers passed **5/5 payee outcomes and 3/3 amount comparisons** on their first run. Every target included a check against the original physical page. [Original holdout](payer-holdout.md) · [New frozen expectations](../bench/payer_confirmation_cases/gold.json) · [Observed findings and citations](../bench/payer_confirmation_cases/observed.json)

| New case | Expected decision | Observed evidence |
| --- | --- | --- |
| Similar provider names | Verify the intended recipient | FEP records p1 names **Cedar Spire Outpatient Centre**. The linked discharge summary p1 names **Cedar Spire Inpatient Hospital**. The finding cited each. |
| Matching assigned hospital | Identify provider assignment for staff verification | Records p1 names Ocean Fern Surgical Hospital. The expected provider check was present and no provider discrepancy was raised. |
| Member selects reimbursement by check | Route to member reimbursement | Records p1 contained the two member selections. A note on the instructions page named Maple Quay Community Hospital and did not change the route. |
| Different named provider, supporting files for another encounter | Refer facility comparison for verification | The form names Banyan Reach Specialist Centre. Intake names Banyan Reach General Hospital, but the supporting bundle identifies VX-5428 instead of VX-5248. The reader identified the paper payee and requested independent corroboration. |
| Simultaneous member and hospital selections | Refer the competing elections | FEP records p1 had a member check selection and a signed 5D assignment to Willow Inlet Day Hospital. The reader cited both sections and chose neither payee. |
| CMS discrepancy with a leading zero in cents | Flag USD 14,207.03 versus 14,207.30 | Bill p1 cited `14207` and `03`. Bill p3 cited USD 14,207.30. The neighboring FL48 cents cell contained `77`. |
| CMS aligned total beside an unrelated cents value | Confirm USD 18,219.00 matches the invoice | Bill p1 cited `18219` and `00`. Bill p3 cited USD 18,219.00. The neighboring FL48 cents cell contained `91`. |
| FEP transposed minor units | Flag THB 142,710.05 versus 142,710.50 | Records p1 cited the submitted amount. Bill p1 cited the independent invoice total. |

All **8/8** unverified cases remained on hold. Each returned a null payable, exposed no workflow actions, and returned HTTP 409 for approval and export. All **30/30** original PDFs were retrieved byte-for-byte. The field-specific checks produced no contradictory route or amount conclusion on this panel. Reimbursement elections express the requested route. The payer still controls settlement.

The evaluator froze the new names, identifiers, amounts, expected decisions and source requirements at **05:54:13 UTC on 21 November 2026**, before generating or submitting these packets. Manifest SHA-256 is `e3beb6c0ad0a47832d82f0d876ea29756ef7d0fc390011a9c803e01509989360`. The panel uses the checksum-pinned CMS-1450 and FEP overseas blanks with fictional overlays. The evaluator cross-checked returned values against the source pages and rendered the adjacent CMS cells and competing FEP elections. Four workers exercised a local PostgreSQL-backed HTTP application. The run used no cloud OCR or model calls and required no reader changes.

This panel tests the two fixes on new values and combinations within known form editions. It supplies eight additional observations, separate from the original blinded result. [Generator and grader](../bench/payer_confirmation.py) · [US source forms and usage](us-payer-forms.md)

```bash
uv run --locked python bench/payer_confirmation.py
```
