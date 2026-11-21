# Two-worker OCR on independent intake documents

On 21 November 2026, two workers finished a pair of one-page scans in **4.21–4.24 seconds**. Reading the same pair sequentially took **7.37–8.21 seconds**. All eight extractions preserved the key facts, the file SHA-256, physical page 1, the member and policy identifiers, and the OCR method.

| Pair | Run order | Sequential | Two workers | Speedup |
| --- | --- | ---: | ---: | ---: |
| 1 | Sequential, then two workers | 7.374 s | 4.242 s | 1.74× |
| 2 | Two workers, then sequential | 8.210 s | 4.210 s | 1.95× |
| Combined | Same number of pages per arm | 15.584 s | 8.452 s | 1.84× |

Each arm ran the existing Astra PDF extraction path on the same Git-versioned synthetic scans. The Z002 estimate showed THB 82,000 with no itemized charges. The Z003 plan retained the provider's exact statement of cosmetic purpose. Each pair reversed the preceding pair's document order. Timing covered local PDF reading, the API call, parsing and verification. No extraction output was cached locally. Astra reported 24,616 cached input tokens out of 25,288 input tokens and 823 output tokens. Reusing the same pages makes these warm-path timings. Two paired observations establish neither cold-start latency nor p95.

**Application implication.** Independent exhibits can be preprocessed concurrently. In a same-case workflow, each completed extraction would retain its own case, document revision, source digest and physical page. A coordinator's calculation would start only after the required exhibits for the selected case revision are present and their identifiers match. These scans came from two different synthetic cases. Packet joining, durable queues, network saturation and concurrent updates to a single case were outside this measurement.

The experiment used two workers per parallel arm, standard service tier and zero automatic retries. API limits apply across a project's requests and tokens. A deployed queue should bound total in-flight calls across cases, account for the project's token budget and retry a rate-limited document with backoff. Eight inferences returned eight verified outputs. Charging every input token at the published short-context 12-hour cache-write rate and every output token at the standard output rate gives a conservative **$0.539 ceiling** for this run. Actual billing depends on cache usage. [OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits) · [Astra pricing](https://developers.openai.com/api/docs/models/gpt-6.2-astra)

## Reproduce

Set a server-side `OPENAI_API_KEY` in the local `.env` and select `gpt-6.2-astra` for OCR. The benchmark verifies the two pinned file digests before starting. It makes at most eight page inferences, prints aggregate timing, counts and usage, and exits with an error if a required fact or source check fails.

```sh
uv run --locked --env-file .env python bench/parallel_intake.py
```
