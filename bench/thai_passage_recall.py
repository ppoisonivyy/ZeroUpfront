"""Compare whole-page and overlapping-passage vectors on the same cached Thai policy."""
from collections import defaultdict
import json
from pathlib import Path
import unicodedata

from openai import OpenAI

from bilingual_embeddings import normalized_vectors
from thai_public_recall import DIGEST, ROOT

MODEL = "text-embedding-3-large"
WINDOW = 900
OVERLAP = 160
PRICE_PER_MILLION = 0.13


def spans(text):
    """Prefer line and phrase breaks and avoid starting a span on a combining mark."""
    start = 0
    while start < len(text):
        end = min(start + WINDOW, len(text))
        if end < len(text):
            floor = start + 2 * WINDOW // 3
            line = text.rfind("\n", floor, end)
            space = text.rfind(" ", floor, end)
            if line >= 0 or space >= 0:
                end = (line if line >= 0 else space) + 1
            while end > floor and unicodedata.category(text[end]).startswith("M"):
                end -= 1
        yield text[start:end]
        if end == len(text):
            break
        start = end - OVERLAP
        while start > 0 and unicodedata.category(text[start]).startswith("M"):
            start -= 1


def cached_pages():
    directory = ROOT / ".local/benchmark/thai-ocr" / DIGEST
    parameters = json.loads((directory / "parameters.json").read_text())
    if parameters["pdf_sha256"] != DIGEST or parameters["ocr_model"] != "gpt-6.2-astra":
        raise ValueError("Expected the pinned Thai policy and Astra reader cache")
    pages = {}
    for n in range(1, 43):
        row = json.loads((directory / f"page-{n:02}.json").read_text())
        if row.get("method") not in {"native", "astra"} or not row.get("text", "").strip():
            raise ValueError(f"Missing reader-approved text for physical page {n}")
        pages[n] = row["text"]
    return pages


def embeddings(client, texts):
    vectors = []
    token_count = 0
    for i in range(0, len(texts), 32):
        batch, tokens = normalized_vectors(client, MODEL, texts[i:i + 32])
        vectors.extend(batch)
        token_count += tokens
    return vectors, token_count


def evaluate(source_pages, vectors, queries, query_vectors):
    for lang in ("th", "en"):
        summary = {k: defaultdict(int) for k in (1, 4)}
        for (language, row), query in zip(queries, query_vectors, strict=True):
            if language != lang:
                continue
            page_scores = {}
            for page, passage in zip(source_pages, vectors, strict=True):
                score = sum(a * b for a, b in zip(query, passage, strict=True))
                page_scores[page] = max(page_scores.get(page, -1.0), score)
            top = sorted(page_scores, key=lambda page: (-page_scores[page], page))[:4]
            print(f"  {lang} {row['id']}: {top} required {row['required']}")
            for cutoff, counts in summary.items():
                covered = sum(bool(set(group).intersection(top[:cutoff])) for group in row["required"])
                counts["hit"] += covered > 0
                counts["covered"] += covered
                counts["total"] += len(row["required"])
                counts["complete"] += covered == len(row["required"])
                counts["questions"] += 1
        for cutoff, counts in summary.items():
            print(f"  {lang} @{cutoff}: hit {counts['hit']}/{counts['questions']}, "
                  f"requirement recall {counts['covered']}/{counts['total']}, "
                  f"complete {counts['complete']}/{counts['questions']}")


def main():
    pages = cached_pages()
    rows = json.loads(Path(__file__).with_name("thai_public_queries.json").read_text())
    queries = [(lang, row) for lang in ("th", "en") for row in rows]
    banks = {"whole": list(pages.items()),
             "passage": [(n, text) for n, page in pages.items() for text in spans(page)]}
    queries_text = [row[lang] for lang, row in queries]
    input_bytes = sum(len(t.encode()) for bank in banks.values() for _, t in bank)
    input_bytes += sum(len(t.encode()) for t in queries_text)
    if input_bytes * PRICE_PER_MILLION / 1_000_000 > 0.20:
        raise ValueError("Input byte count exceeds the conservative research budget")
    client = OpenAI(timeout=75, max_retries=0)
    query_vectors, tokens = embeddings(client, queries_text)
    print(f"{len(queries)} queries: {tokens} tokens")
    for name, bank in banks.items():
        page_numbers, texts = zip(*bank, strict=True)
        vectors, used = embeddings(client, texts)
        print(f"{name}: {len(texts)} vectors, {len(set(page_numbers))} pages, {used} tokens")
        tokens += used
        evaluate(page_numbers, vectors, queries, query_vectors)
    print(f"Total {tokens} tokens, estimated standard embedding cost USD {tokens * PRICE_PER_MILLION / 1_000_000:.5f}")


if __name__ == "__main__":
    main()
