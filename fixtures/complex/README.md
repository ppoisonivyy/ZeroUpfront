# Complex GOP cases

The two plans, facilities, members, riders and amounts are original synthetic teaching material. Use the public US and Thai references in the [research report](../../docs/document-research.md) to stress-test document handling. The fictional benefit calculations apply only to these authored plans.

| Pack | Read these together | Staff decision to demonstrate |
| --- | --- | --- |
| US-origin group certificate with overseas care | [Eight-page policy](us-policy.pdf) and [five-page case](us-case.pdf) | Distinguish accident admission from scheduled overseas care. The active M7 rider extends the notice window from 48 to 72 hours. The notice at 60 hours is timely. USD 220 × 35 THB gives a room cap of 7,700 per night. Excess on the first night is 1,300. The THB 62,000 implant line awaits a supplier schedule. The assistance desk acknowledged receipt. |
| Thai-origin Gold inpatient policy | [Eight-page policy](th-policy.pdf) and [five-page bilingual case](th-case.pdf) or its [scanned-sheet variant](th-case-mixed.pdf) | Compare R9 with expired circular R8. Net charges reconcile to THB 144,000. Room excess is THB 1,000 and the companion bed is 1,200. Draft request 141,800, subject to staff review. Paid-to-date remains unknown. Quarantine the unrelated HN. |

Read a case once using only the exhibits. Then compare it against [the expected answers and pages](expected.json). The mixed Thai PDF has the same business content as the digital copy; physical page 4 is image-only. Independently check the Thai line descriptions, currency and figures against the rendered page when evaluating Astra. The US case uses a synthetic exchange rate.

The editable UTF-8 sources are the four .txt files. To regenerate PDFs run `uv run --locked --group fixtures python fixtures/complex/build.py`. The development-only builder uses Chrome (set CHROME_BIN as needed), a Thai-capable font and pdftoppm to manufacture the scan. Application ingestion uses pypdf and Astra.
