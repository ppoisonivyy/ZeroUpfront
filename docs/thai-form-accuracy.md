# AIA Thailand inpatient screening after field mapping

The discharge app identified the specific reason for **5 of 5 defective packets**, up from **1 of 5** on the same seven test cases. Neither aligned packet acquired a field discrepancy. Both still required staff review. The Thai and English editions each represent one synthetic encounter on an actual AIA form. This result supports a targeted regression check for these layouts. It does not estimate the probability of clearing a new hospital’s claim. [Historic results](../bench/payer_forms_th/observed.json) · [AIA Thailand form library](https://www.aia.co.th/th/help-support/form-library)

| Packet | Current finding and evidence |
| --- | --- |
| Thai aligned | Admission number and THB amount agree with the independent bill. Part A on records page 2 and Part B on page 3 require a person to verify the signature marks. |
| English aligned | The same two comparisons pass. A reviewer verifies the signatures on records pages 1 and 2. |
| Thai wrong admission number | Records page 3 states `AN-QA999`. Bill page 1 identifies `AN-QA042`. The app cites both and requests reconciliation. |
| English missing patient consent | The app identifies the empty insured signature field and cites the printed label on records page 1. |
| Thai missing physician certification | Part A names the physician. The app correctly identifies the separate empty certification field on records page 3. |
| Thai inconsistent amount | Records page 2 gives THB 92,750.00 and bill page 1 gives THB 87,500.00. The issue cites both and asks whether the difference represents a partial claim or needs correction. |
| English missing letter | The app requests the missing payer letter. The attached IPD form does not authorize payment. |

All seven multipart uploads returned HTTP 201. The API preserved every uploaded original byte-for-byte. All 21 approval, export and submission attempts on held packets returned HTTP 409. Replacing the erroneous Thai admission form on the same case removed the specific discrepancy and added the matching admission-number check to revision 2. Both originals were recoverable and stale approval returned HTTP 412. The separate internal-format control reached simulated settlement.

With four concurrent workers, median intake time was **2.08 seconds** versus **1.01 seconds** in the original digital-only run. The new runs include scoped form parsing plus the original screening. There is one timing per case on a local machine. Both runs omit network OCR, actual payer response time and staff review. [Original digital and cloud comparison](thai-payer-forms.md)

## What the field reader can establish

The reader locates a single Part A and its adjacent Part B in the original records PDF. It verifies their printed May 2023 layouts before reading the filled field rectangles. It compares native digital entries with a separately uploaded, encounter-, member- and facility-matched final bill. The amount on Part A can describe expenses advanced or claimed through the hospital. Staff must resolve significant differences, including a legitimately partial submission, before drawing a financial conclusion. [Official English AIA form](https://www.aia.co.th/content/dam/th-wise/images/th/help---support/si-141_form_library/ipd-en.pdf.coredownload.inline.pdf)

Typed, drawn and authenticated signatures have different evidentiary value. The reader always asks a person to inspect the original for execution and signer authority. A new graphic or annotation makes a blank digital field inconclusive. Ambiguous values, another edition, changed page geometry, multiple certificates, unrecognized bills and image-only copies stay in review. A rescanned or re-exported document may look identical while lacking the verified drawing and text structure. The existing layout and pagination holds still prevent either aligned real form from automatically advancing.

## Reproduce

```sh
uv run --locked python -m unittest discover -s tests -p test_payer_aia.py
uv run --locked python bench/thai_payer_forms.py
```

The seven-case run uses the original gold labels and the current public multipart endpoints. Its generated local report is `.local/th-payer/results.json`. The checked-in historical observations stay available for comparison. Six independent regression tests use different identifiers, amounts with cents, adjacent date/license text, graphical marks, ambiguous repeats and changed layouts. The retest recorded here used no paid OCR calls and sent nothing to a payer.
