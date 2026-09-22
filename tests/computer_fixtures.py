"""Deterministic driver fixtures for the computer-use boundary."""

from __future__ import annotations

import copy
from typing import Any


WINDOW = {
    "window_id": 42,
    "pid": 4242,
    "application_id": "com.example.fixture",
    "application_name": "Fixture",
    "title": "Fixture Window",
    "layer": 0,
    "on_screen": True,
    "bounds": {"x": 100, "y": 100, "width": 800, "height": 600},
}


def _element(
    element_id: str,
    *,
    role: str = "AXButton",
    title: str = "Fixture Button",
    enabled: bool = True,
    settable: bool | None = None,
    x: float = 200,
    y: float = 200,
    width: float = 80,
    height: float = 30,
    actions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "element_id": element_id,
        "parent_id": None,
        "depth": 1,
        "role": role,
        "subrole": None,
        "title": title,
        "description": None,
        "value": "",
        "identifier": None,
        "enabled": enabled,
        "focused": False,
        "selected": False,
        "settable": settable,
        "position": {"x": x, "y": y},
        "size": {"width": width, "height": height},
        "actions": ["AXPress"] if actions is None else actions,
    }


ELEMENTS = [
    _element("element-press"),
    _element(
        "element-press-icon",
        title="",
        x=210,
        y=207,
        width=24,
        height=16,
    ),
    _element("element-disabled", enabled=False),
    _element(
        "element-field",
        role="AXTextField",
        title="Fixture Field",
        settable=True,
        actions=[],
    ),
    _element(
        "element-readonly",
        role="AXTextField",
        title="Readonly Field",
        settable=False,
        actions=[],
    ),
    _element("element-outside", x=2000, y=2000),
]


class FakeComputerDriver:
    """Return deterministic observations and record admitted operations."""

    name = "fake"

    def __init__(self) -> None:
        self.observations = 0
        self.actions: list[dict[str, Any]] = []
        self.hit_point_element = "element-press"
        self.persisted: list[str] = []
        self.loaded: list[str] = []
        self.restorable = False
        self.window_at_point_id: int | None = None
        self.window_at_point_layer = 0
        self.accessibility: str | None = "not_applicable"
        # Keyboard input targets whatever holds focus, so the fixture must be
        # able to say which element that is in a given observation.
        self.focus_element_id: str | None = None

    def list_windows(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(WINDOW)]

    def observe(self, window: str) -> dict[str, Any]:
        self.observations += 1
        elements = copy.deepcopy(ELEMENTS)
        for element in elements:
            element["focused"] = element["element_id"] == self.focus_element_id
        observation = {
            "window": copy.deepcopy(WINDOW),
            "revision": f"revision-{self.observations}",
            "elements": elements,
            "truncated": False,
            "screenshot_ref": f"file:///tmp/macjev-fixture-{self.observations}.png",
            "screenshot_digest": f"sha256:fixture-{self.observations}",
            "screenshot_width": 800,
            "screenshot_height": 600,
            "screenshot_scale": 1.0,
        }
        if self.accessibility is not None:
            observation["accessibility"] = self.accessibility
        return observation

    def act(self, request: dict[str, Any]) -> dict[str, Any]:
        self.actions.append(copy.deepcopy(request))
        return {
            "action": request["operation"]["kind"],
            "element_id": request["operation"].get("element_id"),
            "performed": True,
        }

    def persist_observation(self, observation: dict[str, Any], request: dict) -> str:
        self.persisted.append(observation["revision"])
        return observation["revision"]

    def load_observation(self, revision: str) -> dict[str, Any] | None:
        self.loaded.append(revision)
        if not self.restorable:
            return None
        return {
            "window": copy.deepcopy(WINDOW),
            "revision": revision,
            "elements": copy.deepcopy(ELEMENTS),
            "truncated": False,
            "screenshot_ref": "file:///tmp/macjev-restored.png",
            "screenshot_digest": "sha256:restored",
            "screenshot_width": 800,
            "screenshot_height": 600,
            "screenshot_scale": 1.0,
        }

    def hit_test(self, request: dict[str, Any]) -> dict[str, Any]:
        geometry = next(
            (
                element
                for element in ELEMENTS
                if element["element_id"] == self.hit_point_element
            ),
            None,
        )
        # An unknown target reports geometry far from the expected control, so
        # containment cannot accidentally admit it.
        position = geometry["position"] if geometry else {"x": 9000, "y": 9000}
        size = geometry["size"] if geometry else {"width": 10, "height": 10}
        return {
            "point": copy.deepcopy(request["point"]),
            "element_id": self.hit_point_element,
            "role": "AXButton",
            "title": "Fixture Button",
            "description": None,
            "value": None,
            "position": dict(position),
            "size": dict(size),
            "actions": ["AXPress"],
        }

    def window_at_point(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "point": copy.deepcopy(request["point"]),
            "window_id": self.window_at_point_id,
            "pid": 4242,
            "application_name": "Fixture",
            "title": "Fixture Window",
            "layer": self.window_at_point_layer,
        }
