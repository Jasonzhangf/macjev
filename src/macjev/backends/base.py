"""Backend interface."""

from __future__ import annotations

from typing import Any, Protocol


class DecisionBackend(Protocol):
    """A backend that answers a diffgemma-shaped question schema."""

    name: str

    def decide(
        self,
        state: Any,
        schema: dict[str, Any],
        images: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return an answers object plus optional diagnostics."""
