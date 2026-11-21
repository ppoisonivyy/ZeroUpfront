"""Score the actual cloud demo retriever against the paired staff questions."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from cloud_policy import cloud_retrieve
from document_text import read_document
from policy_rag import PACKS, passages


def main():
    client = OpenAI(timeout=60, max_retries=1)
    queries = json.loads((ROOT/"bench/bilingual_queries.json").read_text())["queries"]
    editions = {pack: passages(read_document(ROOT/f"fixtures/complex/{pack}-policy.pdf"),"P")
                for pack in PACKS}

    def score(job):
        query, language = job
        pack = query["pack"]
        hits = cloud_retrieve(client,query[language],PACKS[pack][1],editions[pack])
        pages = [p.page for p in hits]
        expected = set(query["pages"])
        return (language,query["id"],expected.issubset(pages),len(expected.intersection(pages)),
                len(expected),bool(pages and pages[0] in expected))

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(score,((q,lang) for q in queries for lang in ("en","th"))))
    for lang in ("en","th"):
        split = [r for r in rows if r[0] == lang]
        print(lang,"complete",sum(r[2] for r in split),"/",len(split),"page recall",
              sum(r[3] for r in split),"/",sum(r[4] for r in split),"top-1",sum(r[5] for r in split),
              "incomplete", [r[1] for r in split if not r[2]])


if __name__ == "__main__":
    main()
