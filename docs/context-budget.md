# Does the entire policy fit in Astra?

**Yes for the editions tested.** On 21 November 2026, OpenAI's Responses input-token counter measured **119,372 input tokens** for a coordinator request containing all 168 physical pages of the 2026 US policy as text, the five-page synthetic case, instructions and a question. Supplying the original policy PDF alone at high detail took **373,397 tokens**. Both fit. Only the PDF crossed Astra’s long-context pricing threshold. [Token-count endpoint](https://developers.openai.com/api/reference/resources/responses/subresources/input_tokens/methods/count) · [Astra limits and pricing](https://developers.openai.com/api/docs/models/gpt-6.2-astra)

| Input sent to the counter | Physical pages | Measured input tokens | Astra pricing tier |
| --- | ---: | ---: | --- |
| US policy PDF alone, inline file with high detail | 168 | 373,397 | Long |
| US policy alone, compact JSON with page numbers and native text | 168 | 118,488 | Short |
| Same US policy text, synthetic US case text, instructions and question | 168 + 5 | 119,372 | Short |
| Cached Thai policy text, synthetic Thai case text, instructions and question | 42 + 5 | 36,181 | Short |

The US source is the OPM-hosted Blue Cross and Blue Shield Service Benefit Plan brochure. OpenAI processes PDF input with extracted text and rendered page images. Supplying this PDF instead of numbered native text added 254,909 input tokens. The Thai policy text came from 41 Astra-transcribed pages and one native page. The synthetic cases illustrate request size only. Their named policies differ from the public editions used for this experiment. [US policy](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/71-005.pdf) · [Thai policy](https://www.allianz.co.th/content/dam/onemarketing/azay/allianz-co-th/document-download/forms/Allianz-Policy-Superior-Health-Plus-TH.pdf) · [PDF handling](https://developers.openai.com/api/docs/guides/file-inputs)

## Input, output and price

The complex CLI uses the Responses API with `OPENAI_OCR_MODEL` defaulting to `gpt-6.2-astra` for OCR and drafting. The original fixture reader uses `OPENAI_MODEL`, defaulting to `gpt-6.2-sol`. This experiment counted Astra inputs. Its published limits are **1,050,000 tokens of combined context, 922,000 maximum input and 128,000 maximum output**. A generation request must fit both the input cap and the combined context, with room for reasoning and visible output. For example, a 4,096-token output allowance on the measured 119,372-token request gives a budget of 123,468 tokens. Unused output allowance represents capacity. The counting endpoint generates no answer and reports input tokens only. Additional tools, schemas, messages or exhibits require counting the revised request. [Astra model card](https://developers.openai.com/api/docs/models/gpt-6.2-astra) · [Token counting guide](https://developers.openai.com/api/docs/guides/token-counting)

At Standard pricing Astra lists USD 8 per million ordinary input tokens and USD 40 per million output tokens for short requests. Once input **exceeds 272,000 tokens**, input and cache rates double and the output rate rises to 1.5 times the short rate for the **whole request**. For example, the 119,372-token text request would cost about USD 0.955 in ordinary uncached input charges before any output, assuming no cache writes. The counter provides no invoice or generation-cost measurement. [Astra pricing](https://developers.openai.com/api/docs/models/gpt-6.2-astra)

## Reproduction and interpretation

Save the public US PDF to the Git-ignored path documented in the [source register](document-research.md). The script checks the published copy's recorded SHA-256 and the physical page count. With both public policies prepared, run the command below. Omit the final option to count only the US representations. The optional Thai arm reads the existing accepted page checkpoints and makes no new OCR requests. [Benchmark source and exact request construction](../bench/context_budget.py)

```sh
uv run --locked --env-file .env python bench/context_budget.py --include-thai
```

Every count used the same Astra model and disabled truncation. The two review requests had no response schema or tool definitions. These measurements establish how the inputs fit and which input price tier applies. They leave answer accuracy, evidence completeness and generation latency on the 168-page case unmeasured. A separate evaluation compares full-context and retrieval answers on shorter synthetic policies. [Measured synthetic comparison](context-comparison.md)
