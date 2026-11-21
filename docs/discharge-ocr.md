# Live OCR on a discharge summary

On 21 November 2026, the discharge API recovered the exact procedure, the admission and discharge dates, and signed-final status from a two-page image-only copy of the fictional summary. The two live Astra page calls and the complete HTTP request took **12.228 seconds** in the first comparison. The resulting packet required staff to check the transcribed pages. Each variant returned HTTP 201 with the payer's payable amount left blank.

| Input to the same discharge endpoint | Request time | Exact summary evidence recovered | Outcome |
| --- | ---: | --- | --- |
| Original digital summary | 0.021 s | Procedure, admission and discharge dates on page 1. Signed-final status on page 2. | Ready for staff review |
| Both pages rasterized, cloud OCR off | 0.017 s | Neither page had selectable text. | Staff review, pages 1 and 2 unreadable |
| Same two images, live `gpt-6.2-astra` | 12.228 s | All four values on their original physical pages, each tagged as OCR | Staff must verify the OCR |
| Digital page 1, physically blank page 2, OCR enabled after the blank-page fix | 0.016 s | All three page 1 values retained. Page 2 signoff unavailable. | Staff review with page 2 identified as unreadable |

The procedure was *Wrist fracture fixation*. The admission and discharge dates were 11 and 13 December 2026. The benchmark compared the exact published strings, including their field labels, to the returned source anchors. The source download matched the uploaded summary bytes in each case.

## From the OCR finding to a reviewed submission

In a subsequent live end-to-end run, the two-page raster took **10.684 seconds** to reach the OCR verification finding. The benchmark opened the revision-specific verification view and compared each complete transcript to the known digital original, allowing only whitespace differences. Both pages matched. Two explicitly named synthetic test actors then exercised the separate verification and approval steps. This was an automated rehearsal using known text.

Confirming both physical pages created revision 2, ready for staff review. The export endpoint still rejected a download before ordinary approval. After approval, the API returned HTTP 200 with two visible pages, the original four PDFs and the exact image-only summary. The second page recorded the scan reviewer, source revision, physical page numbers and SHA-256 digests of the file and each transcript. The payer's payable amount remained blank.

A coordinator can use this transition only when verification of complete OCR pages is the sole open finding. The API replays the saved text against the same original bytes and repeats the document checks. A missing page confirmation, altered transcript, different file, substantive billing gap or superseded revision prevents clearance. Cases with a missing signoff or unreadable page still need new evidence.

A separate early run exposed an issue with a structurally blank PDF page. Astra took 26.227 seconds on a packet with one digital page and an empty page. The reader rejected the resulting wording through its document checks, but the response lacked a specifically numbered unreadable-page finding. The revised reader detects a physically empty page before making an OCR call. A second complete run verified all four OCR anchors again and retained the valid page while flagging the empty page. Unit tests also simulate partial and unreadable model responses. Both preserve other pages, withhold the uncertain text and identify the physical page. Provider authentication, quota, throttling and availability failures follow the service-error path.

The test sends only synthetic summary pages to the configured OpenAI project. The original bill, preauthorization letter and supporting records stay digital. The harness starts a local Uvicorn server and disposable PostgreSQL cluster, creates each case through multipart `POST /api/discharge`, then removes the database. Timing starts immediately before upload and stops after the HTTP response. It includes PDF processing, network/provider time and persistence. It excludes server startup and preparation of the 180-DPI grayscale images.

Run from the repository root with PostgreSQL's `initdb` and `pg_ctl`, Poppler's `pdftoppm` and a project key in the local `.env`. Poppler only renders the synthetic input into pixels. Astra performs the transcription.

```sh
uv run --locked --env-file .env python bench/discharge_ocr.py --live
```

Omit `--live` for the two offline controls. This experiment covers one clean, machine-rendered English summary and one blank-page fault. It provides no estimate of accuracy on Thai handwriting, faint faxes, complex bills or clinical interpretation. [Benchmark](../bench/discharge_ocr.py) · [Fictional exhibits](../fixtures/discharge/README.md)
