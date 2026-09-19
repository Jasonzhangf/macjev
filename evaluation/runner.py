"""Run labelled evaluation rows through the real MacJev HTTP service."""

from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from evaluation.metrics import selected_probability_label
from macjev.backends.diffgemma import DiffGemmaBackend
from macjev.service import DecisionService


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = percentile * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _timing_from_response(response: dict[str, Any]) -> dict[str, Any] | None:
    diagnostics = response.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    raw = diagnostics.get("raw_backend_response")
    if not isinstance(raw, dict):
        return None
    raw_diagnostics = raw.get("diagnostics")
    if not isinstance(raw_diagnostics, dict):
        return None
    timing = raw_diagnostics.get("timing")
    return timing if isinstance(timing, dict) else None


def _timing_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for field in (
        "prefill_ms",
        "denoise_ms",
        "prompt_tokens",
        "reused_tokens",
        "samples",
        "rounds",
        "steps_run",
    ):
        values = []
        for record in records:
            timing = record.get("timing")
            if not isinstance(timing, dict):
                continue
            value = timing.get(field)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            ):
                values.append(float(value))
        if not values:
            metrics[field] = {
                "count": 0,
                "p50": None,
                "p95": None,
                "mean": None,
                "sum": None,
            }
            continue
        metrics[field] = {
            "count": len(values),
            "p50": _percentile(values, 0.50),
            "p95": _percentile(values, 0.95),
            "mean": sum(values) / len(values),
            "sum": sum(values),
        }

    observed = [
        record
        for record in records
        if isinstance(record.get("timing"), dict)
    ]
    if observed:
        prefill = [float(record["timing"]["prefill_ms"]) for record in observed]
        denoise = [float(record["timing"]["denoise_ms"]) for record in observed]
        total = [float(record["latency_ms"]) for record in observed]
        other = [
            max(0.0, latency - prefill_value - denoise_value)
            for latency, prefill_value, denoise_value in zip(total, prefill, denoise)
        ]
        non_prefill = [
            max(0.0, latency - prefill_value)
            for latency, prefill_value in zip(total, prefill)
        ]
        metrics["request_breakdown"] = {
            "count": len(observed),
            "prefill_p50_ms": _percentile(prefill, 0.50),
            "non_prefill_p50_ms": _percentile(non_prefill, 0.50),
            "denoise_p50_ms": _percentile(denoise, 0.50),
            "other_p50_ms": _percentile(other, 0.50),
            "prefill_share": sum(prefill) / sum(total),
            "non_prefill_share": sum(non_prefill) / sum(total),
            "denoise_share": sum(denoise) / sum(total),
            "other_share": sum(other) / sum(total),
        }
        fresh_prefill = [
            float(record["timing"]["prefill_ms"])
            for record in observed
            if float(record["timing"].get("reused_tokens", 0)) == 0.0
        ]
        reused_prefill = [
            float(record["timing"]["prefill_ms"])
            for record in observed
            if float(record["timing"].get("reused_tokens", 0)) > 0.0
        ]
        metrics["prefill_cache"] = {
            "fresh_count": len(fresh_prefill),
            "fresh_p50_ms": (
                _percentile(fresh_prefill, 0.50) if fresh_prefill else None
            ),
            "reused_count": len(reused_prefill),
            "reused_p50_ms": (
                _percentile(reused_prefill, 0.50) if reused_prefill else None
            ),
        }
    else:
        metrics["request_breakdown"] = {
            "count": 0,
            "prefill_p50_ms": None,
            "non_prefill_p50_ms": None,
            "denoise_p50_ms": None,
            "other_p50_ms": None,
            "prefill_share": None,
            "non_prefill_share": None,
            "denoise_share": None,
            "other_share": None,
        }
        metrics["prefill_cache"] = {
            "fresh_count": 0,
            "fresh_p50_ms": None,
            "reused_count": 0,
            "reused_p50_ms": None,
        }
    return metrics


def add_timing_metrics(
    speed: dict[str, Any],
    records: list[dict[str, Any]],
) -> None:
    speed["timing"] = _timing_metrics(records)
    speed["timing_slices"] = {}
    for dimension in ("scenario", "type"):
        groups: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            groups.setdefault(str(record[dimension]), []).append(record)
        speed["timing_slices"][dimension] = {
            value: _timing_metrics(group)
            for value, group in sorted(groups.items())
        }
    sample_groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        timing = record.get("timing")
        if isinstance(timing, dict) and "samples" in timing:
            sample_groups.setdefault(str(timing["samples"]), []).append(record)
    speed["timing_slices"]["samples"] = {
        value: _timing_metrics(group)
        for value, group in sorted(sample_groups.items())
    }


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


