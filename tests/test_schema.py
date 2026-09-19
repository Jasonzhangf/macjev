from __future__ import annotations

import unittest

from macjev.errors import SchemaError
from macjev.schema import build_diffgemma_schema


class SchemaTests(unittest.TestCase):
    def test_builds_supported_schema(self) -> None:
        schema = build_diffgemma_schema(
            {
                "urgent": {"type": "noul", "instructions": "Urgent?"},
                "team": {
                    "type": "choice",
                    "instructions": "Team?",
                    "criteria": {"billing": "Billing", "engineering": "Outage"},
                },
                "tone": {
                    "type": "score",
                    "instructions": "Tone?",
                    "criteria": ["calm", "annoyed", "furious"],
                },
            },
            {"samples": "auto"},
        )

        self.assertEqual(schema["samples"], "auto")
        self.assertEqual(schema["questions"][1]["options"][1]["name"], "engineering")
        self.assertEqual(schema["questions"][2]["levels"][2], "furious")

    def test_rejects_large_choice(self) -> None:
        with self.assertRaises(SchemaError):
            build_diffgemma_schema(
                {
                    "team": {
                        "type": "choice",
                        "criteria": {f"option_{i}": str(i) for i in range(27)},
                    }
                }
            )

    def test_rejects_unknown_option(self) -> None:
        with self.assertRaises(SchemaError):
            build_diffgemma_schema(
                {"urgent": {"type": "noul", "instructions": "Urgent?"}},
                {"unknown": 1},
            )


if __name__ == "__main__":
    unittest.main()
