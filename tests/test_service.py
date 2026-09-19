from __future__ import annotations

import unittest

from macjev.backends.mock import MockBackend
from macjev.errors import UnsupportedFeature
from macjev.schema import normalize_answers
from macjev.service import DecisionService


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DecisionService(MockBackend())

    def test_normalizes_all_question_types(self) -> None:
        result = self.service.decide(
            {
                "state": "Production outage with 500 responses.",
                "questions": {
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
            }
        )

        self.assertGreater(result["answers"]["urgent"]["noul"], 0.8)
        self.assertEqual(result["answers"]["team"]["choice"], "billing")
        self.assertEqual(result["answers"]["tone"]["score"], 1.0)
        self.assertEqual(result["answers"]["tone"]["level"], "annoyed")
        self.assertTrue(result["diagnostics"]["is_mock"])

    def test_rejects_images(self) -> None:
        with self.assertRaises(UnsupportedFeature):
            self.service.decide(
                {
                    "state": "state",
                    "images": [{"url": "https://example.invalid/image.png"}],
                    "questions": {"urgent": {"type": "noul"}},
                }
            )

    def test_normalizes_real_diffgemma_score_shape(self) -> None:
        result = normalize_answers(
            {
                "tone": {
                    "type": "score",
                    "instructions": "Tone?",
                    "criteria": ["calm", "annoyed", "furious"],
                }
            },
            {
                "answers": {
                    "tone": {
                        "type": "score",
                        "score": 2.0,
                        "level": "annoyed",
                        "probabilities": {
                            "annoyed": 0.7,
                            "calm": 0.2,
                            "furious": 0.1,
                        },
                    }
                }
            },
        )

        self.assertEqual(result["tone"]["score"], 1.0)
        self.assertEqual(result["tone"]["level"], "annoyed")
        self.assertEqual(
            result["tone"]["legend"],
            {"0": "calm", "1": "annoyed", "2": "furious"},
        )
        self.assertEqual(
            result["tone"]["probabilities"],
            {"0": 0.2, "1": 0.7, "2": 0.1},
        )

    def test_normalizes_choice_in_request_order(self) -> None:
        result = normalize_answers(
            {
                "team": {
                    "type": "choice",
                    "criteria": {
                        "billing": "Billing",
                        "support": "Support",
                        "engineering": "Engineering",
                    },
                }
            },
            {
                "answers": {
                    "team": {
                        "probabilities": {
                            "engineering": 0.8,
                            "billing": 0.1,
                            "support": 0.1,
                        }
                    }
                }
            },
        )

        self.assertEqual(
            list(result["team"]["probabilities"]),
            ["billing", "support", "engineering"],
        )
        self.assertEqual(result["team"]["choice"], "engineering")

    def test_preserves_full_backend_response(self) -> None:
        result = self.service.decide(
            {
                "state": "state",
                "questions": {"urgent": {"type": "noul"}},
            }
        )

        self.assertEqual(
            result["diagnostics"]["raw_backend_response"]["diagnostics"]["backend"],
            "mock",
        )


if __name__ == "__main__":
    unittest.main()
