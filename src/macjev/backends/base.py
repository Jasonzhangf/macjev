"""Backend interface."""

from __future__ import annotations

from typing import Any, Protocol


class DecisionBackend(Protocol):
    """A backend that answers a diffgemma-shaped question schema."""

    name: str

    def decide(self, state: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Return an answers object plus optional diagnostics."""
