from __future__ import annotations

import unittest

from computer_fixtures import FakeComputerDriver
from macjev.computer import ComputerRequestError, ComputerService


class ComputerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.driver = FakeComputerDriver()
        self.service = ComputerService(self.driver)
        self.observation = self.service.observe({"window": "Fixture"})
        self.revision = self.observation["revision"]

    def guard(self, operation: dict) -> dict:
        return self.service.guard(
            {"revision": self.revision, "operation": operation}
        )

    def test_observe_returns_revision_elements_and_screenshot(self) -> None:
        self.assertEqual(self.observation["window"]["window_id"], 42)
        self.assertEqual(self.observation["screenshot"]["width"], 800)
        self.assertEqual(len(self.observation["elements"]), 6)
        self.assertEqual(self.observation["elements"][0]["settable"], None)

    def test_observe_reports_accessibility_outcome(self) -> None:
        """The web-renderer wake-up result must be visible for triage."""

        self.assertEqual(
            self.observation["diagnostics"]["accessibility"], "not_applicable"
        )
        self.driver.accessibility = "enabled"
        fresh = self.service.observe({"window": "Fixture"})
        self.assertEqual(fresh["diagnostics"]["accessibility"], "enabled")

    def test_observe_reports_unknown_accessibility_without_driver_field(self) -> None:
        """A driver that predates the wake-up reports `unknown`, not a crash."""

        self.driver.accessibility = None
        fresh = self.service.observe({"window": "Fixture"})
        self.assertEqual(fresh["diagnostics"]["accessibility"], "unknown")

    def test_guard_denies_stale_revision(self) -> None:
        result = self.service.guard(
            {
                "revision": "missing",
                "operation": {"kind": "click", "element_id": "element-press"},
            }
        )
        self.assertEqual(result["verdict"], "deny")
        self.assertEqual(result["reason_code"], "stale_revision")

    def test_guard_allows_press_capable_element(self) -> None:
        result = self.guard({"kind": "click", "element_id": "element-press"})
        self.assertEqual(result["verdict"], "allow")

    def test_guard_denies_disabled_element(self) -> None:
        result = self.guard({"kind": "click", "element_id": "element-disabled"})
        self.assertEqual(result["verdict"], "deny")
        self.assertEqual(result["reason_code"], "element_disabled")

    def test_guard_denies_element_outside_window(self) -> None:
        result = self.guard({"kind": "click", "element_id": "element-outside"})
        self.assertEqual(result["verdict"], "deny")
        self.assertEqual(result["reason_code"], "element_outside_window")

    def test_guard_returns_unknown_without_press_action(self) -> None:
        result = self.guard({"kind": "click", "element_id": "element-field"})
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["reason_code"], "element_action_unavailable")

    def test_guard_requires_expected_element_for_points(self) -> None:
        result = self.guard({"kind": "click", "point": {"x": 220, "y": 215}})
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["reason_code"], "point_identity_unverified")

    def test_guard_rejects_point_target_mismatch(self) -> None:
        self.driver.hit_point_element = "another-element"
        result = self.guard(
            {
                "kind": "click",
                "point": {"x": 220, "y": 215},
                "expected_element_id": "element-press",
            }
        )
        self.assertEqual(result["verdict"], "deny")
        self.assertEqual(result["reason_code"], "point_target_mismatch")

    def test_guard_allows_verified_point(self) -> None:
        result = self.guard(
            {
                "kind": "click",
                "point": {"x": 220, "y": 215},
                "expected_element_id": "element-press",
            }
        )
        self.assertEqual(result["verdict"], "allow")

    def test_guard_allows_point_hitting_a_child_of_expected_element(self) -> None:
        """Hit-test is app-anchored and lands on a deeper node than observe."""

        self.driver.hit_point_element = "element-press-icon"
        result = self.guard(
            {
                "kind": "click",
                "point": {"x": 220, "y": 215},
                "expected_element_id": "element-press",
            }
        )
        self.assertEqual(result["verdict"], "allow")
        self.assertEqual(result["reason_code"], "hit_test_match")

    def test_guard_denies_point_hitting_an_unrelated_element(self) -> None:
        self.driver.hit_point_element = "another-element"
        result = self.guard(
            {
                "kind": "click",
                "point": {"x": 220, "y": 215},
                "expected_element_id": "element-press",
            }
        )
        self.assertEqual(result["verdict"], "deny")
        self.assertEqual(result["reason_code"], "point_target_mismatch")

    def test_guard_denies_point_hitting_an_element_elsewhere(self) -> None:
        self.driver.hit_point_element = "element-far-away"
        result = self.guard(
            {
                "kind": "click",
                "point": {"x": 220, "y": 215},
                "expected_element_id": "element-press",
            }
        )
        self.assertEqual(result["verdict"], "deny")
        self.assertEqual(result["reason_code"], "point_target_mismatch")

    def test_guard_denies_occluded_point(self) -> None:
        self.driver.window_at_point_id = 999
        result = self.guard(
            {
                "kind": "click",
                "point": {"x": 220, "y": 215},
                "expected_element_id": "element-press",
            }
        )
        self.assertEqual(result["verdict"], "deny")
        self.assertEqual(result["reason_code"], "point_occluded")

    def test_guard_ignores_high_layer_cover(self) -> None:
        """Dock and menu-bar chrome must not read as occlusion."""

        self.driver.window_at_point_id = 999
        self.driver.window_at_point_layer = 20
        result = self.guard(
            {
                "kind": "click",
                "point": {"x": 220, "y": 215},
                "expected_element_id": "element-press",
            }
        )
        self.assertEqual(result["verdict"], "allow")

    def test_guard_returns_unknown_for_readonly_value(self) -> None:
        result = self.guard(
            {
                "kind": "set_value",
                "element_id": "element-readonly",
                "value": "hello",
            }
        )
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["reason_code"], "element_value_not_settable")

    def test_guard_allows_settable_value(self) -> None:
        result = self.guard(
            {
                "kind": "set_value",
                "element_id": "element-field",
                "value": "hello",
            }
        )
        self.assertEqual(result["verdict"], "allow")

    def test_act_requires_guard_verdict(self) -> None:
        with self.assertRaises(ComputerRequestError):
            self.service.act(
                {
                    "revision": self.revision,
                    "operation": {
                        "kind": "click",
                        "element_id": "element-disabled",
                    },
                }
            )
        self.assertEqual(self.driver.actions, [])

    def test_act_executes_guarded_element(self) -> None:
        result = self.service.act(
            {
                "revision": self.revision,
                "operation": {"kind": "click", "element_id": "element-press"},
            }
        )
        self.assertTrue(result["result"]["performed"])
        self.assertEqual(self.driver.actions[0]["operation"]["element_id"], "element-press")

    def test_verify_observes_again(self) -> None:
        result = self.service.verify(
            {
                "previous_revision": self.revision,
                "window": "Fixture",
                "element_id": "element-press",
            }
        )
        self.assertEqual(self.driver.observations, 2)
        self.assertTrue(result["revision_changed"])
        self.assertTrue(result["found"])

    def test_point_click_never_passes_element_id_to_driver(self) -> None:
        result = self.service.act(
            {
                "revision": self.revision,
                "operation": {
                    "kind": "click",
                    "point": {"x": 220, "y": 215},
                    "expected_element_id": "element-press",
                },
            }
        )
        self.assertTrue(result["result"]["performed"])
        operation = self.driver.actions[0]["operation"]
        self.assertEqual(operation["mode"], "point")
        self.assertNotIn("element_id", operation)
        self.assertEqual(
            operation["verified_element_id"],
            "element-press",
        )

    def test_element_click_declares_element_mode(self) -> None:
        self.service.act(
            {
                "revision": self.revision,
                "operation": {"kind": "click", "element_id": "element-press"},
            }
        )
        self.assertEqual(
            self.driver.actions[0]["operation"]["mode"],
            "element",
        )

    def test_observe_persists_observation(self) -> None:
        self.assertEqual(self.driver.persisted, [self.revision])

    def test_guard_recovers_revision_from_driver_store(self) -> None:
        fresh = ComputerService(self.driver)
        self.driver.restorable = True
        result = fresh.guard(
            {
                "revision": "sha256:release-1",
                "operation": {"kind": "click", "element_id": "element-press"},
            }
        )
        self.assertEqual(result["verdict"], "allow")
        self.assertEqual(self.driver.loaded, ["sha256:release-1"])

    def test_guard_denies_unrestorable_revision(self) -> None:
        fresh = ComputerService(self.driver)
        result = fresh.guard(
            {
                "revision": "sha256:release-2",
                "operation": {"kind": "click", "element_id": "element-press"},
            }
        )
        self.assertEqual(result["verdict"], "deny")
        self.assertEqual(result["reason_code"], "stale_revision")

    def test_guard_admits_type_text_on_focused_element(self) -> None:
        """Typed text goes to the focus holder, so the guard binds that element."""

        self.driver.focus_element_id = "element-field"
        observation = self.service.observe({"window": "Fixture"})
        result = self.service.guard(
            {
                "revision": observation["revision"],
                "operation": {
                    "kind": "type_text",
                    "text": "hello",
                    "expected_element_id": "element-field",
                },
            }
        )
        self.assertEqual(result["verdict"], "allow")
        self.assertEqual(result["reason_code"], "focus_target_match")

    def test_guard_denies_type_text_when_focus_moved(self) -> None:
        self.driver.focus_element_id = "element-press"
        observation = self.service.observe({"window": "Fixture"})
        result = self.service.guard(
            {
                "revision": observation["revision"],
                "operation": {
                    "kind": "type_text",
                    "text": "hello",
                    "expected_element_id": "element-field",
                },
            }
        )
        self.assertEqual(result["verdict"], "deny")
        self.assertEqual(result["reason_code"], "focus_target_not_focused")

    def test_guard_denies_empty_type_text(self) -> None:
        result = self.guard(
            {
                "kind": "type_text",
                "text": "",
                "expected_element_id": "element-field",
            }
        )
        self.assertEqual(result["verdict"], "deny")
        self.assertEqual(result["reason_code"], "text_missing")

    def test_guard_requires_focus_binding_for_type_text(self) -> None:
        result = self.guard({"kind": "type_text", "text": "hello"})
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["reason_code"], "focus_target_unverified")

    def test_guard_admits_key_tap_against_focus_holder(self) -> None:
        self.driver.focus_element_id = "element-field"
        observation = self.service.observe({"window": "Fixture"})
        result = self.service.guard(
            {
                "revision": observation["revision"],
                "operation": {
                    "kind": "key_tap",
                    "key": "return",
                    "expected_element_id": "element-field",
                },
            }
        )
        self.assertEqual(result["verdict"], "allow")
        self.assertEqual(result["reason_code"], "focus_target_match")

    def test_guard_requires_focus_binding_for_key_tap(self) -> None:
        """A keystroke must name its target; focus is the entire destination."""

        result = self.guard({"kind": "key_tap", "key": "return"})
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["reason_code"], "focus_target_unverified")

    def test_guard_denies_key_tap_without_key(self) -> None:
        result = self.guard({"kind": "key_tap"})
        self.assertEqual(result["verdict"], "deny")
        self.assertEqual(result["reason_code"], "key_missing")

    def test_guard_admits_scroll_inside_window(self) -> None:
        result = self.guard({"kind": "scroll", "point": {"x": 300, "y": 300}})
        self.assertEqual(result["verdict"], "allow")

    def test_guard_denies_scroll_outside_window(self) -> None:
        result = self.guard({"kind": "scroll", "point": {"x": 2000, "y": 2000}})
        self.assertEqual(result["verdict"], "deny")
        self.assertEqual(result["reason_code"], "point_outside_window")

    def test_guard_denies_drag_when_only_start_is_inside(self) -> None:
        """A drag can leave the window at its end point, so both ends must pass."""

        result = self.guard(
            {
                "kind": "drag",
                "from": {"x": 300, "y": 300},
                "to": {"x": 5000, "y": 5000},
            }
        )
        self.assertEqual(result["verdict"], "deny")
        self.assertEqual(result["reason_code"], "point_outside_window")

    def test_guard_admits_drag_inside_window(self) -> None:
        result = self.guard(
            {
                "kind": "drag",
                "from": {"x": 300, "y": 300},
                "to": {"x": 400, "y": 400},
            }
        )
        self.assertEqual(result["verdict"], "allow")
        self.assertEqual(result["reason_code"], "drag_endpoints_in_window")

    def test_act_forwards_type_text_without_element_id(self) -> None:
        self.driver.focus_element_id = "element-field"
        observation = self.service.observe({"window": "Fixture"})
        self.service.act(
            {
                "revision": observation["revision"],
                "operation": {
                    "kind": "type_text",
                    "text": "你好",
                    "expected_element_id": "element-field",
                },
            }
        )
        forwarded = self.driver.actions[-1]["operation"]
        self.assertEqual(forwarded["kind"], "type_text")
        self.assertEqual(forwarded["text"], "你好")
        self.assertNotIn("element_id", forwarded)

    def test_act_forwards_key_tap_modifiers(self) -> None:
        self.driver.focus_element_id = "element-field"
        observation = self.service.observe({"window": "Fixture"})
        self.service.act(
            {
                "revision": observation["revision"],
                "operation": {
                    "kind": "key_tap",
                    "key": "v",
                    "modifiers": ["cmd"],
                    "expected_element_id": "element-field",
                },
            }
        )
        forwarded = self.driver.actions[-1]["operation"]
        self.assertEqual(forwarded["key"], "v")
        self.assertEqual(forwarded["modifiers"], ["cmd"])
        # The fixture elements carry no AXIdentifier, so the assertion identity
        # is role plus title; that is exactly what the driver compares.
        self.assertEqual(forwarded["expect_identifier"], "")
        self.assertEqual(forwarded["expect_title"], "Fixture Field")
        self.assertEqual(forwarded["expect_role"], "AXTextField")

    def test_act_forwards_drag_endpoints(self) -> None:
        observation = self.service.observe({"window": "Fixture"})
        self.service.act(
            {
                "revision": observation["revision"],
                "operation": {
                    "kind": "drag",
                    "from": {"x": 300, "y": 300},
                    "to": {"x": 400, "y": 420},
                    "steps": 8,
                },
            }
        )
        forwarded = self.driver.actions[-1]["operation"]
        self.assertEqual(forwarded["mode"], "drag")
        self.assertEqual(forwarded["from"], {"x": 300, "y": 300})
        self.assertEqual(forwarded["to"], {"x": 400, "y": 420})
        self.assertEqual(forwarded["steps"], 8)

    def test_act_denies_unsupported_operation(self) -> None:
        observation = self.service.observe({"window": "Fixture"})
        with self.assertRaises(ComputerRequestError) as caught:
            self.service.act(
                {
                    "revision": observation["revision"],
                    "operation": {"kind": "teleport", "text": "x"},
                }
            )
        self.assertIn("operation_unsupported", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
