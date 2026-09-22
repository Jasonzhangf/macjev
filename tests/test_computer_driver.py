"""Tests for the native driver argument translation boundary."""

from __future__ import annotations

import unittest

from macjev.computer import _socket_request


class SocketRequestTests(unittest.TestCase):
    def test_observe_arguments_become_a_request(self) -> None:
        request = _socket_request(
            ["observe", "--window", "42", "--output", "/tmp/x.png"]
        )
        self.assertEqual(
            request,
            {"command": "observe", "window": "42", "output": "/tmp/x.png"},
        )

    def test_window_at_point_arguments_become_a_request(self) -> None:
        request = _socket_request(["window-at-point", "--x", "10", "--y", "20"])
        self.assertEqual(request, {"command": "window-at-point", "x": 10.0, "y": 20.0})

    def test_click_point_arguments_become_a_request(self) -> None:
        request = _socket_request(
            ["click-point", "--window", "42", "--x", "12.5", "--y", "30"]
        )
        self.assertEqual(request["command"], "click-point")
        self.assertEqual(request["x"], 12.5)
        self.assertEqual(request["y"], 30.0)
        self.assertNotIn("element", request)

    def test_click_element_arguments_become_a_request(self) -> None:
        request = _socket_request(
            ["click-element", "--window", "42", "--element", "sha256:abc"]
        )
        self.assertEqual(request["command"], "click-element")
        self.assertEqual(request["element"], "sha256:abc")
        self.assertNotIn("x", request)

    def test_set_value_arguments_become_a_request(self) -> None:
        request = _socket_request(
            ["set-value", "--window", "42", "--element", "e", "--value", "hello"]
        )
        self.assertEqual(request["value"], "hello")

    def test_type_text_carries_its_focus_assertion(self) -> None:
        """Keyboard requests must survive translation with their assertion intact.

        The driver refuses keyboard input without the expected focus identity, so
        dropping these flags in translation turns every keystroke into a
        `focus_target_missing` failure.
        """

        request = _socket_request(
            [
                "type-text",
                "--window", "42",
                "--text", "查询",
                "--expect-role", "AXTextArea",
                "--expect-identifier", "search",
                "--expect-title", "搜索",
            ]
        )
        self.assertEqual(request["command"], "type-text")
        self.assertEqual(request["text"], "查询")
        self.assertEqual(request["expect_role"], "AXTextArea")
        self.assertEqual(request["expect_identifier"], "search")
        self.assertEqual(request["expect_title"], "搜索")

    def test_key_tap_carries_modifiers(self) -> None:
        request = _socket_request(
            [
                "key-tap",
                "--window", "42",
                "--key", "v",
                "--modifiers", "cmd,shift",
                "--expect-role", "AXTextArea",
                "--expect-identifier", "chat_input_field",
            ]
        )
        self.assertEqual(request["key"], "v")
        self.assertEqual(request["modifiers"], ["cmd", "shift"])
        self.assertEqual(request["expect_identifier"], "chat_input_field")

    def test_drag_arguments_become_a_request(self) -> None:
        request = _socket_request(
            [
                "drag",
                "--window", "42",
                "--x", "10", "--y", "20",
                "--to-x", "30", "--to-y", "40",
                "--steps", "6",
            ]
        )
        self.assertEqual(request["to_x"], 30.0)
        self.assertEqual(request["to_y"], 40.0)
        self.assertEqual(request["steps"], 6)

    def test_click_point_carries_button_and_count(self) -> None:
        request = _socket_request(
            [
                "click-point",
                "--window", "42",
                "--x", "10", "--y", "20",
                "--button", "right",
                "--count", "2",
            ]
        )
        self.assertEqual(request["button"], "right")
        self.assertEqual(request["count"], 2)


if __name__ == "__main__":
    unittest.main()
