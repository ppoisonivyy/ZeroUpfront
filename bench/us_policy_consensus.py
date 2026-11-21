"""Evaluate the prespecified two-read release rule offline, without gold at decision time."""
import argparse
from collections import Counter
import json
from pathlib import Path

from pydantic import ValidationError

from us_policy_accuracy import Answer, GOLD, MODEL, contains_quote, digest, grade, load_pages, reviewed_rows, task_spec
from us_field_verifier import INSTRUCTIONS


TYPES = {"boolean": bool, "integer": int, "number": (int, float), "string": str}


def checked_read(cell, contract, pages):
    if cell.get("status") != "completed" or not cell.get("output"):
        return None
    try:
        output = Answer.model_validate(cell["output"], strict=True)
    except ValidationError:
        return None
    values = {field.key: field.value for field in output.fields}
    if values.keys() != contract.keys() or len(values) != len(output.fields):
        return None
    for key, value in values.items():
        if value is None and not output.answerable:
            continue
        spec = contract[key]
        allowed = TYPES[spec["type"]]
        if spec["type"] == "number":
            if type(value) not in allowed:
                return None
        elif type(value) is not allowed:
            return None
        if spec.get("choices") and value not in spec["choices"]:
            return None
    anchors = {}
    for citation in output.citations:
        if (citation.page not in cell["selected"] or citation.page not in pages
                or len(citation.quote.split()) < 4 or not contains_quote(pages[citation.page], citation.quote)):
            return None
        anchors[(citation.page, citation.quote)] = citation.model_dump()
    if output.answerable and not anchors:
        return None
    return output.answerable, values, anchors


def decide(full, rag, contract, pages):
    reads = [checked_read(arm, contract, pages) for arm in (full, rag)]
    if None in reads:
        return "review", None
    (answers_a, a, cites_a), (answers_b, b, cites_b) = reads
    if not answers_a and not answers_b and all(v is None for v in (*a.values(), *b.values())):
        return "missing", None
    if not (answers_a and answers_b and a == b):
        return "review", None
    if not ({p for p, _ in cites_a} & {p for p, _ in cites_b}):
        return "review", None
    return "release", {
        "answerable": True,
        "fields": [{"key": key, "value": value} for key, value in a.items()],
        "citations": list((cites_a | cites_b).values()),
    }


def decide_fields(full, second, contract, pages):
    """Require a source for each proposed field, anchored in the second reader's own inputs."""
    first = checked_read(full, contract, pages)
    if first is None or second.get("status") != "completed" or not second.get("output"):
        return "review", None
    first_answerable, first_values, first_anchors = first
    fields = second["output"]["fields"]
    if {f["key"] for f in fields} != set(contract) or len(fields) != len(contract):
        return "review", None
    if (not first_answerable and all(v is None for v in first_values.values())
            and all(f["value"] is None and not f["citations"] for f in fields)):
        return "missing", None
    if not first_answerable or any(f["value"] is None or not f["citations"] for f in fields):
        return "review", None
    anchors = dict(first_anchors)
    for field in fields:
        key = field["key"]
        field_read = {
            "status": second["status"], "selected": second["selected"],
            "output": {"answerable": True, "fields": [{"key": key, "value": field["value"]}],
                       "citations": field["citations"]},
        }
        checked = checked_read(field_read, {key: contract[key]}, pages)
        if checked is None or checked[1][key] != first_values[key]:
            return "review", None
        anchors.update(checked[2])
    return "release", {"answerable": True, "fields": full["output"]["fields"],
                       "citations": list(anchors.values())}


def compare(rows, cells, pages, field_cells=None):
    by_key = {(c["id"], c["lang"], c["arm"]): c for c in cells}
    if len(by_key) != len(cells) or len(cells) != 4 * len(rows):
        raise ValueError("Expected exactly two independent runs per question and language")
    summary = {lang: Counter() for lang in ("en", "th")}
    decisions = []
    for row in rows:
        for lang in summary:
            arms = [by_key[row["id"], lang, arm] for arm in ("full", "rag")]
            contract = task_spec(row, lang)["fields"]
            if field_cells is None:
                outcome, output = decide(*arms, contract, pages)
            else:
                outcome, output = decide_fields(arms[0], field_cells[row["id"], lang], contract, pages)
            stats = summary[lang]
            stats["cases"] += 1
            stats["answerable" if row["answerable"] else "unanswerable"] += 1
            stats[outcome] += 1
            if output is None:
                stats[f"{outcome}_on_{'answerable' if row['answerable'] else 'unanswerable'}"] += 1
                decisions.append((row["id"], lang, outcome, None, None))
                continue
            cell = {"status": "completed", "selected": list(pages), "output": output}
            score = grade(row, cell, pages)
            stats["fact_correct_releases"] += score["exact"]
            stats["supported_releases"] += score["supported"]
            stats["wrong_fact_releases"] += not score["exact"]
            stats["unsupported_releases"] += not score["supported"]
            decisions.append((row["id"], lang, outcome, score["exact"], score["supported"]))
    return {"summary": summary, "decisions": decisions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scores", type=Path, help="Original scores.json produced by the US policy accuracy bench")
    parser.add_argument("--labels", choices=("audited", "frozen"), default="audited")
    parser.add_argument("--field-verifier", action="store_true",
                        help="Score the independent field-level verifier after running its benchmark")
    args = parser.parse_args()
    gold = GOLD.read_text()
    rows = json.loads(gold)["questions"]
    report = json.loads(args.scores.read_text())
    if report["suite_sha256"] != digest(gold):
        parser.error("Score files must match the frozen question suite")
    if args.labels == "audited":
        rows = reviewed_rows(rows, digest(gold))
    field_cells = None
    if args.field_verifier:
        directory = args.scores.parent / ("field-verifier-" + digest(INSTRUCTIONS + MODEL)[:12])
        field_cells = {}
        for row in rows:
            for lang in ("en", "th"):
                cell = json.loads((directory / f"{row['id']}-{lang}.json").read_text())
                if (cell["id"], cell["lang"]) != (row["id"], lang):
                    raise ValueError("Field verifier output does not match this question")
                field_cells[row["id"], lang] = cell
    print(json.dumps(compare(rows, report["cells"], load_pages(), field_cells), indent=2))


if __name__ == "__main__":
    main()
