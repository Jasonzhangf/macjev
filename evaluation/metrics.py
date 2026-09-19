"""Pure-stdlib probability and risk metrics for MacJev evaluation."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable


class EvaluationError(ValueError):
    """Prediction evidence is malformed or not evaluable."""


def _probabilities(record: dict[str, Any]) -> list[float]:
    answer = record["answer"]
    if not isinstance(answer, dict):
        raise EvaluationError(f"{record['id']}: answer must be an object")
    if answer.get("type") == "noul":
        raw = answer.get("probabilities")
        if not isinstance(raw, dict):
            raise EvaluationError(f"{record['id']}: probabilities missing")
        values = [float(raw["false"]), float(raw["true"])]
    else:
        raw = answer.get("probabilities")
        if not isinstance(raw, dict) or not raw:
            raise EvaluationError(f"{record['id']}: probabilities missing")
        values = [float(value) for value in raw.values()]

    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise EvaluationError(f"{record['id']}: invalid probability")
    total = sum(values)
    if total <= 0.0:
        raise EvaluationError(f"{record['id']}: probabilities sum to zero")
    return [value / total for value in values]


def _observed_index(record: dict[str, Any]) -> int:
    answer = record["answer"]
    label = record["label"]
    if answer.get("type") == "noul":
        if not isinstance(label, bool):
            raise EvaluationError(f"{record['id']}: noul label must be boolean")
        return 1 if label else 0
    if answer.get("type") == "score":
        if not isinstance(label, int) or isinstance(label, bool):
            raise EvaluationError(f"{record['id']}: score label must be integer")
        if label < 0 or label >= len(answer["probabilities"]):
            raise EvaluationError(f"{record['id']}: score label is out of range")
        return label
    labels = list(answer["probabilities"])
    if label not in labels:
        raise EvaluationError(f"{record['id']}: choice label is not a candidate")
    return labels.index(label)


def _selected_index(record: dict[str, Any], probabilities: list[float]) -> int:
    answer = record["answer"]
    if answer.get("type") == "noul":
        selected = bool(answer.get("noul", 0.0) >= 0.5)
        return int(selected)
    if answer.get("type") == "score":
        score = answer.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise EvaluationError(f"{record['id']}: score missing")
        index = round(float(score))
        if index < 0 or index >= len(probabilities):
            raise EvaluationError(f"{record['id']}: score is out of range")
        return index
    labels = list(answer["probabilities"])
    selected = answer.get("choice")
    if selected not in labels:
        raise EvaluationError(f"{record['id']}: selected choice is not a candidate")
    return labels.index(selected)


def _ece(
    confidences: list[float], correct: list[bool], bins: int = 10
) -> tuple[float, list[dict[str, Any]]]:
    details = []
    total = len(confidences)
    value = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [
            i
            for i, confidence in enumerate(confidences)
            if lower <= confidence < upper
            or (index == bins - 1 and confidence == 1.0)
        ]
        if not members:
            details.append(
                {
                    "lower": lower,
                    "upper": upper,
                    "count": 0,
                    "confidence": None,
                    "accuracy": None,
                }
            )
            continue
        mean_confidence = sum(confidences[i] for i in members) / len(members)
        accuracy = sum(1 for i in members if correct[i]) / len(members)
        value += len(members) / total * abs(accuracy - mean_confidence)
        details.append(
            {
                "lower": lower,
                "upper": upper,
                "count": len(members),
                "confidence": mean_confidence,
                "accuracy": accuracy,
            }
        )
    return value, details


def _aurc(confidences: list[float], correct: list[bool]) -> float:
    ordered = sorted(range(len(correct)), key=lambda index: confidences[index])
    errors = 0
    area = 0.0
    for rank, index in enumerate(ordered, start=1):
        errors += int(not correct[index])
        area += errors / rank
    return area / len(ordered)


def _coverage_risk(
    confidences: list[float],
    correct: list[bool],
    coverages: Iterable[float],
) -> list[dict[str, float | int]]:
    ordered = sorted(
        range(len(correct)), key=lambda index: confidences[index], reverse=True
    )
    points: list[dict[str, float | int]] = []
    for coverage in coverages:
        if not 0.0 < coverage <= 1.0:
            raise EvaluationError("coverage must be in (0, 1]")
        count = max(1, math.ceil(coverage * len(ordered)))
        retained = ordered[:count]
        points.append(
            {
                "coverage": count / len(ordered),
                "count": count,
                "risk": sum(1 for index in retained if not correct[index]) / count,
            }
        )
    return points


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise EvaluationError("cannot compute a percentile without values")
    if not 0.0 <= percentile <= 1.0:
        raise EvaluationError("percentile must be in [0, 1]")
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


def _speed_metrics(
    records: list[dict[str, Any]], error_count: int = 0
) -> dict[str, Any]:
    latencies = [float(record["latency_ms"]) for record in records]
    if any(not math.isfinite(value) or value < 0.0 for value in latencies):
        raise EvaluationError("latency_ms must be finite and non-negative")
    measured = [value for value in latencies if value > 0.0]
    if not measured:
        raise EvaluationError("no measured latency values")
    elapsed_seconds = sum(measured) / 1000.0
    return {
        "count": len(measured),
        "errors": error_count + sum(bool(record.get("error")) for record in records),
        "p50_ms": _percentile(measured, 0.50),
        "p90_ms": _percentile(measured, 0.90),
        "p95_ms": _percentile(measured, 0.95),
        "p99_ms": _percentile(measured, 0.99),
        "mean_ms": sum(measured) / len(measured),
        "min_ms": min(measured),
        "max_ms": max(measured),
        "throughput_rps": len(measured) / elapsed_seconds,
    }


def _suitability(
    metrics: dict[str, Any],
    speed: dict[str, Any],
    thresholds: dict[str, Any],
) -> str:
    minimum_samples = int(thresholds["minimum_samples"])
    if metrics["count"] < minimum_samples:
        return "inconclusive"
    if speed["errors"] > 0:
        return "unsuitable"
    if (
        metrics["accuracy"] < float(thresholds["minimum_accuracy"])
        or metrics["aurc"] > float(thresholds["maximum_aurc"])
        or speed["p95_ms"] > float(thresholds["maximum_p95_ms"])
    ):
        return "unsuitable"
    if (
        metrics["count"] < minimum_samples * 2
        or metrics["accuracy"] < float(thresholds["preferred_accuracy"])
        or metrics["aurc"] > float(thresholds["preferred_maximum_aurc"])
        or speed["p95_ms"] > float(thresholds["preferred_p95_ms"])
    ):
        return "caution"
    return "suitable"


def _evaluate_group(
    records: list[dict[str, Any]],
    coverages: Iterable[float],
    thresholds: dict[str, Any] | None = None,
    error_count: int = 0,
) -> dict[str, Any]:
    confidences: list[float] = []
    correct: list[bool] = []
    nll = 0.0
    brier = 0.0
    for record in records:
        probabilities = _probabilities(record)
        observed = _observed_index(record)
        selected = _selected_index(record, probabilities)
        observed_probability = max(probabilities[observed], 1e-12)
        nll -= math.log(observed_probability)
        brier += sum(
            (probability - int(index == observed)) ** 2
            for index, probability in enumerate(probabilities)
        )
        confidence = float(record["answer"].get("confidence", 0.0))
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise EvaluationError(f"{record['id']}: confidence must be in [0, 1]")
        confidences.append(confidence)
        correct.append(selected == observed)

    count = len(records)
    ece, ece_bins = _ece(confidences, correct)
    result = {
        "count": count,
        "accuracy": sum(correct) / count,
        "nll": nll / count,
        "brier": brier / count,
        "ece": ece,
        "ece_bins": ece_bins,
        "aurc": _aurc(confidences, correct),
        "coverage_risk": _coverage_risk(confidences, correct, coverages),
    }
    result["attempts"] = len(records) + error_count
    result["speed"] = _speed_metrics(records, error_count)
    if thresholds is not None:
        result["suitability"] = _suitability(result, result["speed"], thresholds)
    return result


def evaluate_predictions(
    records: list[dict[str, Any]],
    *,
    coverages: Iterable[float] = (0.5, 0.7, 0.9),
    thresholds: dict[str, Any] | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate normalized public answers against labelled rows."""

    if not records:
        raise EvaluationError("no prediction records")
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise EvaluationError("prediction record must have an id")
        if record.get("split") not in {"calibration", "test", "ood"}:
            raise EvaluationError(f"{record['id']}: invalid split")
        if record.get("type") not in {"noul", "choice", "score"}:
            raise EvaluationError(f"{record['id']}: invalid type")
        if not isinstance(record.get("scenario"), str) or not record["scenario"]:
            raise EvaluationError(f"{record['id']}: scenario is required")
        if isinstance(record.get("latency_ms"), bool) or not isinstance(
            record.get("latency_ms"), (int, float)
        ):
            raise EvaluationError(f"{record['id']}: latency_ms is required")
        if record.get("is_mock"):
            raise EvaluationError(f"{record['id']}: mock output is not model evidence")

    thresholds = thresholds or {
        "minimum_samples": 1,
        "minimum_accuracy": 0.5,
        "preferred_accuracy": 0.8,
        "maximum_aurc": 0.5,
        "preferred_maximum_aurc": 0.2,
        "maximum_p95_ms": 30_000.0,
        "preferred_p95_ms": 5_000.0,
    }
    errors = errors or []
    for error in errors:
        if not isinstance(error, dict) or not isinstance(error.get("id"), str):
            raise EvaluationError("error record must have an id")
        for field in ("split", "type", "cardinality", "source", "scenario"):
            if field not in error:
                raise EvaluationError(f"error {error['id']}: {field} is required")

    def matching_errors(
        group_records: list[dict[str, Any]], dimension: str | None = None
    ) -> list[dict[str, Any]]:
        ids = {record["id"] for record in group_records}
        if dimension is None:
            return errors
        values = {record[dimension] for record in group_records}
        return [
            error
            for error in errors
            if error[dimension] in values and error["id"] in ids
        ]

    # Error rows are expected to carry the same slice fields as dataset rows.
    # They are grouped by stable row identity, not by a substring in an error.
    slices: dict[str, dict[str, Any]] = {}
    dimensions = ("split", "type", "cardinality", "source", "scenario")
    for dimension in dimensions:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            groups[str(record[dimension])].append(record)
        error_groups: dict[str, int] = defaultdict(int)
        for error in errors:
            error_groups[str(error[dimension])] += 1
        slices[dimension] = {
            value: _evaluate_group(
                group,
                coverages,
                thresholds,
                error_groups.get(value, 0),
            )
            for value, group in sorted(groups.items())
        }

    combined: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        combined[f"{record['split']}:{record['type']}"].append(record)
    split_type_errors: dict[str, int] = defaultdict(int)
    for error in errors:
        split_type_errors[f"{error['split']}:{error['type']}"] += 1
    slices["split_type"] = {
        value: _evaluate_group(
            group,
            coverages,
            thresholds,
            split_type_errors.get(value, 0),
        )
        for value, group in sorted(combined.items())
    }
    matrix: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        matrix[record["scenario"]].append(record)
    suitability_matrix: dict[str, list[dict[str, Any]]] = {}
    for scenario, scenario_records in sorted(matrix.items()):
        groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for record in scenario_records:
            groups[(record["type"], record["cardinality"])].append(record)
        matrix_errors: dict[tuple[str, int], int] = defaultdict(int)
        for error in errors:
            if error["scenario"] == scenario:
                matrix_errors[(error["type"], error["cardinality"])] += 1
        suitability_matrix[scenario] = [
            {
                "type": kind,
                "cardinality": cardinality,
                **_evaluate_group(
                    group,
                    coverages,
                    thresholds,
                    matrix_errors.get((kind, cardinality), 0),
                ),
            }
            for (kind, cardinality), group in sorted(groups.items())
        ]
    return {
        "metric_version": 1,
        "count": len(records),
        "error_count": len(errors),
        "policy_id": "evaluation-policy-v1",
        "thresholds": thresholds,
        "overall": _evaluate_group(
            records,
            coverages,
            thresholds,
            len(errors),
        ),
        "slices": slices,
        "suitability_matrix": suitability_matrix,
    }
