# Financial preflight

The executable checks the supplied synthetic exhibits with exact decimal arithmetic. It reads packet identity and source text, calculates fields, then compares them to the labels. The executable exits with a failing status if a financial packet is unsupported or any checked field differs. It runs without an API key.

```sh
uv run --locked python app/finance_eval.py
uv run --locked python -m unittest discover -s tests -p 'test_finance.py' -v
```

| Split | Billing packets | GOP packets | Financial and status fields matched | Medical-record-only packets |
| --- | ---: | ---: | ---: | ---: |
| Training | 5 | 5 | 70 / 70 | 4 |
| Held out | 3 | 2 | 36 / 36 | 2 |

For billing, the gate compares reported gross, discount and net, visible detail net, the difference between the reported and itemized net, cumulative payment, balance due and reconciliation state. It checks each line and subtotal. A THB 0 payment requires an identifiable receipt. Missing payment evidence preserves an unknown balance.

For GOP requests, the gate compares the estimate, excluded amount, excess over available benefit, provisional eligible amount, draft request amount and staff readiness state. It applies documented exclusions before the available-balance cap. A blank signature preserves the provisional amount and withholds the draft request. The held-out blank-signature packet has a THB 55,500 provisional amount and a null draft amount.

The fixture adapter recognizes the supplied Lotus and River teaching formats. Unknown clauses, currencies, encounter mismatches, malformed amounts and unexplained estimate discrepancies require staff review. A separate test changes the expected draft amount and checks that the evaluator detects it. The medical-record-only rows have no labeled financial fields. This benchmark covers post-extraction arithmetic and supported preconditions; it does not measure OCR, language-model interpretation, prose quality, insurer approval, or unreviewed real-world contracts. The detailed US and Thai RAG packets use different rules and remain a separate evaluation.
