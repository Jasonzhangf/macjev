from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluation.runner import (
    _canonicalize_answer,
    _timing_metrics,
    add_timing_metrics,
    build_request,
    file_sha256,
    option_order_sensitivity,
    run_rows,
    summarize_run_speed,
    write_evidence,
)
from macjev.backends.base import DecisionBackend


class CountingBackend(DecisionBackend):
    name = "counting-test"

    def __init__(self) -> None:
        self.calls = 0

    def decide(
        self,
        state: object,
        schema: dict,
        images: list[dict] | None = None,
    ) -> dict:
        self.calls += 1
        answer = {
            "type": "choice",
            "choice": "b",
            "probabilities": {"a": 0.25, "b": 0.75},
        }
        if schema["questions"][0]["options"][0]["name"] == "b":
            answer = {
                "type": "choice",
                "choice": "b",
                "probabilities": {"a": 0.75, "b": 0.25},
            }
        return {
            "answers": {"choice-1": answer},
            "diagnostics": {"timing": {"prefill_ms": 1, "denoise_ms": 2}},
        }


class RunnerTests(unittest.TestCase):
    def test_builds_jev_request(self) -> None:
        row = {
            "id": "choice-1",
            "type": "choice",
            "state": "Outage",
            "question": {
                "instructions": "Which team?",
                "criteria": {"support": "Account", "engineering": "Outage"},
            },
        }
        request = build_request(row)
        self.assertEqual(request["model"], "jev-latest")
        self.assertEqual(
            request["questions"]["choice-1"]["criteria"],
            {"support": "Account", "engineering": "Outage"},
        )

    def test_writes_hashed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = root / "rows.jsonl"
            rows.write_text('{"id":"a"}\n', encoding="utf-8")
            output = root / "out"
            write_evidence(
                output,
                rows_path=rows,
                records=[{"id": "a"}],
                errors=[{"id": "b", "error": "timeout"}],
                report={"count": 1},
                provenance={"git_head": "abc"},
            )
            self.assertTrue(
                (output / "dataset.sha256").read_text().startswith(
                    file_sha256(rows)
                )
            )
            self.assertEqual(
                json.loads((output / "report.json").read_text())["count"],
                1,
            )
            self.assertIn("timeout", (output / "errors.jsonl").read_text())

    def test_writes_perturbation_evidence_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = root / "rows.jsonl"
            rows.write_text('{"id":"a"}\n', encoding="utf-8")
            output = root / "out"
            write_evidence(
                output,
                rows_path=rows,
                records=[{"id": "a", "option_order": "canonical"}],
                errors=[],
                perturbation_records=[
                    {"id": "a", "option_order": "reversed"}
                ],
                perturbation_errors=[],
                report={"count": 1},
                provenance={"git_head": "abc"},
            )
            self.assertIn(
                '"reversed"',
                (output / "perturbation_records.jsonl").read_text(),
            )
            self.assertEqual(
                (output / "records.jsonl").read_text().count("reversed"),
                0,
            )

    def test_option_order_sensitivity_maps_choice_labels(self) -> None:
        canonical = {
            "id": "choice-1",
            "type": "choice",
            "option_order": "canonical",
            "answer": {
                "choice": "a",
                "probabilities": {"a": 0.7, "b": 0.3},
            },
        }
        reversed_record = {
            "id": "choice-1",
            "type": "choice",
            "option_order": "reversed",
            "answer": {
                "choice": "b",
                "probabilities": {"a": 0.2, "b": 0.8},
            },
        }
        result = option_order_sensitivity([canonical, reversed_record])
        self.assertEqual(result["selected_changed_count"], 1)
        self.assertAlmostEqual(result["mean_total_variation"], 0.5)

    def test_canonicalizes_reversed_score_answer(self) -> None:
        row = {
            "id": "score-1",
            "type": "score",
            "question": {
                "instructions": "How severe?",
                "criteria": ["low", "medium", "high"],
            },
        }
        answer = {
            "type": "score",
            "score": 1.8,
            "level": "low",
            "legend": {"0": "high", "1": "medium", "2": "low"},
            "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7},
            "confidence": 0.5,
        }
        result = _canonicalize_answer(row, "reversed", answer)
        self.assertAlmostEqual(result["score"], 0.2)
        self.assertEqual(
            result["legend"],
            {"0": "low", "1": "medium", "2": "high"},
        )
        self.assertEqual(
            result["probabilities"],
            {"0": 0.7, "1": 0.2, "2": 0.1},
        )

    def test_option_order_sensitivity_maps_score_semantics(self) -> None:
        canonical = {
            "id": "score-1",
            "type": "score",
            "option_order": "canonical",
            "answer": {
                "score": 0.2,
                "legend": {"0": "low", "1": "medium", "2": "high"},
                "probabilities": {"0": 0.7, "1": 0.2, "2": 0.1},
            },
        }
        reversed_record = {
            "id": "score-1",
            "type": "score",
            "option_order": "reversed",
            "answer": {
                "score": 1.8,
                "legend": {"0": "high", "1": "medium", "2": "low"},
                "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7},
            },
        }
        result = option_order_sensitivity([canonical, reversed_record])
        self.assertEqual(result["selected_changed_count"], 0)
        self.assertAlmostEqual(result["mean_total_variation"], 0.0)

    def test_reversed_probes_do_not_change_primary_run_metrics(self) -> None:
        backend = CountingBackend()
        rows = [
            {
                "id": "choice-1",
                "split": "test",
                "type": "choice",
                "cardinality": 2,
                "scenario": "unit",
                "source": "unit",
                "state": "state",
                "question": {
                    "instructions": "Pick one",
                    "criteria": {"a": "A", "b": "B"},
                },
                "label": "b",
            }
        ]
        original = run_rows.__globals__["DiffGemmaBackend"]
        run_rows.__globals__["DiffGemmaBackend"] = lambda **_: backend
        try:
            records, errors, speed = run_rows(
                rows,
                base_url="http://unused",
                timeout_seconds=1,
                warmup=0,
                repeats=1,
                concurrency=1,
                in_process=True,
                reverse_options=True,
            )
        finally:
            run_rows.__globals__["DiffGemmaBackend"] = original

        self.assertEqual(len(records), 1)
        self.assertEqual(errors, [])
        self.assertEqual(speed["measured"]["attempts"], 1)
        self.assertEqual(speed["measured"]["completed"], 1)
        self.assertEqual(speed["perturbation"]["attempts"], 1)
        self.assertEqual(speed["perturbation"]["completed"], 1)
        self.assertEqual(backend.calls, 2)

    def test_option_order_sensitivity_pairs_each_repeat(self) -> None:
        records = []
        for repeat, reversed_choice in ((0, "b"), (1, "a")):
            records.append(
                {
                    "id": "choice-1",
                    "repeat": repeat,
                    "type": "choice",
                    "option_order": "canonical",
                    "answer": {
                        "choice": "a",
                        "probabilities": {"a": 0.8, "b": 0.2},
                    },
                }
            )
            records.append(
                {
                    "id": "choice-1",
                    "repeat": repeat,
                    "type": "choice",
                    "option_order": "reversed",
                    "answer": {
                        "choice": reversed_choice,
                        "probabilities": {"a": 0.2, "b": 0.8},
                    },
                }
            )

        result = option_order_sensitivity(records)

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["selected_changed_count"], 1)
        self.assertEqual(
            [row["repeat"] for row in result["rows"]],
            [0, 1],
        )

    def test_summarizes_wall_clock_throughput(self) -> None:
        result = summarize_run_speed(
            attempts=4,
            completed=3,
            errors=1,
            elapsed_ms=2000.0,
            warmup_latencies_ms=[600.0, 400.0],
            concurrency=2,
            repeats=1,
            latency_scope="request_to_complete_public_json_response",
        )
        self.assertEqual(result["measured"]["attempted_rps"], 2.0)
        self.assertEqual(result["measured"]["successful_rps"], 1.5)
        self.assertEqual(result["measured"]["error_rate"], 0.25)
        self.assertEqual(result["warmup"]["first_request_ms"], 600.0)
        self.assertEqual(
            result["ttft"]["status"],
            "unavailable_non_streaming_response",
        )

    def test_reports_prefill_and_denoise_separately(self) -> None:
        result = _timing_metrics(
            [
                {
                    "latency_ms": 1000.0,
                    "timing": {
                        "prefill_ms": 600.0,
                        "denoise_ms": 300.0,
                        "prompt_tokens": 120,
                        "reused_tokens": 0,
                        "samples": 1,
                        "rounds": 1,
                        "steps_run": 1,
                    },
                },
                {
                    "latency_ms": 800.0,
                    "timing": {
                        "prefill_ms": 200.0,
                        "denoise_ms": 500.0,
                        "prompt_tokens": 120,
                        "reused_tokens": 100,
                        "samples": 4,
                        "rounds": 4,
                        "steps_run": 4,
                    },
                },
            ]
        )
        self.assertEqual(result["prefill_ms"]["p50"], 400.0)
        self.assertEqual(result["denoise_ms"]["p50"], 400.0)
        self.assertEqual(result["request_breakdown"]["count"], 2)
        self.assertAlmostEqual(result["request_breakdown"]["prefill_share"], 0.4444444444)
        self.assertAlmostEqual(
            result["request_breakdown"]["non_prefill_share"],
            0.5555555556,
        )
        self.assertAlmostEqual(result["request_breakdown"]["denoise_share"], 0.4444444444)
        self.assertEqual(result["request_breakdown"]["non_prefill_p50_ms"], 500.0)
        self.assertEqual(result["prefill_cache"]["fresh_p50_ms"], 600.0)
        self.assertEqual(result["prefill_cache"]["reused_p50_ms"], 200.0)

    def test_rebuilds_timing_slices_from_records(self) -> None:
        records = [
            {
                "scenario": "short_text",
                "type": "score",
                "latency_ms": 1000.0,
                "timing": {
                    "prefill_ms": 600.0,
                    "denoise_ms": 300.0,
                    "samples": 1,
                },
            }
        ]
        speed = {"timing": {"stale": True}}
        add_timing_metrics(speed, records)
        self.assertEqual(
            speed["timing"]["request_breakdown"]["non_prefill_p50_ms"],
            400.0,
        )
        self.assertIn("short_text", speed["timing_slices"]["scenario"])
        self.assertIn("1", speed["timing_slices"]["samples"])


if __name__ == "__main__":
    unittest.main()
