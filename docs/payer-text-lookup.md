# Does exact document lookup improve the AI reader?

The PDF-only reader and the reader required to perform an exact-text lookup both answered **4/4 targeted fields correctly**, named the required values, and cited the physical pages that supported their conclusions. The lookup added a model request on every case. Median time rose from **8.50 to 12.94 seconds**. This experiment supports keeping the existing PDF-only staff reader for these four targets. It leaves open whether optional lookup would help on longer, unfamiliar forms. [Raw target observations, traces and scores](../bench/results/payer-text-lookup.json)

| Synthetic case | What the PDF-only reader cited | What changed with a compulsory lookup |
| --- | --- | --- |
| CMS insured ID, first packet | Bill p1 for TEST-MBI-0099 and the separate hospital invoice on bill p3 for TEST-MBI-0042 | Searched TEST-MBI-0042, received four matching pages and cited the same two pages |
| CMS insured ID, holdout packet | Bill p1 for HM0130891 and the invoice on bill p3 for HM0130871 | Searched HM0130871, received four matching pages and cited the same two pages |
| AIA English form with graphic consent | For the **admission number**, records p2 and summary p1 both showed AN-HO944 | Searched AN-HO944, received nine matching pages and cited the same two. The scored target was admission. The native-text search did not inspect the graphic mark |
| FEP assignment with an unrelated account | Kept the payee unknown. Records p1 names Banyan Reach Specialist Centre. The independent register on records p3 names Banyan Reach General Hospital under VX-5428. The letter on p1 specifies the requested encounter VX-5248 | Searched VX-5248 and found only the letter. Cited records p1, bill p1 rather than the independent register, and letter p1. The bill also bears the other encounter, VX-5428. Both answers named the two facilities and both encounter IDs |

Both arms used the same model, complete original PDF bytes, metadata, family rubric and strengthened staff instructions. We compared identical input hashes within each pair. The earlier evaluation had sometimes cited only the payer form for a cross-document comparison. The current staff instructions explicitly request the independent source. These four purposely selected packets include those earlier misses and an unrelated-encounter control. The eight new answers were scored exactly as the model returned them, before application validation or deterministic citation repair. [Earlier raw-answer audit](payer-model-fidelity.md)

In the lookup arm the model had to choose one literal query, once. The tool searched only the supplied packet's selectable PDF text, preserving case and normalizing whitespace. It returned document roles, physical page numbers and short nearby excerpts. Neither the model nor the tool received expected answers, expected source pages, findings from the form reader, or a list of preferred queries. The known intake metadata, including the registered identifier, was present in both arms. In the FEP case, a native-text hit on the letter could not establish the payment recipient. Both readers inspected counterevidence in the PDFs and left the result unresolved.

The PDF-only arm made **4 model requests** and used 32,429 input tokens, including 7,026 cached, and 1,382 output tokens. The lookup arm made **8 model requests** and used 66,935 input tokens, including 31,005 cached, and 1,483 output tokens. Up to four case/arm trials ran concurrently. Timings include the API round trips and tool action and exclude PDF preparation. There was one trial per arm per case, with no retries. These results measure neither population accuracy nor whether a model would voluntarily choose the tool on harder examples. [Experiment implementation](../bench/payer_text_lookup.py)

To repeat the experiment on a fresh output directory, first prepare the local public forms and fully synthetic cases using the US form, frozen holdout and confirmation harnesses. The live command sends those synthetic PDF packets to the configured OpenAI model and incurs usage.

```sh
uv run --locked python bench/us_payer_forms.py
uv run --locked python bench/payer_challenge.py --prepare-only
uv run --locked python bench/payer_confirmation.py
uv run --locked --env-file .env python bench/payer_text_lookup.py --live --out .local/payer-text-lookup-new
```
