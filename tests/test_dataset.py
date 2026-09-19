from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluation.dataset import DatasetError, load_rows


class DatasetTests(unittest.TestCase):
    def test_rejects_cardinality_mismatch(self) -> None:
        row = {
            "id": "choice-1",
            "split": "test",
            "type": "choice",
            "cardinality": 2,
            "state": "outage",
            "question": {
                "instructions": "Which team?",
                "criteria": {"a": "A", "b": "B", "c": "C"},
            },
            "label": "a",
            "source": "unit",
            "scenario": "short_text",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(DatasetError, "cardinality must be 3"):
                load_rows(path)

    def test_accepts_noul_cardinality(self) -> None:
        row = {
            "id": "noul-1",
            "split": "test",
            "type": "noul",
            "cardinality": 2,
            "state": "outage",
            "question": {"instructions": "Is it urgent?"},
            "label": True,
            "source": "unit",
            "scenario": "short_text",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            self.assertEqual(load_rows(path)[0]["id"], "noul-1")
