"""Change only the language of the managed search call, preserving the original Thai vector."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median
from types import SimpleNamespace
import json
import sys
import time

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from cloud_policy import cloud_retrieve
from document_text import read_document
from policy_rag import PACKS, passages


def lookup(client, pack, passages_for_edition, question, search_question):
    embedding_tokens = 0

    def embed(**kwargs):
        nonlocal embedding_tokens
        response = client.embeddings.create(**kwargs)
        embedding_tokens += response.usage.total_tokens
        return response

    def search(store, **kwargs):
        kwargs["query"] = search_question
        return client.vector_stores.search(store, **kwargs)

    services = SimpleNamespace(
        vector_stores=SimpleNamespace(search=search, files=client.vector_stores.files),
        embeddings=SimpleNamespace(create=embed),
    )
    hits = cloud_retrieve(services, question, PACKS[pack][1], passages_for_edition)
    return [hit.page for hit in hits], embedding_tokens


def main():
    client = OpenAI(timeout=35, max_retries=0)
    data = json.loads((ROOT / "bench/bilingual_queries.json").read_text())["queries"]
    editions = {
        pack: passages(read_document(ROOT / "fixtures/complex" / f"{pack}-policy.pdf"), "P")
        for pack in PACKS
    }

    def run(item):
        question = item["th"]
        pack = item["pack"]
        start = time.perf_counter()
        response = client.responses.create(
            model="gpt-6.2-astra", store=False, max_output_tokens=480,
            reasoning={"effort": "low"},
            instructions=("Translate this Thai health insurance staff question into idiomatic English. "
                          "Keep every factual detail and uncertainty. Return only the translation. "
                          "Do not answer or add information."),
            input=question,
        )
        if response.status != "completed" or not response.output_text.strip():
            raise ValueError(f"Translation failed for {item['id']}: {response.status}")
        translation = response.output_text.strip()
        seconds = time.perf_counter() - start
        baseline, tokens_a = lookup(client, pack, editions[pack], question, question)
        variant, tokens_b = lookup(client, pack, editions[pack], question, translation)
        return {
            "id": item["id"],
            "translation": translation,
            "baseline": baseline,
            "translated": variant,
            "gold": item["pages"],
            "translation_seconds": round(seconds, 3),
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "embedding_tokens": tokens_a + tokens_b,
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(run, data))

    for mode in ("baseline", "translated"):
        complete = sum(set(row["gold"]).issubset(row[mode]) for row in rows)
        pages = sum(len(set(row["gold"]).intersection(row[mode])) for row in rows)
        gold_pages = sum(len(row["gold"]) for row in rows)
        first = sum(row[mode][0] in row["gold"] for row in rows)
        print(f"{mode}: complete {complete}/{len(rows)}, pages {pages}/{gold_pages}, first {first}/{len(rows)}")
        for row in rows:
            if not set(row["gold"]).issubset(row[mode]):
                print(f"  {row['id']}: retrieved {row[mode]}, required {row['gold']}")
    for meter in ("input_tokens", "output_tokens", "embedding_tokens"):
        print(meter, sum(row[meter] for row in rows))
    print("median translation seconds", median(row["translation_seconds"] for row in rows))


if __name__ == "__main__":
    main()
