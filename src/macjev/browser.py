"""Browser adapter boundary for goal-driven automation."""

from __future__ import annotations

from typing import Any, NotRequired, Protocol, TypedDict


class BrowserContainer(TypedDict):
    """Identity and optional context for one matched DOM container."""

    ref: str
    selector: NotRequired[str]
    text: NotRequired[str]
    bounds: NotRequired[dict[str, float]]


class BrowserGoal(TypedDict):
    """Describe what to find in the DOM and what to do with it."""

    target: str
    action: NotRequired[str]
    arguments: NotRequired[dict[str, Any]]


class BrowserResult(TypedDict):
    """Return the matched container, the action result, or both."""

    found: bool
    container: NotRequired[BrowserContainer]
    action_result: NotRequired[dict[str, Any]]


class BrowserAdapter(Protocol):
    """Resolve a described DOM target and execute its requested operation.

    The adapter owns browser transport and execution details, for example
    Camo or CDP. It accepts a semantic goal, locates the target in the current
    DOM, performs the requested action, and returns the container identity or
    action result. Browser control state never enters Jev requests or
    responses.
    """

    name: str

    def execute(self, goal: BrowserGoal) -> BrowserResult:
        """Find the described target and execute the requested action."""
