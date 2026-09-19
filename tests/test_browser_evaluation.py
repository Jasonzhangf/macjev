from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from evaluation.browser import (
    _phase_summary,
    build_request,
    load_rows,
    summarize,
)


class BrowserEvaluationTests(unittest.TestCase):
    def test_loads_fixture_and_builds_choice_request(self) -> None:
        rows = load_rows(
            Path(__file__).parents[1] / "fixtures/browser-actions-v1.jsonl"
        )
        request = build_request(
            rows[0],
            question_id="browser-test",
            state={"page": rows[0]["state"]},
        )
        self.assertEqual(request["questions"]["browser-test"]["type"], "choice")
        self.assertIn("CLICK:search", request["questions"]["browser-test"]["criteria"])
        self.assertEqual(request["state"]["page"]["url"], "http://fixture.local/home")

    def test_phase_summary_separates_prefill_and_non_prefill(self) -> None:
        records = [
            {
                "latency_ms": 1000.0,
                "timing": {
                    "prefill_ms": 600.0,
                    "denoise_ms": 300.0,
                    "prompt_tokens": 100,
                    "reused_tokens": 0,
                },
            },
            {
                "latency_ms": 700.0,
                "timing": {
                    "prefill_ms": 200.0,
                    "denoise_ms": 300.0,
                    "prompt_tokens": 150,
                    "reused_tokens": 100,
                },
            },
        ]
        result = _phase_summary(records)
        self.assertEqual(result["prefill_ms"]["p50"], 400.0)
        self.assertEqual(result["non_prefill_ms"]["p50"], 450.0)
        self.assertEqual(result["denoise_ms"]["p50"], 300.0)
        self.assertEqual(result["reused_tokens"]["positive_count"], 1)

    def test_summarize_pairs_context_modes(self) -> None:
        records = []
        for mode, prefill, latency in (
            ("fresh_schema", 600.0, 1000.0),
            ("stable_schema", 200.0, 600.0),
            ("continuous_history", 250.0, 650.0),
            ("schema_churn_history", 550.0, 950.0),
        ):
            records.append(
                {
                    "id": "a",
                    "scenario": "form",
                    "trajectory_id": "t",
                    "step": 0,
                    "mode": mode,
                    "expected": "DONE",
                    "selected": "DONE",
                    "correct": True,
                    "valid_target": True,
                    "probabilities": {"DONE": 1.0, "WAIT": 0.0},
                    "latency_ms": latency,
                    "timing": {
                        "prefill_ms": prefill,
                        "denoise_ms": 300.0,
                        "prompt_tokens": 100,
                        "reused_tokens": (
                            50
                            if mode in {"stable_schema", "continuous_history"}
                            else 0
                        ),
                    },
                }
            )
        result = summarize(records)
        self.assertEqual(
            result["context_comparisons"]["all_steps"][
                "stable_schema_vs_fresh_schema"
            ]["prefill_delta_ms"][
                "mean_candidate_minus_baseline_ms"
            ],
            -400.0,
        )
        self.assertEqual(
            result["context_comparisons"]["all_steps"][
                "continuous_history_vs_schema_churn_history"
            ]["complete_delta_ms"][
                "candidate_faster_count"
            ],
            1,
        )

    def test_rejects_schema_changes_inside_a_trajectory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"id":"a","scenario":"x","trajectory_id":"t","step":0,'
                        '"goal":"g","state":{},"actions":[{"label":"A",'
                        '"description":"a"},{"label":"B","description":"b"}],'
                        '"expected":"A","valid_actions":["A"]}',
                        '{"id":"b","scenario":"x","trajectory_id":"t","step":1,'
                        '"goal":"g","state":{},"actions":[{"label":"A",'
                        '"description":"a"},{"label":"C","description":"c"}],'
                        '"expected":"A","valid_actions":["A"]}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "changes its action schema"):
                load_rows(path)


if __name__ == "__main__":
    unittest.main()
