"""Decision service that keeps the Jev contract independent of the backend."""

from __future__ import annotations

from typing import Any

from .backends.base import DecisionBackend
from .errors import UnsupportedFeature
from .schema import build_diffgemma_schema, normalize_answers


class DecisionService:
    """Validate a Jev request, call a backend, and normalize its answer."""

    def __init__(self, backend: DecisionBackend) -> None:
        self.backend = backend

    def decide(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise UnsupportedFeature("request must be an object")
        if request.get("images"):
            raise UnsupportedFeature(
                "the Mac diffgemma backend is text-only; image input is not supported"
            )

        state = request.get("state")
        if not isinstance(state, str):
            raise UnsupportedFeature("state must be a string")

        questions = request.get("questions")
        options = request.get("options")
        schema = build_diffgemma_schema(questions, options)
        backend_response = self.backend.decide(state, schema)
        answers = normalize_answers(questions, backend_response)
        diagnostics = backend_response.get("diagnostics", {})
        return {
            "answers": answers,
            "diagnostics": {
                "backend": self.backend.name,
                "is_mock": bool(diagnostics.get("is_mock", False)),
                "raw_backend_response": backend_response,
            },
        }
