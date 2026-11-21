"""Evaluate financial fields against independent labels after reading only the exhibits."""
import argparse
from decimal import Decimal
import json
from pathlib import Path

from finance import ReviewRequired, billing_fields, gop_fields


def financial_fields(packet):
    """Adapter entry point. Return None for a medical-record-only packet."""
    exhibits = packet["exhibits"]
    if any(key.startswith("B p") for key in exhibits):
        return billing_fields(packet["case"], exhibits)
    if "S p1" in exhibits or any(key.startswith("P §") for key in exhibits):
        return gop_fields(packet["case"], exhibits)
    if exhibits and all(key.startswith("M p") for key in exhibits):
        return None
    raise ReviewRequired("Unrecognized packet format")


def expected_value(expected, field):
    if field in ("reported_gross", "reported_discount", "reported_net"):
        return expected["reported_totals"][field.removeprefix("reported_")]
    return expected[field]


def evaluate(folder):
    seen = set()
    passed = True
    for split in ("train", "eval"):
        count = correct = fields = skipped = rejected = 0
        with (folder / f"{split}.jsonl").open() as rows:
            for row in rows:
                if not row.strip():
                    continue
                messages = json.loads(row)["messages"]
                if [message["role"] for message in messages] != ["system", "user", "assistant"]:
                    raise ValueError("Unexpected sample message order")
                packet = json.loads(messages[1]["content"])
                case = packet["case"]
                if case in seen:
                    raise ValueError(f"Duplicate case in evaluation: {case}")
                seen.add(case)
                try:
                    result = financial_fields(packet)
                except ReviewRequired as error:
                    print(f"{case} requires staff review: {error}")
                    rejected += 1
                    continue
                if result is None:
                    skipped += 1
                    continue
                count += 1
                expected = json.loads(messages[2]["content"], parse_float=Decimal)
                for key, actual in result.items():
                    target = expected_value(expected, key)
                    fields += 1
                    if actual == target:
                        correct += 1
                    else:
                        print(f"{case} {key}: expected {target!r}, calculated {actual!r}")
        print(f"{split}: {correct}/{fields} financial and status fields; {count} financial packets, "
              f"{skipped} medical-record-only, {rejected} unsupported.")
        passed &= count > 0 and rejected == 0 and correct == fields
    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path,
                        default=Path(__file__).resolve().parents[1] / "ZeroUpfront-training-samples")
    raise SystemExit(0 if evaluate(parser.parse_args().samples) else 1)
