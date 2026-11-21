# Performance baseline

Measured 21 November 2026 on an Apple M4 Max with 16 logical CPUs, macOS 27.2.1, CPython 3.12.9 and PostgreSQL 18.6. The local tests measure PDF checks and database queue bookkeeping separately. The hosted timings below measure real OCR, retrieval and drafting on synthetic packets. Browser interaction, upload, queue wait and final PDF rendering remain outside the measured path.

## PDF pre-check

Each run processed 400 packet revisions, evenly split across the four fixture scenarios. Each worker reopened the applicable one-page files, checked member/edition and policy text, extracted estimate/purpose evidence, applied the rule and asserted the expected outcome. Timing uses a monotonic clock. Results below are the medians of three warm, closed-loop runs. Service-time percentiles are per packet. Worker startup and the initial warm-up are excluded.

| Workers | Checks/s | Median latency | p95 latency | Throughput range |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 240.71 | 4.12 ms | 4.57 ms | 240.23–246.88/s |
| 4 | 917.77 | 4.24 ms | 4.73 ms | 900.24–922.14/s |

All 2,400 measured checks matched their expected result. Four processes achieved 3.81× the throughput on this small repeated PDF corpus. The operating-system file cache was warm. Longer documents, raster scans and deployments with fewer cores require separate measurements. Reproduce with three repetitions of:

```sh
uv run --locked python app/benchmark.py --workers 1 --cases-per-worker 400
uv run --locked python app/benchmark.py --workers 4 --cases-per-worker 100
```

## Historical local OCR baseline (replaced)

The former Poppler/Tesseract path was measured before switching to Astra. With one worker, six repetitions of each of the two OCR scenarios completed in 11.339 seconds (12 checks, 1.06 checks/s). Median latency was 0.944 seconds; p95 was 1.267 seconds. Each case renders and OCRs one or two pages, verifies the policy and checks the case. Both scans are clean, synthetic and English. These timings exclude the OpenAI API and exclude warm-up. With only 12 observations the nearest-rank p95 is the slowest observed check.

A subsequent live Astra run transcribed physical page 20 of the real Thai reference in 13.16 seconds. A complete synthetic Thai retrieval-and-draft run with one scanned page took 33.935 seconds. These are single observations on different inputs. See the [comparative research results](document-research.md).

## Hosted end-to-end preflight

Two measured runs of the managed Thai path took **20.180 and 21.580 seconds**, including transcription of a scanned statement page. Both produced a THB 141,800 draft from THB 144,000 net and THB 2,200 member responsibility. Two measured US digital runs took **17.642 and 18.382 seconds**. Both held the draft while the THB 62,000 implant charge awaited a supplier schedule. The second pair ran concurrently. All four outputs passed the page-quote and typed-amount verifier. The original short suite separately passed all six live scenarios. The sample is too small for a meaningful p95, and insurer turnaround and staff review require separate timing. [Managed retrieval and reproducible commands](../README.md#run-the-demo)

## Database queue

The script starts a disposable PostgreSQL cluster on a private Unix socket. Each client claims a pending job using a short transaction and SKIP LOCKED, then writes its result and marks the job done in a second transaction. A result key enforces uniqueness. Each run verifies 800 distinct completed jobs with matching results.

| Concurrent clients | Completed jobs | Average job cycle | Jobs/s |
| ---: | ---: | ---: | ---: |
| 1 | 800/800 | 0.123 ms | 8,125 |
| 4 | 800/800 | 0.180 ms | 22,231 |

One short run per setting, zero failures. Client and database ran on the same machine with default durability settings. These numbers measure queue bookkeeping alone. They cannot be multiplied by the PDF rate or used as a hospital capacity estimate. Run with PostgreSQL utilities available on PATH:

```sh
bash bench/postgres.sh
```

## Measure the real demo

1. Enter a key in the root .env. Run the following command to evaluate six synthetic scenarios with live PDF extraction. Each line shows elapsed case-check time, THB amount, status and blocking clause. The long-document RAG path has a separate live observation above.

   ```sh
   uv run --locked --env-file .env python app/check_fixtures.py --live
   ```

2. Once the UI and Writer exist, time from upload acceptance until the downloadable draft and verified gap report are available. Count staff review time separately. Use the brief's **under 120 seconds** as the initial target. Record p50/p95, error rate, tokens, cost, pages, worker count, provider rate limits and queue wait. A single six-case run can catch a regression but gives a weak estimate of tail latency.
3. Repeat on unmodified and corrected packets, short digital PDFs and longer scanned ones. Test increasing arrival rates with the same file mix. Exercise timeouts, worker restart, repeated submission and stale revision completion. Compare outcomes and citation correctness as well as speed. Add workers when queue delay rises; if provider throttling drives the tail, cap concurrency or reduce repeated model input first. [k6 thresholds](https://grafana.com/docs/k6/latest/using-k6/thresholds/) · [OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits)

The final live default supplied the whole eight-page synthetic edition. The Thai mixed case reached the verified THB 141,800 staff draft in **21.548 s**; the US digital case returned insufficient evidence with THB 62,000 pending in **18.560 s**. These individual runs include case processing, model generation and quote verification. [Source selection and preprocessing benchmarks](benchmark-comparison.md)
