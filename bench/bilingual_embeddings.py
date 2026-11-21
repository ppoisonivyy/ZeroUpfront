"""Compare standalone cosine retrieval on paired synthetic English and Thai questions."""
import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import sys

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from document_text import read_document
from policy_rag import passages


def normalized_vectors(client, model, texts):
    response = client.embeddings.create(model=model, input=texts)
    entries = sorted(response.data, key=lambda entry: entry.index)
    if len(entries) != len(texts) or [e.index for e in entries] != list(range(len(texts))):
        raise ValueError("Unexpected embedding response indexes")
    vectors = []
    for entry in entries:
        length = math.sqrt(sum(value * value for value in entry.embedding))
        if not math.isfinite(length) or length <= 0:
            raise ValueError("Non-finite or zero vector")
        vectors.append([value / length for value in entry.embedding])
    return vectors, response.usage.total_tokens


def compare(client, model, banks, questions):
    keys = list(banks)
    indexed = [p for key in keys for p in banks[key]]
    queries = [(row, lang) for row in questions for lang in ("en", "th")]
    # The API embeds each string independently. IDs and gold labels are local.
    texts = [p.text for p in indexed] + [row[lang] for row, lang in queries]
    all_vectors, tokens = normalized_vectors(client, model, texts)
    bank_vectors = {}
    start = 0
    for key in keys:
        stop = start + len(banks[key])
        bank_vectors[key] = all_vectors[start:stop]
        start = stop
    runs = []
    for (row, lang), q in zip(queries, all_vectors[start:], strict=True):
        pack = row["pack"]
        candidates = banks[pack]
        scores = [sum(x*y for x, y in zip(q, vector, strict=True))
                  for vector in bank_vectors[pack]]
        ranked = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)
        # Multiple passages from a page count once in a page-level evaluation.
        pages = list(dict.fromkeys(candidates[index].page for index in ranked))
        runs.append((row, lang, pages))
    return runs, len(all_vectors[0]), tokens


def report(model, results, details):
    groups = defaultdict(list)
    for row, lang, ranked in results:
        groups[lang].append((row, ranked))
        groups[f"{lang}/{row['pack']}"].append((row, ranked))
        if details:
            print(f"  {row['id']} {lang}: retrieved {ranked[:4]}, expected {row['pages']}")
    for label, rows in groups.items():
        for k in (1, 4):
            total = found = complete = hit = 0
            for row, ranked in rows:
                relevant = set(row["pages"])
                matched = relevant.intersection(ranked[:k])
                total += len(relevant)
                found += len(matched)
                complete += int(matched == relevant)
                hit += int(bool(matched))
            print(f"{model} {label} @{k}: hit {hit}/{len(rows)}, page recall {found}/{total}, "
                  f"complete evidence {complete}/{len(rows)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--details", action="store_true", help="Show page ranks per query")
    args = parser.parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY in .env and pass --env-file .env to uv")
    data = json.loads(Path(__file__).with_name("bilingual_queries.json").read_text())
    questions = data["queries"]
    banks = {pack: passages(read_document(ROOT / "fixtures" / "complex" / f"{pack}-policy.pdf"), "P")
             for pack in ("us", "th")}
    for q in questions:
        if not q["pages"] or not set(q["pages"]).issubset(p.page for p in banks[q["pack"]]):
            raise ValueError(f"Invalid gold page for {q['id']}")
    client = OpenAI(timeout=60, max_retries=1)
    for model in ("text-embedding-3-small", "text-embedding-3-large"):
        runs, dims, tokens = compare(client, model, banks, questions)
        print(f"{model}: {dims} dimensions, {tokens} input tokens")
        report(model, runs, args.details)


if __name__ == "__main__":
    main()
