"""Compare explicit embedding models on a pinned Thai insurer PDF and authored page labels."""
import argparse
from hashlib import sha256
import json
import logging
from pathlib import Path

from openai import OpenAI
from pypdf import PdfReader

from bilingual_embeddings import normalized_vectors

ROOT = Path(__file__).resolve().parents[1]
DIGEST = "d5b4e3f8d3bbf2c524f0dabf9b2ed0e942f7e9bad02c8eb5a7120d0633e3fcd4"


def compare(client, model, pages, rows):
    queries = [(lang, row) for lang in ("th", "en") for row in rows]
    texts = pages + [row[lang] for lang, row in queries]
    vectors, tokens = normalized_vectors(client, model, texts)
    print(f"{model}: {len(vectors[0])} dimensions, {tokens} tokens")
    for lang in ("th", "en"):
        rankings = []
        for (query_lang, row), q in zip(queries, vectors[len(pages):], strict=True):
            if query_lang != lang:
                continue
            scores = [sum(x*y for x, y in zip(q, p, strict=True)) for p in vectors[:len(pages)]]
            ranked = sorted(range(1, len(pages) + 1), key=lambda page: scores[page - 1], reverse=True)
            print(f"  {lang} {row['id']}: {ranked[:4]} expected {row['required']}")
            rankings.append((row['required'], ranked))
        for k in (1, 4):
            hit = covered = complete = count = 0
            for groups, ranking in rankings:
                found = sum(bool(set(group).intersection(ranking[:k])) for group in groups)
                covered += found
                count += len(groups)
                hit += found > 0
                complete += found == len(groups)
            print(f"  {lang} @{k}: hit {hit}/{len(rows)}, requirement recall {covered}/{count}, "
                  f"complete {complete}/{len(rows)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=ROOT / ".local/references/th-allianz-superior.pdf")
    args = parser.parse_args()
    if sha256(args.pdf.read_bytes()).hexdigest() != DIGEST:
        parser.error("PDF digest differs from the reviewed edition")
    # Some cover fonts generate verbose encoding warnings. Keep the extracted layer as-is.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    pages = [" ".join(p.extract_text().split()) for p in PdfReader(args.pdf).pages]
    rows = json.loads(Path(__file__).with_name("thai_public_queries.json").read_text())
    if len(pages) != 42 or not all(pages):
        parser.error("Expected 42 nonempty physical pages")
    for row in rows:
        if not row["required"] or any(not group or not all(1 <= p <= len(pages) for p in group)
                                      for group in row["required"]):
            parser.error(f"Invalid evidence requirements for {row['id']}")
    print(f"{len(pages)} pages, {len(rows)} paired questions; "
          f"{sum(p.count(chr(0xfffd)) for p in pages)} replacement characters")
    client = OpenAI(timeout=70, max_retries=1)
    for model in ("text-embedding-3-small", "text-embedding-3-large"):
        compare(client, model, pages, rows)


if __name__ == "__main__":
    main()
