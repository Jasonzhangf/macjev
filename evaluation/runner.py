"""Run labelled evaluation rows through the real MacJev HTTP service."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from macjev.backends.diffgemma import DiffGemmaBackend
from macjev.service import DecisionService


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_request(row: dict[str, Any]) -> dict[str, Any]:
    question = row["question"]
    criteria = question.get("criteria")
    if row["type"] == "noul":
        criteria = None
    return {
        "model": "jev-latest",
        "state": row["state"],
        "questions": {
            row["id"]: {
                "type": row["type"],
                "instructions": question["instructions"],
                **({"criteria": criteria} if criteria is not None else {}),
            }
        },
        "options": {"samples": "auto"},
    }


def _call_http(
    base_url: str,
    request_body: dict[str, Any],
    timeout_seconds: float,
) -> tuple[dict[str, Any], float]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/systemone",
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:500]}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"request failed: {exc}") from exc
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if not isinstance(payload, dict):
        raise RuntimeError("response is not a JSON object")
    return payload, elapsed_ms


def _call_in_process(
    service: DecisionService,
    request_body: dict[str, Any],
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    result = service.decide(request_body)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    public = {
        "model": result["model"],
        "answers": result["answers"],
        "usage": result["usage"],
    }
    return public, elapsed_ms


def run_rows(
    rows: list[dict[str, Any]],
    *,
    base_url: str,
    timeout_seconds: float,
    warmup: int,
    repeats: int,
    concurrency: int,
    in_process: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if warmup < 0 or repeats < 1 or concurrency < 1:
        raise ValueError("warmup must be >= 0, repeats and concurrency must be >= 1")

    backend = DiffGemmaBackend(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    service = DecisionService(backend)

    def invoke(row: dict[str, Any]) -> tuple[dict[str, Any], float]:
        request_body = build_request(row)
        if in_process:
            return _call_in_process(service, request_body)
        return _call_http(base_url, request_body, timeout_seconds)

    for row in rows[:warmup]:
        invoke(row)

    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    def evaluate_once(row: dict[str, Any], repeat: int, concurrency_level: int) -> None:
        try:
            response, elapsed_ms = invoke(row)
            answer = response["answers"][row["id"]]
            records.append(
                {
                    "id": row["id"],
                    "split": row["split"],
                    "type": row["type"],
                    "cardinality": row["cardinality"],
                    "source": row["source"],
                    "scenario": row["scenario"],
                    "answer": answer,
                    "label": row["label"],
                    "latency_ms": elapsed_ms,
                    "repeat": repeat,
                    "concurrency": concurrency_level,
                    "response": response,
                    "is_mock": False,
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "id": row["id"],
                    "split": row["split"],
                    "type": row["type"],
                    "cardinality": row["cardinality"],
                    "source": row["source"],
                    "scenario": row["scenario"],
                    "repeat": repeat,
                    "concurrency": concurrency_level,
                    "error": str(exc),
                }
            )

    jobs = [
        (row, repeat, concurrency)
        for repeat in range(repeats)
        for row in rows
    ]
    if concurrency == 1:
        for row, repeat, level in jobs:
            evaluate_once(row, repeat, level)
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(evaluate_once, row, repeat, level)
                for row, repeat, level in jobs
            ]
            for future in futures:
                future.result()
    return records, errors


def write_evidence(
    output_dir: Path,
    *,
    rows_path: Path,
    records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    report: dict[str, Any],
    provenance: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "dataset.sha256").write_text(
        f"{file_sha256(rows_path)}  {rows_path.name}\n",
        encoding="utf-8",
    )
    (output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "records.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    (output_dir / "errors.jsonl").write_text(
        "".join(json.dumps(error, ensure_ascii=False) + "\n" for error in errors),
        encoding="utf-8",
    )
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
