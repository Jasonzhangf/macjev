from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluation.runner import build_request, file_sha256, write_evidence


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


if __name__ == "__main__":
    unittest.main()
