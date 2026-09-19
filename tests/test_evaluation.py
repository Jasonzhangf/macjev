from __future__ import annotations

import math
import unittest

from evaluation.metrics import EvaluationError, evaluate_predictions


def record(
    row_id: str,
    *,
    answer: dict,
    label: object,
    split: str = "test",
    kind: str = "choice",
    cardinality: int = 2,
    source: str = "unit",
    scenario: str = "unit",
    latency_ms: float = 10.0,
) -> dict:
    return {
        "id": row_id,
        "split": split,
        "type": kind,
        "cardinality": cardinality,
        "source": source,
        "scenario": scenario,
        "answer": answer,
        "label": label,
        "latency_ms": latency_ms,
    }


class EvaluationMetricTests(unittest.TestCase):
    def test_perfect_choice_metrics(self) -> None:
        report = evaluate_predictions(
            [
                record(
                    "a",
                    answer={
                        "type": "choice",
                        "choice": "yes",
                        "confidence": 1.0,
                        "probabilities": {"yes": 1.0, "no": 0.0},
                    },
                    label="yes",
                ),
                record(
                    "b",
                    answer={
                        "type": "choice",
                        "choice": "no",
                        "confidence": 1.0,
                        "probabilities": {"yes": 0.0, "no": 1.0},
                    },
                    label="no",
                ),
            ]
        )
        self.assertEqual(report["overall"]["accuracy"], 1.0)
        self.assertEqual(report["overall"]["nll"], 0.0)
        self.assertEqual(report["overall"]["brier"], 0.0)
        self.assertEqual(report["overall"]["ece"], 0.0)
        self.assertEqual(report["overall"]["aurc"], 0.0)
        self.assertEqual(
            report["overall"]["coverage_risk"][0],
            {"coverage": 0.5, "count": 1, "risk": 0.0},
        )

    def test_known_probability_metrics(self) -> None:
        report = evaluate_predictions(
            [
                record(
                    "a",
                    answer={
                        "type": "noul",
                        "noul": 0.8,
                        "confidence": 0.8,
                        "probabilities": {"false": 0.2, "true": 0.8},
                    },
                    label=True,
                    kind="noul",
                ),
                record(
                    "b",
                    answer={
                        "type": "noul",
                        "noul": 0.6,
                        "confidence": 0.6,
                        "probabilities": {"false": 0.4, "true": 0.6},
                    },
                    label=False,
                    kind="noul",
                ),
            ]
        )
        self.assertAlmostEqual(report["overall"]["accuracy"], 0.5)
        self.assertAlmostEqual(
            report["overall"]["nll"],
            (-math.log(0.8) - math.log(0.4)) / 2,
        )
        self.assertAlmostEqual(report["overall"]["brier"], (0.08 + 0.72) / 2)
        self.assertAlmostEqual(report["overall"]["ece"], 0.4)
        self.assertEqual(report["overall"]["speed"]["count"], 2)
        self.assertEqual(report["overall"]["speed"]["p50_ms"], 10.0)
        self.assertIsNone(report["overall"]["speed"]["throughput_rps"])

    def test_uses_wall_clock_run_speed_for_throughput(self) -> None:
        item = record(
            "a",
            answer={
                "type": "noul",
                "noul": 0.9,
                "confidence": 0.9,
                "probabilities": {"false": 0.1, "true": 0.9},
            },
            label=True,
            kind="noul",
            latency_ms=800.0,
        )
        report = evaluate_predictions(
            [item],
            run_speed={
                "measured": {
                    "completed": 1,
                    "errors": 0,
                    "successful_rps": 2.0,
                    "wall_clock_ms": 500.0,
                }
            },
        )
        self.assertEqual(report["metric_version"], 2)
        self.assertEqual(report["overall"]["speed"]["throughput_rps"], 2.0)
        self.assertEqual(report["overall"]["speed"]["wall_clock_ms"], 500.0)

    def test_aurc_uses_high_confidence_first(self) -> None:
        report = evaluate_predictions(
            [
                record(
                    "high-correct",
                    answer={
                        "type": "noul",
                        "noul": 0.9,
                        "confidence": 0.9,
                        "probabilities": {"false": 0.1, "true": 0.9},
                    },
                    label=True,
                    kind="noul",
                ),
                record(
                    "low-wrong",
                    answer={
                        "type": "noul",
                        "noul": 0.6,
                        "confidence": 0.6,
                        "probabilities": {"false": 0.4, "true": 0.6},
                    },
                    label=False,
                    kind="noul",
                ),
            ]
        )
        self.assertAlmostEqual(report["overall"]["aurc"], 0.25)

    def test_choice_uses_public_probability_order(self) -> None:
        report = evaluate_predictions(
            [
                record(
                    "a",
                    answer={
                        "type": "choice",
                        "choice": "b",
                        "confidence": 0.6,
                        "probabilities": {"a": 0.3, "b": 0.6, "c": 0.1},
                    },
                    label="b",
                    cardinality=3,
                )
            ]
        )
        self.assertEqual(report["overall"]["accuracy"], 1.0)
        self.assertAlmostEqual(report["overall"]["brier"], 0.26)

    def test_score_accuracy_uses_probability_mode(self) -> None:
        report = evaluate_predictions(
            [
                record(
                    "score-mode",
                    answer={
                        "type": "score",
                        "score": 0.6,
                        "confidence": 0.05,
                        "probabilities": {
                            "0": 0.40,
                            "1": 0.35,
                            "2": 0.25,
                        },
                    },
                    label=0,
                    kind="score",
                    cardinality=3,
                )
            ]
        )
        self.assertEqual(report["overall"]["accuracy"], 1.0)

    def test_speed_and_suitability_slices(self) -> None:
        report = evaluate_predictions(
            [
                record(
                    "a",
                    answer={
                        "type": "noul",
                        "noul": 0.9,
                        "confidence": 0.9,
                        "probabilities": {"false": 0.1, "true": 0.9},
                    },
                    label=True,
                    kind="noul",
                    scenario="short_text",
                    latency_ms=100.0,
                ),
                record(
                    "b",
                    answer={
                        "type": "noul",
                        "noul": 0.8,
                        "confidence": 0.8,
                        "probabilities": {"false": 0.2, "true": 0.8},
                    },
                    label=True,
                    kind="noul",
                    scenario="short_text",
                    latency_ms=300.0,
                ),
            ],
            thresholds={
                "minimum_samples": 2,
                "minimum_accuracy": 0.5,
                "preferred_accuracy": 0.8,
                "maximum_aurc": 0.5,
                "preferred_maximum_aurc": 0.2,
                "maximum_p95_ms": 1000.0,
                "preferred_p95_ms": 500.0,
            },
        )
        matrix = report["suitability_matrix"]["short_text"]
        self.assertEqual(matrix[0]["suitability"], "caution")
        self.assertAlmostEqual(matrix[0]["speed"]["p95_ms"], 290.0)

    def test_counts_errors_in_speed_and_suitability(self) -> None:
        item = record(
            "a",
            answer={
                "type": "noul",
                "noul": 0.9,
                "confidence": 0.9,
                "probabilities": {"false": 0.1, "true": 0.9},
            },
            label=True,
            kind="noul",
            scenario="short_text",
        )
        error = {
            "id": "b",
            "split": "test",
            "type": "noul",
            "cardinality": 2,
            "source": "unit",
            "scenario": "short_text",
            "error": "timeout",
        }
        report = evaluate_predictions([item], errors=[error])
        self.assertEqual(report["error_count"], 1)
        self.assertEqual(report["overall"]["attempts"], 2)
        self.assertEqual(report["overall"]["speed"]["errors"], 1)
        self.assertEqual(
            report["slices"]["scenario"]["short_text"]["speed"]["errors"],
            1,
        )

    def test_all_failed_run_emits_error_only_report(self) -> None:
        error = {
            "id": "a",
            "split": "test",
            "type": "noul",
            "cardinality": 2,
            "source": "unit",
            "scenario": "short_text",
            "error": "timeout",
        }
        report = evaluate_predictions([], errors=[error])
        self.assertEqual(report["count"], 0)
        self.assertEqual(report["error_count"], 1)
        self.assertIsNone(report["overall"]["accuracy"])
        self.assertEqual(report["overall"]["speed"]["errors"], 1)
        self.assertEqual(report["overall"]["suitability"], "unsuitable")

    def test_rejects_mock_evidence(self) -> None:
        item = record(
            "a",
            answer={
                "type": "noul",
                "noul": 0.8,
                "confidence": 0.8,
                "probabilities": {"false": 0.2, "true": 0.8},
            },
            label=True,
            kind="noul",
        )
        item["is_mock"] = True
        with self.assertRaises(EvaluationError):
            evaluate_predictions([item])


if __name__ == "__main__":
    unittest.main()