def _reverse_criteria(row: dict[str, Any]) -> dict[str, Any]:
    question = row["question"]
    criteria = question.get("criteria")
    if row["type"] == "choice":
        if not isinstance(criteria, dict):
            raise ValueError("choice criteria must be an object")
        reversed_criteria = dict(reversed(list(criteria.items())))
    elif row["type"] == "score":
        if not isinstance(criteria, list):
            raise ValueError("score criteria must be an array")
        reversed_criteria = list(reversed(criteria))
    else:
        return row
    return {
        **row,
        "question": {
            **question,
            "criteria": reversed_criteria,
        },
    }


def _canonicalize_answer(
    row: dict[str, Any],
    order: str,
    answer: dict[str, Any],
) -> dict[str, Any]:
    """Map order-sensitive positional score fields back to dataset order."""

    if order != "reversed" or row["type"] != "score":
        return answer
    criteria = row["question"].get("criteria")
    if not isinstance(criteria, list):
        raise ValueError("score criteria must be an array")
    size = len(criteria)
    raw_probabilities = answer.get("probabilities")
    if not isinstance(raw_probabilities, dict):
        raise ValueError("score answer probabilities must be an object")
    raw_score = answer.get("score")
    if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool):
        raise ValueError("score answer score must be numeric")
    probabilities = {
        str(index): raw_probabilities[str(size - 1 - index)]
        for index in range(size)
    }
    return {
        **answer,
        "score": size - 1 - float(raw_score),
        "legend": {
            str(index): level for index, level in enumerate(criteria)
        },
        "probabilities": probabilities,
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
    return result, elapsed_ms


def summarize_run_speed(
    *,
    attempts: int,
    completed: int,
    errors: int,
    elapsed_ms: float,
    warmup_latencies_ms: list[float],
    concurrency: int,
    repeats: int,
    latency_scope: str,
) -> dict[str, Any]:
    if attempts < 1 or completed < 0 or errors < 0:
        raise ValueError("attempts must be positive; completed and errors non-negative")
    if completed + errors != attempts:
        raise ValueError("completed plus errors must equal attempts")
    if elapsed_ms <= 0.0:
        raise ValueError("elapsed_ms must be positive")
    if concurrency < 1 or repeats < 1:
        raise ValueError("concurrency and repeats must be positive")

    elapsed_seconds = elapsed_ms / 1000.0
    warmup = {
        "count": len(warmup_latencies_ms),
        "first_request_ms": (
            warmup_latencies_ms[0] if warmup_latencies_ms else None
        ),
        "mean_ms": (
            sum(warmup_latencies_ms) / len(warmup_latencies_ms)
            if warmup_latencies_ms
            else None
        ),
    }
    return {
        "latency_scope": latency_scope,
        "concurrency": concurrency,
        "repeats": repeats,
        "warmup": warmup,
        "measured": {
            "attempts": attempts,
            "completed": completed,
            "errors": errors,
            "error_rate": errors / attempts,
            "wall_clock_ms": elapsed_ms,
            "attempted_rps": attempts / elapsed_seconds,
            "successful_rps": completed / elapsed_seconds,
        },
        "ttft": {
            "value_ms": None,
            "status": "unavailable_non_streaming_response",
        },
        "process_startup": {
            "value_ms": None,
            "status": "not_measured_service_prestarted",
        },
        "phase_scope": {
            "prefill_ms": "diffgemma prompt/context prefill",
            "non_prefill_ms": "request total minus prefill; includes denoise",
            "denoise_ms": "diffgemma structured diffusion forward",
            "other_ms": "request total minus prefill and denoise",
        },
    }


def run_rows(
    rows: list[dict[str, Any]],
    *,
    base_url: str,
    timeout_seconds: float,
    warmup: int,
    repeats: int,
    concurrency: int,
    in_process: bool,
    reverse_options: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if warmup < 0 or repeats < 1 or concurrency < 1:
        raise ValueError("warmup must be >= 0, repeats and concurrency must be >= 1")

    backend = DiffGemmaBackend(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    service = DecisionService(backend)

    def invoke(
        row: dict[str, Any], order: str
    ) -> tuple[dict[str, Any], float, dict[str, Any] | None]:
        request_row = _reverse_criteria(row) if order == "reversed" else row
        request_body = build_request(request_row)
        if in_process:
            response, elapsed_ms = _call_in_process(service, request_body)
        else:
            response, elapsed_ms = _call_http(base_url, request_body, timeout_seconds)
        timing = _timing_from_response(response)
        return response, elapsed_ms, timing

    warmup_latencies_ms = []
    for row in rows[:warmup]:
        _, elapsed_ms, _ = invoke(row, "canonical")
        warmup_latencies_ms.append(elapsed_ms)

    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    def evaluate_once(
        row: dict[str, Any],
        repeat: int,
        concurrency_level: int,
        order: str,
    ) -> None:
        try:
            response, elapsed_ms, timing = invoke(row, order)
            answer = _canonicalize_answer(
                row,
                order,
                response["answers"][row["id"]],
            )
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
                    "timing": timing,
                    "repeat": repeat,
                    "concurrency": concurrency_level,
                    "option_order": order,
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
                    "option_order": order,
                    "error": str(exc),
                }
            )

    orders = ["canonical", "reversed"] if reverse_options else ["canonical"]
    jobs = [
        (row, repeat, concurrency, order)
        for order in orders
        for repeat in range(repeats)
        for row in rows
    ]
    measured_started = time.perf_counter()
    if concurrency == 1:
        for row, repeat, level, order in jobs:
            evaluate_once(row, repeat, level, order)
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(evaluate_once, row, repeat, level, order)
                for row, repeat, level, order in jobs
            ]
            for future in futures:
                future.result()
    measured_elapsed_ms = (time.perf_counter() - measured_started) * 1000.0
    speed = summarize_run_speed(
        attempts=len(jobs),
        completed=len(records),
        errors=len(errors),
        elapsed_ms=measured_elapsed_ms,
        warmup_latencies_ms=warmup_latencies_ms,
        concurrency=concurrency,
        repeats=repeats,
        latency_scope=(
            "decision_service_to_complete_backend_response"
            if in_process
            else "request_to_complete_public_json_response"
        ),
    )
    add_timing_metrics(speed, records)
    return records, errors, speed


