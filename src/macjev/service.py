"""Decision service that keeps the Jev contract independent of the backend."""

from __future__ import annotations

from typing import Any

from .backends.base import DecisionBackend
from .errors import ModelNotFound, SchemaError, UnsupportedFeature
from .schema import build_diffgemma_schema, normalize_answers

MODEL_VERSION = "openjev-0.1"
MODEL_ALIASES = {"openjev-latest", MODEL_VERSION, "jev-latest", "jev-preview"}


class DecisionService:
    """Validate a Jev request, call a backend, and normalize its answer."""

    def __init__(self, backend: DecisionBackend) -> None:
        self.backend = backend

    def decide(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise UnsupportedFeature("request must be an object")
        model = request.get("model")
        if not isinstance(model, str) or not model:
            raise SchemaError("model must be a non-empty string")
        if model not in MODEL_ALIASES:
            raise ModelNotFound(
                f"model {model!r} is not available; use one of: "
                f"{', '.join(sorted(MODEL_ALIASES))}"
            )
        if request.get("images"):
            raise UnsupportedFeature(
                "the Mac diffgemma backend is text-only; image input is not supported"
            )

        if "state" not in request:
            raise SchemaError("state is required")
        state = request["state"]

        questions = request.get("questions")
        options = request.get("options")
        schema = build_diffgemma_schema(questions, options)
        backend_response = self.backend.decide(state, schema)
        answers = normalize_answers(questions, backend_response)
        diagnostics = backend_response.get("diagnostics", {})
        prompt_tokens = diagnostics.get("timing", {}).get("prompt_tokens")
        usage = {"output_tokens": 0}
        if isinstance(prompt_tokens, (int, float)) and not isinstance(
            prompt_tokens, bool
        ):
            usage["input_tokens"] = prompt_tokens
        return {
            "model": MODEL_VERSION,
            "answers": answers,
            "usage": usage,
            "diagnostics": {
                "backend": self.backend.name,
                "is_mock": bool(diagnostics.get("is_mock", False)),
                "raw_backend_response": backend_response,
            },
        }
