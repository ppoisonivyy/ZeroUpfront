# Synthetic GOP test packets

Choose the policy in the second column, then add the plan and estimate from the listed case directory. The nine original one-page PDFs are original, English-language, machine-readable demo documents. Each identifies its issuer, member or edition, and synthetic origin.

| Case | Policy | Documents from the case directory | Expected pre-check |
| --- | --- | --- | --- |
| Z001 | policies/alder.pdf | plan.pdf + estimate.pdf | THB 120,000. Required itemization is present. Ready for staff review. |
| Z002 | policies/alder.pdf | plan.pdf + estimate.pdf | THB 82,000. The total alone fails AT-2 on page 1. Request itemization. |
| Z002 revision | policies/alder.pdf | Same plan + revised-estimate.pdf | The itemized estimate replaces the original. Same total, blocker resolved. |
| Z003 | policies/mango.pdf | plan.pdf + estimate.pdf | THB 95,000. The documented purpose triggers possible exclusion MM-2 on page 1. Route to staff. |

The Gold labels live in [expected.json](expected.json), separately from the documents. Each run loads the selected policy edition and verifies clause wording against its PDF. The live field reader receives transcribed case evidence. Astra separately receives individual pages that require OCR, including the mixed policy page. Rules, expected amounts, answers and revision labels stay outside its prompt.

The local reader knows the exact layout of these demo forms. It tests packet wiring, threshold logic, matching citations and the correction loop. Live mode evaluates field extraction and adds the scan variants. Both use a deliberately narrow checker for these scenarios. Broader benefit calculations, concurrent findings and admission changes belong to the shared app.

From the repository root, run:

```sh
uv run --locked python app/check_fixtures.py
uv run --locked --group fixtures python fixtures/build.py
```

Rebuild only after intentional source changes. Update expected results independently and inspect the PDFs before accepting a changed baseline.

## Scanned inputs

Two more runs are defined in [expected-ocr.json](expected-ocr.json). The Z002 image-only estimate is paired with a mixed policy packet. The first page is digital, and the second contains a scanned policy sheet plus a selectable header. Its AT-2 flag must cite physical page 2 with OCR provenance. The Z003 image-only plan must trigger MM-2 in the digital policy on page 1. Each case is also available in its original digital form for parity checks.

Run `uv run --locked --group fixtures python fixtures/build_scans.py` after rebuilding the original PDFs to recreate these three derivatives. The extractor inspects every page independently. The fixture checker also verifies packet identity and the policy quote. It is an evaluation tool for the supplied rules and English layouts.

The [complex US and Thai packets](complex/README.md) are the main research and review demo. These smaller forms are retained for regression checks.