def option_order_sensitivity(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    canonical: dict[str, dict[str, Any]] = {}
    reversed_records: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("option_order") == "canonical":
            canonical[record["id"]] = record
        elif record.get("option_order") == "reversed":
            reversed_records[record["id"]] = record

    comparisons = []
    for row_id in sorted(set(canonical) & set(reversed_records)):
        left = canonical[row_id]
        right = reversed_records[row_id]
        if left["type"] not in {"choice", "score"}:
            continue
        left_probabilities = left["answer"]["probabilities"]
        right_probabilities = right["answer"]["probabilities"]
        if left["type"] == "choice":
            right_values = {
                label: right_probabilities[label]
                for label in left_probabilities
            }
        else:
            left_legend = left["answer"].get("legend", {})
            right_legend = right["answer"].get("legend", {})
            if not isinstance(left_legend, dict) or not isinstance(
                right_legend, dict
            ):
                continue
            right_by_label = {
                right_legend[str(index)]: right_probabilities[str(index)]
                for index in range(len(right_probabilities))
            }
            left_labels = [
                left_legend[str(index)]
                for index in range(len(left_probabilities))
            ]
            right_values = {
                str(index): right_by_label[left_labels[index]]
                for index in range(len(left_probabilities))
            }
        total_variation = 0.5 * sum(
            abs(float(left_probabilities[key]) - float(right_values[key]))
            for key in left_probabilities
        )
        if left["type"] == "choice":
            selected_changed = (
                left["answer"].get("choice")
                != right["answer"].get("choice")
            )
        else:
            left_legend = left["answer"].get("legend", {})
            right_legend = right["answer"].get("legend", {})
            left_selected = (
                left_legend.get(selected_probability_label(left["answer"]))
                if isinstance(left_legend, dict)
                else None
            )
            right_selected = (
                right_legend.get(selected_probability_label(right["answer"]))
                if isinstance(right_legend, dict)
                else None
            )
            selected_changed = left_selected != right_selected
        comparisons.append(
            {
                "id": row_id,
                "type": left["type"],
                "selected_changed": selected_changed,
                "total_variation": total_variation,
            }
        )
    if not comparisons:
        return {
            "count": 0,
            "selected_changed_count": 0,
            "selected_changed_rate": None,
            "mean_total_variation": None,
            "max_total_variation": None,
            "rows": [],
        }
    return {
        "count": len(comparisons),
        "selected_changed_count": sum(
            item["selected_changed"] for item in comparisons
        ),
        "selected_changed_rate": sum(
            item["selected_changed"] for item in comparisons
        )
        / len(comparisons),
        "mean_total_variation": sum(
            item["total_variation"] for item in comparisons
        )
        / len(comparisons),
        "max_total_variation": max(
            item["total_variation"] for item in comparisons
        ),
        "rows": comparisons,
    }


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
