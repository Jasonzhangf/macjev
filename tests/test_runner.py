from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluation.runner import (
    _timing_metrics,
    build_request,
    file_sha256,
    option_order_sensitivity,
    summarize_run_speed,
    write_evidence,
)


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
        self.assertAlmostEqual(result["request_breakdown"]["denoise_share"], 0.4444444444)
        self.assertEqual(result["prefill_cache"]["fresh_p50_ms"], 600.0)
        self.assertEqual(result["prefill_cache"]["reused_p50_ms"], 200.0)


if __name__ == "__main__":
    unittest.main()
