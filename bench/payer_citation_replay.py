"""Replay six recorded model responses against their exact local synthetic discharge packets.

Run from the repository root with:
    uv run --locked python bench/payer_citation_replay.py

The original PDFs must already be prepared. If missing, run
    uv run --locked python bench/us_payer_forms.py
    uv run --locked python bench/payer_challenge.py --prepare-only
Those preparatory commands may download public blank forms. The replay itself never uses
the network, does not require credentials, and reads the recorded responses from Git.
"""

import base64
import json
import os
import socket
import sys
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import payer_ai_reader as ai
from app.discharge_claim import evaluate_discharge
from app.document_text import contains_identifier


def saved_checks(row):
    """Reconstruct the response fields, ignoring gold labels and scoring decisions."""
    checks = []
    for field, item in row["scores"].items():
        citations = []
        for address in item["pages"]:
            role, number = address.split(":")
            citations.append({"role": role, "page": int(number)})
        checks.append(
            {"field": field, "state": item["state"], "observation": item["observation"], "pages": citations}
        )
    return ai.Review(checks=checks)


def packet(phase, name):
    root = ROOT / ".local"
    folder = root / ("us-payer/packets" if phase == "original" else "payer-challenge/fixtures") / name
    meta = folder / ("intake.json" if phase == "original" else "metadata.json")
    if not meta.exists():
        raise FileNotFoundError(f"Prepare the synthetic PDFs first. Missing {meta}. See the module docstring.")
    original = {
        role: (folder / f"{role}.pdf").read_bytes() for role in ai.ROLES if (folder / f"{role}.pdf").is_file()
    }
    digest = sha256()
    for role, data in original.items():
        digest.update(role.encode() + data)
    case = evaluate_discharge(
        dict(json.loads(meta.read_text()), id=name), original, {r: f"{r}.pdf" for r in original}
    )
    return {**case, "revision": 1}, original, digest.hexdigest()


def has_on_page(originals, addr, value):
    role, page = addr
    return contains_identifier(PdfReader(BytesIO(originals[role])).pages[page - 1].extract_text() or "", value)


def replay(row, family, case, originals, digest):
    if row["pdf_digest"] != digest:
        raise ValueError(f"The {row['case']} originals differ from those used for the saved model response.")
    previous = saved_checks(row)
    saved = SimpleNamespace(status="completed", model=row["model"], output_parsed=previous)
    with patch.object(ai, "OpenAI") as provider:
        parse = provider.return_value.__enter__.return_value.responses.parse
        parse.return_value = saved
        current = ai.second_read(case, originals, family)
        parse.assert_called_once()
        request = parse.call_args.kwargs
        assert request["store"] is False
        sent = {
            file["filename"]: base64.b64decode(file["file_data"].split(",", 1)[1], validate=True)
            for file in request["input"][0]["content"]
            if file["type"] == "input_file"
        }
        assert sent == {f"{role}.pdf": data for role, data in originals.items()}
    field = "member" if family == "cms" else "admission"
    check = next(item for item in current.checks if item.field == field)
    assert current.revision == case["revision"] and current.family == family
    links = {(p.role, p.page) for p in check.pages}
    if family == "cms":
        # The itemized account on bill p3 is independent of FL60 on the same PDF's first page.
        valid = check.state == "conflict" and {("bill", 1), ("bill", 3)} <= links
        valid &= has_on_page(originals, ("bill", 3), case["member"])
        mismatch = next(f for f in case["findings"] if f["code"] == "cms_member_mismatch")
        form_value = next(s["quote"] for s in mismatch["sources"] if (s["role"], s["page"]) == ("bill", 1))
        valid &= bool(
            form_value and form_value != case["member"] and has_on_page(originals, ("bill", 1), form_value)
        )
    else:
        independent = links & {("bill", 1), ("summary", 1)}
        valid = check.state == "match" and ("records", 2) in links and bool(independent)
        valid &= has_on_page(originals, ("records", 2), case["encounter"])
        valid &= any(has_on_page(originals, address, case["encounter"]) for address in independent)
        consent = next(item for item in current.checks if item.field == "consent")
        valid &= consent.state == "visual_review" and ("records", 1) in {
            (p.role, p.page) for p in consent.pages
        }
    prior = next(item for item in previous.checks if item.field == field)
    describe = lambda item: ", ".join(f"{p.role} p{p.page}" for p in item.pages)
    print(f"  {field}: {prior.state} [{describe(prior)}] -> {check.state} [{describe(check)}]")
    return valid


def main():
    saved = json.loads((ROOT / "bench/results/payer-form-ai-comparison.json").read_text())
    failures = []
    with (
        patch.dict(os.environ, {"WORKSPACE_ENABLE_AI_REVIEW": "1", "OPENAI_API_KEY": "offline-mock-only"}),
        patch.object(
            socket.socket, "connect", side_effect=AssertionError("Network disabled for citation replay")
        ),
    ):
        for phase, name, family in [
            ("original", "cms_wrong_member", "cms"),
            ("holdout", "cms-member", "cms"),
            ("holdout", "aia-en-ink", "aia"),
        ]:
            case, originals, digest = packet(phase, name)
            for mode in ("single", "agent"):
                (row,) = (r for r in saved[phase][mode]["observations"] if r["case"] == name)
                print(f"{name} / {mode} / revision {case['revision']}")
                if not replay(row, family, case, originals, digest):
                    failures.append(f"{name}/{mode}")
    if failures:
        raise SystemExit("Missing state or required original page: " + ", ".join(failures))
    print("Passed all six saved responses. Zero external calls.")


if __name__ == "__main__":
    main()
