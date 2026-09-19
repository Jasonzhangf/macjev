"""Evaluate MacJev as a structured browser-action selector."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from macjev.backends.diffgemma import DiffGemmaBackend
from macjev.service import DecisionService


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"row {line_number} must be an object")
        for key in (
            "id",
            "scenario",
            "trajectory_id",
            "step",
            "goal",
            "state",
            "actions",
            "expected",
            "valid_actions",
        ):
            if key not in row:
                raise ValueError(f"row {line_number} is missing {key}")
        if not isinstance(row["actions"], list) or len(row["actions"]) < 2:
            raise ValueError(f"row {line_number}.actions must have 2+ items")
        labels = [item["label"] for item in row["actions"]]
        if row["expected"] not in labels:
            raise ValueError(f"row {line_number}.expected is not an action")
        valid_actions = row["valid_actions"]
        if not isinstance(valid_actions, list):
            raise ValueError(f"row {line_number}.valid_actions must be an array")
        if row["expected"] not in valid_actions:
            raise ValueError(f"row {line_number}.expected is not valid")
        if not set(valid_actions) <= set(labels):
            raise ValueError(
                f"row {line_number}.valid_actions contains an unknown action"
            )
        rows.append(row)
    if not rows:
        raise ValueError("browser action dataset is empty")
    schemas: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        actions = row["actions"]
        previous = schemas.setdefault(row["trajectory_id"], actions)
        if actions != previous:
            raise ValueError(
                f"trajectory {row['trajectory_id']} changes its action schema"
            )
    return rows


def build_request(
    row: dict[str, Any],
    *,
    question_id: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    criteria = {
        item["label"]: item["description"] for item in row["actions"]
    }
    return {
        "model": "jev-latest",
        "state": {
            "goal": row["goal"],
            **state,
        },
        "questions": {
            question_id: {
                "type": "choice",
                "instructions": (
                    "Choose exactly one browser action. Return the action "
                    "label that should be executed next."
                ),
                "criteria": criteria,
            }
        },
        "options": {"samples": 1},
    }


def _timing(result: dict[str, Any]) -> dict[str, Any] | None:
    diagnostics = result.get("diagnostics")
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


def _record(
    row: dict[str, Any],
    *,
    mode: str,
    question_id: str,
    selected: str | None,
    probabilities: dict[str, float],
    timing: dict[str, Any] | None,
    latency_ms: float,
    error: str | None = None,
) -> dict[str, Any]:
    valid_actions = set(row["valid_actions"])
    return {
        "id": row["id"],
        "scenario": row["scenario"],
        "trajectory_id": row["trajectory_id"],
        "step": row["step"],
        "mode": mode,
        "question_id": question_id,
        "expected": row["expected"],
        "selected": selected,
        "correct": selected == row["expected"],
        "valid_target": selected in valid_actions if selected else False,
        "probabilities": probabilities,
        "timing": timing,
        "latency_ms": latency_ms,
        **({"error": error} if error else {}),
    }


def _state_for(
    row: dict[str, Any],
    *,
    mode: str,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    if mode in {"fresh_schema", "stable_schema"}:
        return {"page": row["state"]}
    return {
        "trajectory": history,
        "page": row["state"],
    }


def run_rows(
    rows: list[dict[str, Any]],
    *,
    upstream: str = "http://127.0.0.1:8080",
    timeout_seconds: float = 180.0,
    run_id: str = "browser-eval",
    modes: tuple[str, ...] = (
        "fresh_schema",
        "stable_schema",
        "continuous_history",
        "schema_churn_history",
    ),
) -> list[dict[str, Any]]:
    backend = DiffGemmaBackend(
        base_url=upstream,
        timeout_seconds=timeout_seconds,
    )
    service = DecisionService(backend)
    output: list[dict[str, Any]] = []

    for mode in modes:
        histories: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            trajectory_id = row["trajectory_id"]
            history = histories.setdefault(trajectory_id, [])
            if mode in {"stable_schema", "continuous_history"}:
                question_id = f"browser-{run_id}-{mode}-{trajectory_id}"
            else:
                question_id = f"browser-{run_id}-{mode}-{row['id']}"
            state = _state_for(row, mode=mode, history=history)
            request = build_request(
                row,
                question_id=question_id,
                state=state,
            )
            started = time.perf_counter()
            try:
                result = service.decide(request)
                latency_ms = (time.perf_counter() - started) * 1000.0
                answer = result["answers"][question_id]
                selected = answer.get("choice")
                probabilities = {
                    str(key): float(value)
                    for key, value in answer.get("probabilities", {}).items()
                }
                record = _record(
                    row,
                    mode=mode,
                    question_id=question_id,
                    selected=selected if isinstance(selected, str) else None,
                    probabilities=probabilities,
                    timing=_timing(result),
                    latency_ms=latency_ms,
                )
            except Exception as exc:
                latency_ms = (time.perf_counter() - started) * 1000.0
                record = _record(
                    row,
                    mode=mode,
                    question_id=question_id,
                    selected=None,
                    probabilities={},
                    timing=None,
                    latency_ms=latency_ms,
                    error=str(exc),
                )
            output.append(record)
            history.append(
                {
                    "step": row["step"],
                    "observed_page": row["state"],
                    "action": row["expected"],
                }
            )
    return output


def _phase_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    complete = [float(record["latency_ms"]) for record in records]
    timed = [
        record
        for record in records
        if isinstance(record.get("timing"), dict)
    ]
    prefill = [float(record["timing"]["prefill_ms"]) for record in timed]
    denoise = [float(record["timing"]["denoise_ms"]) for record in timed]
    non_prefill = [
        max(0.0, float(record["latency_ms"]) - float(record["timing"]["prefill_ms"]))
        for record in timed
    ]
    prompt_tokens = [
        float(record["timing"]["prompt_tokens"])
        for record in timed
        if isinstance(record["timing"].get("prompt_tokens"), (int, float))
    ]
    reused_tokens = [
        float(record["timing"]["reused_tokens"])
        for record in timed
        if isinstance(record["timing"].get("reused_tokens"), (int, float))
    ]
    return {
        "count": len(records),
        "errors": sum("error" in record for record in records),
        "complete_ms": {
            "p50": percentile(complete, 0.50),
            "p95": percentile(complete, 0.95),
            "mean": sum(complete) / len(complete) if complete else None,
        },
        "prefill_ms": {
            "p50": percentile(prefill, 0.50),
            "p95": percentile(prefill, 0.95),
            "mean": sum(prefill) / len(prefill) if prefill else None,
        },
        "non_prefill_ms": {
            "p50": percentile(non_prefill, 0.50),
            "p95": percentile(non_prefill, 0.95),
            "mean": (
                sum(non_prefill) / len(non_prefill)
                if non_prefill
                else None
            ),
        },
        "denoise_ms": {
            "p50": percentile(denoise, 0.50),
            "p95": percentile(denoise, 0.95),
            "mean": sum(denoise) / len(denoise) if denoise else None,
        },
        "prompt_tokens": {
            "p50": percentile(prompt_tokens, 0.50),
            "mean": (
                sum(prompt_tokens) / len(prompt_tokens)
                if prompt_tokens
                else None
            ),
        },
        "reused_tokens": {
            "p50": percentile(reused_tokens, 0.50),
            "mean": (
                sum(reused_tokens) / len(reused_tokens)
                if reused_tokens
                else None
            ),
            "positive_count": sum(value > 0 for value in reused_tokens),
        },
    }


def _accuracy_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [record for record in records if "error" not in record]
    correct = sum(record["correct"] for record in completed)
    valid = sum(record["valid_target"] for record in completed)
    top2 = 0
    for record in completed:
        ranked = sorted(
            record["probabilities"],
            key=record["probabilities"].__getitem__,
            reverse=True,
        )
        top2 += record["expected"] in ranked[:2]
    return {
        "attempts": len(records),
        "completed": len(completed),
        "errors": len(records) - len(completed),
        "accuracy": correct / len(completed) if completed else None,
        "top2_accuracy": top2 / len(completed) if completed else None,
        "valid_target_rate": valid / len(completed) if completed else None,
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_mode: dict[str, list[dict[str, Any]]] = {}
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_mode.setdefault(record["mode"], []).append(record)
        by_scenario.setdefault(record["scenario"], []).append(record)
    modes = {}
    for mode, group in sorted(by_mode.items()):
        modes[mode] = {
            "accuracy": _accuracy_summary(group),
            "speed": _phase_summary(group),
        }
    scenarios = {}
    for scenario, group in sorted(by_scenario.items()):
        scenarios[scenario] = {
            "accuracy": _accuracy_summary(group),
            "speed": _phase_summary(group),
        }

    paired: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for record in records:
        paired.setdefault(
            (record["trajectory_id"], int(record["step"])), {}
        )[record["mode"]] = record
    comparisons = []
    for key, group in sorted(paired.items()):
        comparison = {
            "trajectory_id": key[0],
            "step": key[1],
        }
        for mode, record in sorted(group.items()):
            timing = record.get("timing")
            comparison[f"{mode}_reused_tokens"] = (
                timing.get("reused_tokens") if timing else None
            )
            comparison[f"{mode}_prefill_ms"] = (
                timing.get("prefill_ms") if timing else None
            )
            comparison[f"{mode}_non_prefill_ms"] = (
                record["latency_ms"] - timing["prefill_ms"]
                if timing
                else None
            )
            comparison[f"{mode}_denoise_ms"] = (
                timing.get("denoise_ms") if timing else None
            )
            comparison[f"{mode}_complete_ms"] = record["latency_ms"]
        comparisons.append(comparison)
    followup_comparisons = [
        comparison for comparison in comparisons if comparison["step"] > 0
    ]
    return {
        "record_count": len(records),
        "modes": modes,
        "scenarios": scenarios,
        "context_comparisons": {
            "pairs": comparisons,
            "count": len(comparisons),
            "all_steps": _context_comparisons(comparisons),
            "followup_steps": _context_comparisons(followup_comparisons),
        },
    }


def _context_comparisons(
    pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "count": len(pairs),
        "stable_schema_vs_fresh_schema": _comparison(
            pairs,
            "fresh_schema",
            "stable_schema",
        ),
        "continuous_history_vs_stable_schema": _comparison(
            pairs,
            "stable_schema",
            "continuous_history",
        ),
        "continuous_history_vs_schema_churn_history": _comparison(
            pairs,
            "schema_churn_history",
            "continuous_history",
        ),
    }


def _comparison(
    pairs: list[dict[str, Any]],
    baseline: str,
    candidate: str,
) -> dict[str, Any]:
    result = {}
    for phase in ("prefill", "non_prefill", "denoise", "complete"):
        baseline_key = f"{baseline}_{phase}_ms"
        candidate_key = f"{candidate}_{phase}_ms"
        values = [
            float(pair[candidate_key]) - float(pair[baseline_key])
            for pair in pairs
            if pair.get(baseline_key) is not None
            and pair.get(candidate_key) is not None
        ]
        result[f"{phase}_delta_ms"] = {
            "count": len(values),
            "mean_candidate_minus_baseline_ms": (
                sum(values) / len(values) if values else None
            ),
            "candidate_faster_count": sum(value < 0 for value in values),
        }
    return result
