"""Deterministic backend for protocol tests. Never used as live evidence."""

from __future__ import annotations

from typing import Any

from ..schema import confidence


class MockBackend:
    """Small deterministic backend used only by the playground."""

    name = "mock"

    def decide(self, state: str, schema: dict[str, Any]) -> dict[str, Any]:
        answers: dict[str, Any] = {}
        urgent = any(word in state.lower() for word in ("outage", "500", "urgent"))

        for question in schema["questions"]:
            qid = question["id"]
            kind = question["type"]
            if kind == "noul":
                p_true = 0.86 if urgent else 0.24
                answers[qid] = {
                    "type": "noul",
                    "noul": p_true,
                    "probabilities": {"yes": p_true, "no": 1.0 - p_true},
                    "confidence": abs(2.0 * p_true - 1.0),
                }
            elif kind == "choice":
                options = [option["name"] for option in question["options"]]
                values = [0.08] * len(options)
                values[0] = 1.0 - sum(values[1:])
                answers[qid] = {
                    "type": "choice",
                    "choice": options[0],
                    "probabilities": dict(zip(options, values)),
                    "confidence": confidence(values),
                }
            elif kind == "score":
                levels = question["levels"]
                index = min(1, len(levels) - 1)
                values = [0.0] * len(levels)
                values[index] = 1.0
                answers[qid] = {
                    "type": "score",
                    "score": float(index + 1),
                    "level": levels[index],
                    "probabilities": dict(zip(levels, values)),
                    "confidence": confidence(values),
                }

        return {
            "answers": answers,
            "diagnostics": {
                "backend": self.name,
                "is_mock": True,
                "state_length": len(state),
            },
        }
