"""Independently audit saved model observations offline against the fixed physical originals."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / ".local"
GOLD = json.loads(Path(__file__).with_name("gold.json").read_text())["cases"]
# Family defaults for the three aligned packets, modified by the frozen case facts below.
ALIGNED = {
    "aia": {"admission": "match", "expense": "match", "consent": "present", "certification": "present", "letter": "present"},
    "cms": {"member": "match", "disposition": "match", "replacement": "original", "expense": "match"},
    "fep": {"payee": "hospital", "expense": "match"},
}
TARGET = {
    "aia-th-cents": ("expense", "conflict", ("87,513.42", "87,500.00")),
    "aia-en-id-decoy": ("admission", "conflict", ("AN-HO825", "AN-HO852")),
    "aia-en-ink": ("consent", "visual_review", ()), "aia-th-clinician": ("certification", "absent", ()),
    "cms-member": ("member", "conflict", ("HM0130891", "HM0130871")),
    "cms-cents": ("expense", "conflict", ("12,345.78", "12,345.67")),
    "cms-member-missing": ("member", "absent", ()),
    "fep-wrong-provider": ("payee", "other_provider", ("Saffron Bay Rehabilitation", "Lantern Quay Hospital")),
    "fep-other-signature": ("payee", "unsigned", ()),
    "fep-cents": ("expense", "conflict", ("158,050.07", "158,050.00")),
    "fep-member-back-decoy": ("payee", "member", ()),
}
# Stress cases were specified separately before the model runs. For missing pages, check a
# supplied contextual source, never a citation purporting to be the missing original.
STRESS = {
    "missing-independent-bill": [("expense", "unknown", {("records", 1)}, ("158,050.00",))],
    "missing-invoice-annex": [("expense", "unknown", {("bill", 1), ("records", 1)}, ("11,285.00",))],
    "contradictory-payees": [("payee", "unknown", {("records", 1), ("records", 3)}, ("Lantern Quay Hospital", "Check"))],
    "missing-physician-page": [("admission", "unknown", {("records", 3)}, ("AN-QA042",)),
                               ("certification", "unknown", {("records", 2)}, ())],
    "image-only-claimed-expense": [("expense", "conflict", {("records", 2), ("bill", 1)}, ("92,750.00", "87,500.00", "5,250.00"))],
}


def compact(text):
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def inspect_inputs(result, fixture, count):
    digest = sha256()
    inputs = {path.stem for path in fixture.glob("*.pdf")}
    assert inputs == set(result["manifest"]), fixture
    for role, pages in result["manifest"].items():
        path = fixture / (role + ".pdf")
        digest.update(role.encode() + path.read_bytes())
        assert len(PdfReader(path).pages) == pages, path
    assert digest.hexdigest() == result["inputs_sha256"], fixture
    for check in result["checks"]:
        assert check["pages"], check
        for ref in check["pages"]:
            assert 1 <= ref["page"] <= result["manifest"].get(ref["role"], 0), ref
            count["valid_page_references"] += 1
    count["matched_pdf_bundles"] += 1


def matches(check, state, pages, literals):
    cited = {(p["role"], p["page"]) for p in check["pages"]}
    words = compact(check["observation"])
    return check["state"] == state and pages <= cited and all(compact(value) in words for value in literals)


def observe(folder, fixture, name, mode, count):
    result = json.loads((folder / f"{name}.{mode}.json").read_text())
    assert result["case"] == name and result["mode"] == mode
    inspect_inputs(result, fixture / name, count)
    return {check["field"]: check for check in result["checks"]}


def run(holdout, stress, fixtures):
    scores = {}
    for mode in ("single", "agent"):
        counts = Counter()
        for spec in GOLD:
            name = spec["id"]
            found = observe(holdout, fixtures, name, mode, counts)
            expected = ALIGNED[spec["family"].split("-")[0]].copy()
            if name == "cms-reference-present":
                expected["replacement"] = "present"
                assert "83944167021" in found["replacement"]["observation"]
            if name in TARGET:
                field, state, literals = TARGET[name]
                expected[field] = state
                if matches(found[field], state, {(spec["role"], spec["page"])}, literals):
                    counts["target_outcomes_with_expected_source"] += 1
                    if literals:
                        counts["target_pairs_named"] += 1
            elif {field: c["state"] for field, c in found.items()} == expected:
                counts["aligned_packets"] += 1
            counts["correct_holdout_field_states"] += sum(found[k]["state"] == v for k, v in expected.items())
            counts["holdout_field_states"] += len(expected)
        for name, targets in STRESS.items():
            found = observe(stress, stress / "fixtures", name, mode, counts)
            for field, state, sources, values in targets:
                if matches(found[field], state, sources, values):
                    counts["stress_targets_with_expected_source"] += 1
        scores[mode] = dict(counts)
    return scores


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout", type=Path, default=LOCAL / "payer-ai-holdout")
    parser.add_argument("--stress", type=Path, default=LOCAL / "payer-ai-stress")
    parser.add_argument("--fixtures", type=Path, default=LOCAL / "payer-challenge/fixtures")
    args = parser.parse_args()
    print(json.dumps(run(args.holdout, args.stress, args.fixtures), indent=2))
