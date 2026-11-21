# Thailand inpatient claim form rehearsal

We used AIA Thailand’s public individual/group inpatient claim form in Thai and English. Both aligned packets reached the hospital review queue and both needed investigation. In the digital-only run, the app held four packets with deliberately altered form entries but gave staff the same explanation it gave for their aligned counterparts. It correctly identified a fifth defect, a missing patient-specific payer letter. All seven cases left the payable amount blank.

## What the sample represents

AIA publishes both PDFs in its form library. The Thai download has three physical pages, including a transmittal cover. The English download has two. Both include the insured’s consent, a physician admission section, and a separate medical certification covering the diagnosis, operation, admission and discharge. The form says that the claimant may have advanced expenses or may be claiming them through the hospital. This matters when a reviewer sees an amount on the form. It cannot establish how much the patient owes or how much the payer will pay. The printed edition is May 2023. The files and links were checked on November 21, 2026. [AIA Thailand form library](https://www.aia.co.th/th/help-support/form-library) · [Thai IPD form](https://www.aia.co.th/content/dam/th-wise/images/th/help---support/si-141_form_library/%E0%B9%83%E0%B8%9A%E0%B8%99%E0%B8%B3%E0%B8%AA%E0%B9%88%E0%B8%87%E0%B9%80%E0%B8%AD%E0%B8%81%E0%B8%AA%E0%B8%B2%E0%B8%A3%E0%B8%A3%E0%B9%89%E0%B8%AD%E0%B8%87%E0%B9%80%E0%B8%A3%E0%B8%B5%E0%B8%A2%E0%B8%99%E0%B8%AA%E0%B8%B4%E0%B8%99%E0%B9%84%E0%B8%AB%E0%B8%A1%E0%B8%97%E0%B8%B1%E0%B9%88%E0%B8%A7%E0%B9%84%E0%B8%9B.pdf.coredownload.inline.pdf) · [English IPD form](https://www.aia.co.th/content/dam/th-wise/images/th/help---support/si-141_form_library/ipd-en.pdf.coredownload.inline.pdf)

The fictional patient, Mali Example, fell on November 2. Imaging showed a displaced left distal radius fracture. The patient underwent fixation on November 3 and went home on November 4. The packet includes the consult time, two patient identifiers, injury narrative, examination, radiography, fixation, postoperative course, planned review, and separate simulated patient and clinician marks. Thai free text appears on the Thai edition. Optional or inapplicable fields are left blank. The marks and identifiers are test-only. An aligned case is eligible for coordinator review under our gold criteria. Only the insurer can determine whether a genuine case is payable.

Ward and nursing charges were THB 13,000, theatre 24,000, implants 18,800, professional fees 21,400, radiographs 5,700, and pharmacy and supplies 5,800. The THB 1,200 supply credit brings the bill to **THB 87,500**. A separate synthetic preauthorization gives a THB 90,000 ceiling and a THB 5,000 fixed patient share. We placed the real completed form first in the supporting-records PDF, followed by a two-page service and credit log. Bill, summary and authorization each have two pages. Hospital descriptions of inpatient direct billing independently support testing the discharge summary, expense packet and payer response together. The exact required evidence depends on the hospital, contract and insurer. [Bumrungrad Hospital discharge and insurance process](https://www.bumrungrad.com/en/blog-news/insurance-payment-process) · [Viriyah inpatient claim process](https://vinsure.viriyah.co.th/claiminfo/ipd)

## Digital-only results

Seven independent cases ran through multipart HTTP intake on a disposable PostgreSQL database with four workers. Every uploaded PDF downloaded byte-for-byte with the expected SHA-256. Each case returned HTTP 201 and a review hold. Each attempted approval, export and submission returned HTTP 409.

| Case | What a coordinator should see | Observed |
| --- | --- | --- |
| Aligned Thai edition | Ready for human review | Held. The three payer pages were flagged unreadable and the annex was flagged for pagination. |
| Aligned English edition | Ready for human review | Held. The two payer pages and separately paginated annex produced the same categories. |
| Thai, incorrect admission number | Part B page 3 says AN-QA999. The encounter is AN-QA042. | Same findings as the aligned Thai packet. No admission-number discrepancy identified. |
| English, missing patient consent | The simulated patient mark and date are absent on Part A page 1. | Same findings as the aligned English packet. No consent action identified. |
| Thai, missing physician certification | Part B page 3 lacks the clinician mark. Part A still identifies the clinician. | Same findings as the aligned Thai packet. No certification action identified. |
| Thai, wrong amount claimed | The patient section on page 2 gives THB 92,750 against a THB 87,500 final bill. | Same findings as the aligned Thai packet. No THB 5,250 discrepancy identified. |
| English, absent authorization | The AIA claim form is attached. The patient-specific payer letter is absent. | Missing letter explicitly identified. The case remained unpaid. |

On these seven selected scenarios, the digital-only run held **5/5** packets with defects and unnecessarily held **2/2** aligned packets for the tested screening target. It identified the intended reason in **1/5** defective packets. This small paired experiment measures these specific checks. It does not estimate field accuracy across the Thai insurance market.

The app routes pages containing graphics through its visual-reading path, even when the text is selectable. With cloud OCR disabled, all carrier-form pages were withheld from the text check. Its internal record parser also expects a single consecutive page sequence. Legitimate exhibit pagination in the two-document bundle produced a page-order warning. These are distinct problems.

## What changed with live OpenAI OCR

The same seven synthetic packets ran again with four workers on the configured `gpt-6.2-astra` OCR endpoint. The app accepted all **18 carrier-page transcripts** as complete. Each probe tested the presence or absence of a specific literal on its physical page. We checked the policy number, amount, patient mark, admission number, hospital number and physician mark, plus a Thai injury phrase where applicable. **42 of 46 probes** matched their expected result. This is an exact-text spot check, not a signature or full-transcript accuracy test.

| Live case | Page-bound probes matched | Actionable result |
| --- | ---: | --- |
| Aligned Thai and English forms | 7/7 and 6/6 | Both still held for form layout and page identity. |
| Thai wrong admission number | 7/7 | OCR returned the wrong AN-QA999 as printed. The app did not flag its mismatch with the case. |
| English missing patient consent | 6/6 | The patient mark was absent from the transcript as expected. The app did not ask for it. |
| Thai missing physician certification | 3/7 | The absent clinician mark was correctly absent on page 3. No specific certification finding appeared. Page 2 also lacked exact matches for the member, amount, consent marker and Thai injury phrase even though OCR marked the page complete. |
| Thai wrong amount claimed | 7/7 | OCR returned 92,750.00 on page 2. The app did not reconcile that value against the bill. |
| English missing authorization | 6/6 | The app again named the missing payer letter. |

All seven live cases remained held. All 21 attempted approvals, exports and submissions returned HTTP 409. The median intake request took **48.2 seconds** with cloud OCR (31.9–61.7 seconds), compared with approximately **1.0 second** digital-only. Timings are single requests per case on this machine and include local HTTP upload and screening. The experiment shows why fixing OCR alone cannot clear these cases. The reviewer needs each populated form value mapped to its field, physical page and invoice or encounter comparison. [Measured results by case](../bench/payer_forms_th/observed.json)

## Revision, attachments and settlement

Re-uploading a corrected Thai form on the same case created revision 2. Both the erroneous and corrected PDFs remained retrievable under different digests. Approval against stale revision 1 returned HTTP 412. The corrected form still produced a review hold.

In a separate transport probe, the prior implementation returned HTTP 201 and marked four aligned exhibits ready when a fifth file arrived under the unknown field `payer_form`. That extra file disappeared from the saved originals. The revised API returned HTTP 422 and named the accepted file fields. A dedicated payer-form slot remains a product gap. [Attachment handling change](https://github.com/aowngong/ZeroUpfront/commit/ad36ccd)

A separate positive control used the same synthetic encounter, six service lines and credit in the app’s supported exhibit format. It reached staff review, approval, export with all four byte-identical attachments, and a local simulated submission. A simulated payer asked for the credit evidence and later confirmed THB 80,000. Settlement stayed unpaid until the two simulated receipts of THB 50,000 and 30,000 brought it through partially paid to paid. This exercises the downstream state transitions. **Neither completed AIA edition reached staff approval in this rehearsal**, and no information went to the insurer.

## Reproduce locally

```sh
uv run --locked python bench/thai_payer_forms.py
uv run --locked --env-file .env python bench/thai_payer_forms.py --live --workers 4
```

The script downloads the two official blank forms and validates their pinned SHA-256 before overlaying clearly marked test data. Processing multiple scenarios does not mutate the pinned originals. Local files stay under `.local/th-payer/`. Use `cases/th-aligned/metadata.json` with its four role-named PDFs to reproduce the intake. The standalone form is `cases/th-aligned/aia-form-only.pdf`. The positive control’s reviewed export is `cases/supported-control/reviewed-discharge.pdf`. Replace the supporting-records PDF with `cases/th-wrong-admission/records.pdf` to compare the admission number. The two machine-readable result files are `results.json` and `live.json`. Using `--live --live-cases th-aligned` limits the paid OCR run to one case and writes a separate subset report.

The only external processing in live mode sends the public form pages with synthetic entries to the configured OpenAI OCR model. All payer replies, accounting entries, staff names and references are fabricated locally. No external submission, identity validation, signature authentication, payer adjudication or bank settlement is exercised.
