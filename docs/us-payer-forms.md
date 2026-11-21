# US discharge rehearsal with genuine claim forms

On November 21, 2026, we uploaded nine fictional packets on two official US forms to the discharge API, using four parallel workers, Uvicorn and disposable PostgreSQL. Staff approval, reviewed export, submission, payer query, partial decision and payment each returned HTTP 409 on all nine. The app preserved every named exhibit byte for byte and left every payable amount blank. It failed to identify any of seven deliberately changed administrative facts. It also asked for itemization on all nine packets despite dated, itemized invoices.

## Which workflow each form represents

**US hospital billing Medicare.** We filled both sides of the CMS-hosted CMS-1450 / UB-04 specimen, then appended the detailed hospital account in the bill slot. The CMS listing is dated November 13, 2026. Medicare normally uses electronic institutional claims (837I), with limited exceptions for paper. CMS specifically advises against submitting a downloaded copy. The rehearsal covers the content and staff workflow. It sends no EDI transaction and exercises no payer acceptance edits. [CMS source package](https://www.cms.gov/regulations-and-guidance/legislation/paperworkreductionactof1995/pra-listing-items/cms-1450) · [CMS billing and paper submission guidance](https://www.cms.gov/medicare/billing/electronicbillingeditrans/1450) · [Medicare 837I guide](https://www.cms.gov/files/document/837i-form-cms-1450-mln006926.pdf)

**US FEP member hospitalized overseas.** We filled the Blue Cross and Blue Shield Federal Employee Program's two-page Overseas Medical Claim Form, edition CUT0159-1S 08/23. It accompanies the hospital's itemized bill and permits a signed assignment of benefits to a provider. It is a member claim. The plan separately describes a direct-billing arrangement negotiated with the overseas provider. A signed election designates a payee and provides no evidence of payer approval, final allowance or money received. The FAQ directs readers to section 5C for assignment. On the linked PDF, 5C holds bank details and **5D** holds the assignment. A reviewer needs the original page and form edition. [FEP form and instructions](https://www.fepblue.org/-/media/PDFs/Forms/2024/Overseas-Medical-Claim-Form---GeoBlue-06082023.pdf) · [FEP direct billing and assignment FAQ](https://www.fepblue.org/faqs/faq-overseas)

## Cases and observed findings

The CMS encounter is a three-night Massachusetts medical admission for pneumonia with five revenue lines totaling **USD 11,285**. It includes the populated institutional bill, itemized account, two-page discharge summary and source register. We supplied no case-specific payer letter. The app's rule requiring a letter in every case cannot establish whether this Medicare encounter actually requires one.

The overseas encounter is a three-night Bangkok admission for fixation of a wrist fracture. Its eight invoice rows include an implant, anesthesia, imaging and a THB 700 return credit, for **THB 158,050** net. We supplied the completed FEP form and the register together in the supporting records slot, a clinical summary, bill and fictional prior admission correspondence. The correspondence describes this simulated scenario only. Both encounters use invented people, provider identifiers and attestations. The comparison packets establish alignment of the selected fields. They have no payer validation, live identifiers or legal signatures.

| Packet | Fact available to the staff reviewer | What the app reported |
| --- | --- | --- |
| CMS comparison | Reconciliation gives USD 11,285 and the discharge note agrees with home disposition | Six generic findings including missing itemization and a missing payer letter. Bill total blank |
| CMS wrong member | FL 60 ends 0099. The admission record ends 0042 | Same findings. No member mismatch |
| CMS transfer conflict | FL 17 says 02, transfer to a short-term hospital. The summary says discharged home | Same findings. No disposition conflict |
| CMS replacement | Type of bill 0117 indicates replacement. FL 64 contains no prior claim control number | Same findings. No request for the original claim reference |
| CMS total | FL 47 shows USD 11,785 while the charge rows and invoice total USD 11,285 | Same findings. No USD 500 discrepancy |
| FEP assignment comparison | Section 5D names the hospital and contains a fictional assignment attestation | Seven generic findings including unreadable records and missing itemization. Bill total blank |
| FEP member reimbursement | Member selected reimbursement by check. Provider assignment is empty | Same findings. No change in payee or route |
| FEP unsigned assignment | Hospital is named. Provider-assignment signature is blank while the separate general claim signature is present | Same findings. No request for the assignment signature |
| FEP total | Section 4 states THB 160,000 while the itemized bill nets THB 158,050 | Same findings. No THB 1,950 discrepancy |

CMS defines frequency 7 as a replacement and instructs providers to supply the prior document control number on an adjustment. Its disposition codes distinguish home and interhospital transfer. These rules supply the independent expected findings. The denominator of seven counts distinct modifications, including the valid member payee election. A generic hold was scored independently from identification of the changed fact. Nine cases across two form families cannot establish claim denial rates, policy coverage accuracy or prevalence. [CMS bill frequency](https://bluebutton.cms.gov/resources/variables/clm_freq_cd/) · [CMS document control number](https://www.cms.gov/outreach-and-education/mln/wbt/mln7388180-mln-wbt-1450/1450/lesson05/20/index.html) · [CMS discharge codes](https://bluebutton.cms.gov/resources/variables/ptnt_dschrg_stus_cd/)

## Corrections, workflow and the lost attachment

We corrected the USD 500 discrepancy and supplied the missing FEP test assignment separately on their original cases. Both replacements produced revision 2. Revision 1 still returned its original bytes and revision 2 returned the corrected bytes. Both stayed held and all six downstream steps still returned 409. On each form family, the app had identical finding codes and messages across the comparison and changed packets.

A separate known-layout control began with a duplicate charge. We corrected it, retrieved the first revision and observed a 412 on stale approval. Staff approved revision 2 and the downloaded PDF contained the four exact originals. The local workflow then recorded submission, query, a THB 80,000 partial payer decision and two simulated remittances of THB 50,000 and THB 30,000. The duplicate remittance returned 409. The case ended paid against the mock decision. Every event was local. No one received money.

The original release at `b0de3ea` accepted an unsupported fifth file posted as `payer_form` alongside four clean template exhibits. This fifth file was the genuine FEP form populated for a *different* fictional encounter with a missing assignment signature. The API returned 201, staff approval and export returned 200, and the packet contained only the four template originals. The local workflow went all the way to paid. Posting the fifth file alongside an unchanged bill during replacement also returned 200, retaining revision 1. In the rerun at `ad36ccd`, **both requests returned 422** and named the supported roles. The existing case stayed at revision 1. The four-role restriction still requires a user to bundle related exhibits.

## Native extraction and cloud OCR

With cloud OCR off, the median time for the nine multipart intake requests was 174 ms, with a range of 122–534 ms at four concurrent workers on the development machine (`ad36ccd`). Each timing includes screening and persistence. Measurements exclude generating the PDFs, reading back the files, staff review and external processing. There was one measured request per scenario, so the timing describes this rehearsal only.

FEP's populated front page has 3,776 selectable characters and a logo image. Its reverse has a link annotation. The app treats pages containing an image as needing OCR and conservatively flags annotations. We explicitly enabled live OpenAI OCR for the signed and unsigned FEP counterparts in parallel. The first paired run completed in 14.64 and 14.58 seconds. Both returned 201 and a one-page transcript. The unreadable-records finding cleared, yet the app reported the same seven messages on both, including missing itemization. Each remained ineligible for OCR signoff because other findings remained open. Both approval attempts and all downstream actions returned 409. A second paired run took 14.75 seconds per request. In the returned transcripts, both contained the expected patient, provider and THB 158,050.00 total. The signed example contained two test attestations, while the unsigned one contained only the general claim attestation. The screen still produced identical findings. These four checks assess the selected fields only.

## Reproduce or rehearse in the workspace

Run from the repository root with `uv` and local PostgreSQL utilities (`initdb` and `pg_ctl`) available. The harness downloads and pins the two publisher originals by SHA-256 and builds fictional test packets locally. The published repository contains the generator and findings. Downloaded forms, filled copies, and local JSON output live under the ignored `.local/us-payer/` directory.

```sh
uv run --locked python bench/us_payer_forms.py
uv run --locked --env-file .env python bench/us_payer_forms.py --live-fep-ocr
```

To inspect the same data by hand, open `.local/us-payer/packets/cms_total/` or `.local/us-payer/packets/fep_unsigned/`. Each folder includes the intake values and the role-named PDFs to upload. Use the corresponding files from `cms_aligned` or `fep_assigned` to rehearse corrections on the same case. `--server-root PATH` runs the API from a checkout of the original release, while using the current benchmark and identical documents. `--output PATH` saves separate observations. [Benchmark and independent expectations](../bench/us_payer_forms.py) · [Fictional specimen generator and publisher fingerprints](../bench/payer_forms_us/specimens.py)
