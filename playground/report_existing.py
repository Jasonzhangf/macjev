"""Recompute an evaluation report from persisted real-run records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.metrics import evaluate_predictions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    records = [
        json.loads(line)
        for line in (args.run_dir / "records.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    errors = [
        json.loads(line)
        for line in (args.run_dir / "errors.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    report = evaluate_predictions(records, errors=errors)
    (args.run_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "count": report["count"],
                "errors": report["error_count"],
                "accuracy": report["overall"]["accuracy"],
                "aurc": report["overall"]["aurc"],
                "speed": report["overall"]["speed"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
