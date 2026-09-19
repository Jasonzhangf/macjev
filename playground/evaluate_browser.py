"""Run the browser action and continuous-context evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import uuid
from pathlib import Path

from macjev.backends.diffgemma import DiffGemmaBackend
from evaluation.browser import load_rows, run_rows, summarize


def _git_value(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--upstream", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--run-id")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    run_id = args.run_id or uuid.uuid4().hex[:12]
    rows = load_rows(args.dataset)
    backend = DiffGemmaBackend(
        base_url=args.upstream,
        timeout_seconds=args.timeout_seconds,
    )
    health = backend.health()
    models = backend.models()
    repeated_rows = [
        {
            **row,
            "id": f"{row['id']}-r{repeat}",
            "trajectory_id": f"{row['trajectory_id']}-r{repeat}",
            "repeat": repeat,
        }
        for repeat in range(args.repeats)
        for row in rows
    ]
    records = run_rows(
        repeated_rows,
        upstream=args.upstream,
        timeout_seconds=args.timeout_seconds,
        run_id=run_id,
    )
    report = summarize(records)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "records.jsonl").write_text(
        "".join(
            json.dumps(record, ensure_ascii=False) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    (args.output / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    provenance = {
        "git_head": _git_value(repo, "rev-parse", "HEAD"),
        "git_status": _git_value(repo, "status", "--short"),
        "python": sys.version,
        "platform": platform.platform(),
        "backend": backend.name,
        "model": backend.model,
        "health": health,
        "models": models,
        "dataset": str(args.dataset),
        "dataset_sha256": _file_sha256(args.dataset),
        "upstream": args.upstream,
        "timeout_seconds": args.timeout_seconds,
        "run_id": run_id,
        "repeats": args.repeats,
        "command": [sys.executable, *sys.argv],
        "modes": [
            "fresh_schema",
            "stable_schema",
            "continuous_history",
            "schema_churn_history",
        ],
        "timing_scope": "DecisionService to complete diffgemma response",
        "phase_definitions": {
            "prefill_ms": "prompt/context encoding into KV",
            "non_prefill_ms": "complete request minus prefill",
            "denoise_ms": "structured diffusion forward",
            "complete_ms": "wall-clock service request",
        },
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
