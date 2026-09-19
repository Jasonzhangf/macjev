"""Run labelled MacJev evaluation against the real Metal service."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

from evaluation.dataset import load_rows
from evaluation.metrics import evaluate_predictions
from evaluation.runner import run_rows, write_evidence
from macjev.backends.diffgemma import DiffGemmaBackend


def _git_value(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--in-process", action="store_true")
    args = parser.parse_args()

    rows = load_rows(args.dataset)
    repo = Path(__file__).resolve().parents[1]
    backend = DiffGemmaBackend(
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
    )
    health = backend.health()
    models = backend.models()
    records, errors = run_rows(
        rows,
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
        warmup=args.warmup,
        repeats=args.repeats,
        concurrency=args.concurrency,
        in_process=args.in_process,
    )
    report = evaluate_predictions(records, errors=errors)
    provenance = {
        "git_head": _git_value(repo, "rev-parse", "HEAD"),
        "git_status": _git_value(repo, "status", "--short"),
        "python": sys.version,
        "platform": platform.platform(),
        "backend": backend.name,
        "model": backend.model,
        "base_url": args.base_url,
        "health": health,
        "models": models,
        "dataset": str(args.dataset),
        "warmup": args.warmup,
        "repeats": args.repeats,
        "concurrency": args.concurrency,
        "in_process": args.in_process,
        "errors": len(errors),
    }
    write_evidence(
        args.output,
        rows_path=args.dataset,
        records=records,
        errors=errors,
        report=report,
        provenance=provenance,
    )
    print(json.dumps({"report": report, "errors": errors}, indent=2))


if __name__ == "__main__":
    main()
