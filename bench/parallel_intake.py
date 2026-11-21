"""Time serial and two-worker Astra OCR on two pinned one-page synthetic fixtures."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import os
from pathlib import Path
import sys
from threading import Lock
from time import perf_counter
from types import SimpleNamespace

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from check_fixtures import estimate_fields
from document_text import contains_identifier, contains_quote, read_document

FILES = {
    "Z002/scanned-estimate.pdf": "92433f447fdc550bf9b72cf157a896e9f30c59cf563460051d734496af79d704",
    "Z003/scanned-plan.pdf": "2d0ff3675c2f1ea7ed4109310c4e6ab04e325688aa95e1407768205a0b441787",
}
MODEL = "gpt-6.2-astra"
OUTPUT_LIMIT = 800
BUDGET = 0.65
# Cover the published short-context Standard 12-hour cache-write price as well as
# ordinary input and cache reads. The SDK token totals are not a billing invoice.
MAX_INPUT_PER_MILLION = 20
OUTPUT_PER_MILLION = 40


class Meter:
    """Capture aggregate SDK usage without keeping input pages or output transcripts."""
    def __init__(self, client):
        self.client = client
        self.responses = self
        self.lock = Lock()
        self.attempted = self.completed = self.verified = 0
        self.input = self.cached = self.output = 0
        self.largest_input = 0

    @property
    def cost(self):
        return (MAX_INPUT_PER_MILLION * self.input + OUTPUT_PER_MILLION * self.output) / 1_000_000

    def parse(self, **kwargs):
        with self.lock:
            if self.attempted >= 8:
                raise ValueError("Inference cap reached")
            self.attempted += 1
        result = self.client.responses.parse(**kwargs, service_tier="default", max_output_tokens=OUTPUT_LIMIT)
        usage = result.usage
        with self.lock:
            self.completed += 1
            self.input += usage.input_tokens
            self.output += usage.output_tokens
            self.cached += getattr(usage.input_tokens_details, "cached_tokens", 0) or 0
            self.largest_input = max(self.largest_input, usage.input_tokens)
        return result


def extract(meter, name):
    doc = read_document(ROOT / "fixtures/cases" / name, meter)
    if doc.sha256 != FILES[name] or len(doc.pages) != 1 or doc.pages[0].number != 1 or not doc.pages[0].ocr:
        raise ValueError("Source digest, physical page or OCR route mismatched")
    if name.startswith("Z002/"):
        valid = (contains_identifier(doc.text, "DEMO-Z002") and contains_identifier(doc.text, "AT-2026.1")
                 and estimate_fields(doc.text) == (82000, False))
    else:
        valid = (contains_identifier(doc.text, "DEMO-Z003") and contains_identifier(doc.text, "MM-2026.1")
                 and contains_quote(doc.text, "Solely cosmetic appearance; no reconstructive indication."))
    if not valid:
        raise ValueError("Expected key facts missing")
    with meter.lock:
        meter.verified += 1


def time_arm(mode, meter, names):
    # After the two cold requests the input sizes are known for every remaining request.
    if meter.largest_input:
        ceiling = (MAX_INPUT_PER_MILLION * meter.largest_input + OUTPUT_PER_MILLION * OUTPUT_LIMIT) / 1_000_000
        if meter.cost + len(names) * ceiling > BUDGET:
            raise ValueError("Budget stop before arm")
    start = perf_counter()
    if mode == "sequential":
        for name in names:
            extract(meter, name)
    else:
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda name: extract(meter, name), names))
    return perf_counter() - start


def main():
    if not os.getenv("OPENAI_API_KEY") or (os.getenv("OPENAI_OCR_MODEL") or MODEL) != MODEL:
        sys.exit("Set OPENAI_API_KEY and select gpt-6.2-astra.")
    for name, digest in FILES.items():
        if sha256((ROOT / "fixtures/cases" / name).read_bytes()).hexdigest() != digest:
            sys.exit("The pinned input digest differed; no OCR started.")
    with OpenAI(timeout=90, max_retries=0) as client:
        meter = Meter(client)
        try:
            for pair, order in enumerate((("sequential", "parallel"), ("parallel", "sequential")), 1):
                names = list(FILES) if pair == 1 else list(reversed(FILES))
                times = {}
                for mode in order:
                    times[mode] = time_arm(mode, meter, names)
                    print(f"pair={pair} mode={mode} seconds={times[mode]:.3f} verified=2/2", flush=True)
                print(f"pair={pair} speedup={times['sequential']/times['parallel']:.2f}x", flush=True)
        except Exception as error:
            print(f"failed ({type(error).__name__}), stopping")
            return 1
        finally:
            print(f"attempted={meter.attempted} API_responses={meter.completed} verified={meter.verified} "
                  f"input={meter.input} cached={meter.cached} output={meter.output} "
                  f"estimated_cost_upper_usd={meter.cost:.5f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
