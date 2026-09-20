"""Conversion between the Jev contract and the diffgemma schema."""

from __future__ import annotations

import math
from typing import Any

from .errors import SchemaError

MAX_CHOICE_CANDIDATES = 26
ALLOWED_TYPES = {"noul", "choice", "score"}
ALLOWED_OPTIONS = {
    "samples",
    "steps",
    "active",
    "hole",
    "fix_definite",
    "auto_threshold",
    "auto_max",
}


def is_data_image_url(value: Any) -> bool:
    """Return whether ``value`` is an inline data URL for an image."""

    return isinstance(value, str) and value.startswith("data:image/")


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError(f"{label} must be an object")
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{label} must be a non-empty string")
    return value


def _description(value: Any, label: str) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    raise SchemaError(f"{label} must be a string or null")


def build_diffgemma_schema(
    questions: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a Jev question map and convert it to a diffgemma schema."""

    questions = _require_mapping(questions, "questions")
    if not questions:
        raise SchemaError("questions must not be empty")

    converted: list[dict[str, Any]] = []
    for qid, raw_question in questions.items():
        qid = _require_text(qid, "question id")
        question = _require_mapping(raw_question, f"questions.{qid}")
        kind = _require_text(question.get("type"), f"questions.{qid}.type")
        if kind not in ALLOWED_TYPES:
            raise SchemaError(f"questions.{qid}.type is unsupported: {kind}")

        item: dict[str, Any] = {
            "id": qid,
            "type": kind,
            "instructions": _description(
                question.get("instructions"), f"questions.{qid}.instructions"
            ),
        }

        if kind == "noul":
            criteria = question.get("criteria")
            if criteria is not None:
                criteria = _require_mapping(criteria, f"questions.{qid}.criteria")
                unknown = set(criteria) - {"true", "false"}
                if unknown:
                    raise SchemaError(
                        f"questions.{qid}.criteria has unknown keys: {sorted(unknown)}"
                    )
        elif kind == "choice":
            criteria = _require_mapping(
                question.get("criteria"), f"questions.{qid}.criteria"
            )
            if len(criteria) < 2:
                raise SchemaError(f"questions.{qid}.criteria needs at least 2 options")
            if len(criteria) > MAX_CHOICE_CANDIDATES:
                raise SchemaError(
                    f"questions.{qid} has {len(criteria)} options; "
                    f"diffgemma supports at most {MAX_CHOICE_CANDIDATES}"
                )
            item["options"] = [
                {
                    "name": _require_text(name, f"questions.{qid}.criteria key"),
                    "description": _description(
                        description, f"questions.{qid}.criteria.{name}"
                    ),
                }
                for name, description in criteria.items()
            ]
        else:
            criteria = question.get("criteria")
            if not isinstance(criteria, list):
                raise SchemaError(f"questions.{qid}.criteria must be an array")
            if not 2 <= len(criteria) <= 10:
                raise SchemaError(f"questions.{qid}.criteria must contain 2 to 10 levels")
            item["levels"] = [
                _require_text(level, f"questions.{qid}.criteria[{index}]")
                for index, level in enumerate(criteria)
            ]

        converted.append(item)

    schema: dict[str, Any] = {"questions": converted}
    options = _require_mapping(options or {}, "options")
    unknown_options = set(options) - ALLOWED_OPTIONS
    if unknown_options:
        raise SchemaError(f"options has unknown keys: {sorted(unknown_options)}")

    for key, value in options.items():
        if key in {"steps", "active", "auto_max"}:
            if isinstance(value, bool) or not isinstance(value, int):
                raise SchemaError(f"options.{key} must be an integer")
        if key in {"auto_threshold"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SchemaError(f"options.{key} must be numeric")
            if not math.isfinite(float(value)):
                raise SchemaError(f"options.{key} must be finite")
        if key == "fix_definite" and not isinstance(value, bool):
            raise SchemaError("options.fix_definite must be a boolean")
        if key == "hole" and value not in {"noise", "pad", "label"}:
            raise SchemaError("options.hole must be noise, pad, or label")
        if key == "samples" and not (
            value == "auto" or (isinstance(value, int) and not isinstance(value, bool))
        ):
            raise SchemaError('options.samples must be "auto" or an integer')
        schema[key] = value

    return schema


def confidence(probabilities: list[float]) -> float:
    """Return normalized certainty for a candidate distribution."""

    if len(probabilities) < 2:
        return 1.0
    entropy = -sum(p * math.log(p) for p in probabilities if p > 0)
    return max(0.0, min(1.0, 1.0 - entropy / math.log(len(probabilities))))


def normalize_answers(
    questions: dict[str, Any], backend_response: dict[str, Any]
) -> dict[str, Any]:
    """Normalize a diffgemma structured response to stable Jev-shaped answers."""

    answers = _require_mapping(backend_response.get("answers"), "backend answers")
    missing = [qid for qid in questions if qid not in answers]
    if missing:
        raise SchemaError(f"backend omitted answers: {missing}")

    normalized: dict[str, Any] = {}
    for qid, question in questions.items():
        kind = question["type"]
        answer = _require_mapping(answers[qid], f"backend answers.{qid}")
        raw_probabilities = answer.get("probabilities")
        if not isinstance(raw_probabilities, dict) or not raw_probabilities:
            raise SchemaError(f"backend answers.{qid}.probabilities is missing")

        if kind == "noul":
            p_true = answer.get("noul")
            if isinstance(p_true, bool) or not isinstance(p_true, (int, float)):
                raise SchemaError(f"backend answers.{qid}.noul is missing")
            p_true = float(p_true)
            if not 0.0 <= p_true <= 1.0:
                raise SchemaError(f"backend answers.{qid}.noul is outside [0, 1]")
            normalized[qid] = {
                "type": "noul",
                "noul": p_true,
                "probabilities": {
                    "false": 1.0 - p_true,
                    "true": p_true,
                },
                "confidence": abs(2.0 * p_true - 1.0),
            }
            continue

        expected_labels = list(question["criteria"])
        if set(raw_probabilities) != set(expected_labels):
            raise SchemaError(
                f"backend answers.{qid}.probabilities must match the question candidates"
            )
        values = [float(raw_probabilities[label]) for label in expected_labels]
        total = sum(values)
        if total <= 0.0:
            raise SchemaError(f"backend answers.{qid}.probabilities sum to zero")
        values = [value / total for value in values]
        probabilities = dict(zip(expected_labels, values))
        selected = max(probabilities, key=probabilities.__getitem__)

        if kind == "choice":
            normalized[qid] = {
                "type": "choice",
                "choice": selected,
                "probabilities": probabilities,
                "confidence": confidence(values),
            }
        elif kind == "score":
            # diffgemma reports the expected level on a 1-based scale.
            # OpenJev's score contract is a 0-based expected index.
            raw_score = answer.get("score")
            if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
                raise SchemaError(f"backend answers.{qid}.score is missing")
            raw_score = float(raw_score)
            if not math.isfinite(raw_score) or not 1.0 <= raw_score <= len(values):
                raise SchemaError(f"backend answers.{qid}.score is outside the levels")
            normalized[qid] = {
                "type": "score",
                "score": raw_score - 1.0,
                "level": answer.get("level"),
                "legend": {
                    str(index): level
                    for index, level in enumerate(question["criteria"])
                },
                "probabilities": {str(index): value for index, value in enumerate(values)},
                "confidence": confidence(values),
            }
        else:
            raise SchemaError(f"unsupported question type: {kind}")

    return normalized
