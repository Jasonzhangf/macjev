"""Recompute an evaluation report from persisted real-run records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.metrics import evaluate_predictions
from evaluation.runner import add_timing_metrics, option_order_sensitivity


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
    perturbation_records_path = args.run_dir / "perturbation_records.jsonl"
    perturbation_records = (
        [
            json.loads(line)
            for line in perturbation_records_path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        if perturbation_records_path.exists()
        else []
    )
    provenance_path = args.run_dir / "provenance.json"
    provenance = (
        json.loads(provenance_path.read_text(encoding="utf-8"))
        if provenance_path.exists()
        else {}
    )
    run_speed = provenance.get("run_speed")
    if isinstance(run_speed, dict):
        add_timing_metrics(run_speed, records)
    report = evaluate_predictions(
        records,
        errors=errors,
        run_speed=run_speed,
    )
    report["option_order_sensitivity"] = option_order_sensitivity(
        records + perturbation_records
    )
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
