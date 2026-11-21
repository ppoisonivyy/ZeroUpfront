"""Run both countries' discharge rehearsals in parallel on separate disposable databases."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run_country(name, commands):
    directory = ROOT / ".local" / "payer-rehearsal"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.log"
    with path.open("w") as log:
        for command in commands:
            result = subprocess.run([sys.executable, *command], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                return name, result.returncode, path
    return name, 0, path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Also run OpenAI OCR on the seven AIA and two FEP packets.")
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=4, help="Concurrent cases per country.")
    args = parser.parse_args()
    workers = ["--workers", str(args.workers)]
    thailand = [["bench/thai_payer_forms.py", *workers]]
    us = [["bench/us_payer_forms.py", *workers]]
    if args.live:
        thailand.append([*thailand[0], "--live"])
        us[0].append("--live-fep-ocr")
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(run_country, "thailand", thailand), pool.submit(run_country, "us", us)]
        results = [task.result() for task in tasks]
    for name, status, log in results:
        print(f"{name} {'completed' if status == 0 else 'failed'} — {log.relative_to(ROOT)}")
    return int(any(status for _, status, _ in results))


if __name__ == "__main__":
    sys.exit(main())
