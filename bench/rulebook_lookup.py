"""Compare PDF search with staff-selected, source-verified tasks on two synthetic editions."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from document_text import contains_identifier, normalized, read_document
from policy_rag import PACKS, passages, retrieve

FIXTURES = ROOT / "fixtures/complex"
CATALOG = FIXTURES / "rulebook-example.json"
# The simulated staff selection is supplied to lookup. Search alone gets the Thai query.
# This pairing belongs to the comparison, never to a natural-language router.
BENCHMARK_TASKS = {
    "observation": "review_observation_stay",
    "receipt": "reconcile_guarantee_and_payment",
    "notice": "review_accident_notice",
    "room-rider": "review_room_endorsement",
}


def lookup(catalog, edition, task, document):
    if catalog["schema_version"] != 1 or not catalog["revision"]:
        raise ValueError("Unsupported catalog version")
    policy = catalog["policies"].get(edition)
    if policy is None or task not in policy["tasks"]:
        raise ValueError("Unsupported edition or staff task")
    if (document.sha256 != policy["sha256"] or document.path.name != policy["file"]
            or not contains_identifier(document.pages[0].text, edition)):
        raise ValueError("Policy PDF, digest or edition differs from the catalog")
    roots = policy["tasks"][task]
    if not roots:
        raise ValueError("No source clauses for this task")

    exhibits = {}
    visiting = set()

    def visit(clause):
        if clause in exhibits:
            return
        if clause in visiting or clause not in policy["clauses"]:
            raise ValueError(f"Invalid dependency for {clause}")
        visiting.add(clause)
        entry = policy["clauses"][clause]
        exhibit = document.locate(entry["quote"], clause)
        if exhibit["page"] != entry["page"]:
            raise ValueError(f"Source page differs for {clause}")
        # These two authored PDFs delimit clause paragraphs with a clause ID or footer.
        # A clipping that drops a qualifier can pass a substring match; require the end too.
        source = normalized(document.pages[exhibit["page"] - 1].text)
        anchor = re.escape(normalized(f"{clause} {entry['quote']}"))
        if not re.search(anchor + r" (?=[A-Z]{2}-\d+\.\d+ |Synthetic training document ·)", source):
            raise ValueError(f"Incomplete source clause {clause}")
        for dependency in entry["requires"]:
            visit(dependency)
        visiting.remove(clause)
        exhibits[clause] = exhibit

    for root in roots:
        visit(root)
    return {"catalog_revision": catalog["revision"], "edition": edition, "task": task,
            "exhibits": list(exhibits.values())}


def compare(catalog):
    rows = json.loads((ROOT / "bench/bilingual_queries.json").read_text())["queries"]
    totals = {"pdf lexical": [0, 0], "staff task": [0, 0]}
    cases = expected_pages = 0
    for row in rows:
        task = BENCHMARK_TASKS.get(row["id"])
        if task is None:
            continue
        pack = row["pack"]
        doc = read_document(FIXTURES / f"{pack}-policy.pdf")
        pdf_pages = [p.page for p in retrieve(row["th"], passages(doc, "P"), k=4)]
        result = lookup(catalog, PACKS[pack][1], task, doc)
        task_pages = sorted({e["page"] for e in result["exhibits"]})
        required = set(row["pages"])
        cases += 1
        expected_pages += len(required)
        print(f"{task}: labeled {sorted(required)}, PDF lexical @4 {pdf_pages}, staff task {task_pages}")
        for label, pages in (("pdf lexical", pdf_pages), ("staff task", task_pages)):
            totals[label][0] += required.issubset(pages)
            totals[label][1] += len(required.intersection(pages))
    for label, (complete, recovered) in totals.items():
        print(f"{label}: complete {complete}/{cases}, required pages {recovered}/{expected_pages}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", help="Edition from the enrollment schedule")
    parser.add_argument("--task", help="Staff-selected workflow key in the catalog")
    args = parser.parse_args()
    catalog = json.loads(CATALOG.read_text())
    if args.edition is None and args.task is None:
        compare(catalog)
        return
    try:
        if not args.task or args.edition not in catalog["policies"]:
            raise ValueError("Select a supported edition and task")
        policy = catalog["policies"][args.edition]
        result = lookup(catalog, args.edition, args.task, read_document(FIXTURES / policy["file"]))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except ValueError as exc:
        parser.exit(2, f"Staff review required: {exc}\n")


if __name__ == "__main__":
    main()
