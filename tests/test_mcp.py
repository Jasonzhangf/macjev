from __future__ import annotations

import io
import json
import unittest
from unittest import mock

from macjev import mcp


class McpTests(unittest.TestCase):
    def test_initialize_lists_tools_and_ping(self) -> None:
        request = b"".join(
            [
                b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n',
                b'{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n',
                b'{"jsonrpc":"2.0","id":3,"method":"ping"}\n',
            ]
        )
        output = io.BytesIO()

        self.assertEqual(mcp.serve_stream(io.BytesIO(request), output), 0)

        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "macjev")
        self.assertEqual(
            [tool["name"] for tool in responses[1]["result"]["tools"]],
            [
                "macjev_daemon_status",
                "macjev_daemon_start",
                "macjev_daemon_stop",
            ],
        )
        self.assertEqual(responses[2]["result"], {})

    def test_tool_call_returns_status(self) -> None:
        request = (
            b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":'
            b'{"name":"macjev_daemon_status","arguments":{}}}\n'
        )
        output = io.BytesIO()
        status = mock.Mock()
        status.as_dict.return_value = {"healthy": False}

        with (
            mock.patch("macjev.mcp.load_config", return_value=object()),
            mock.patch("macjev.mcp.RuntimeSupervisor") as supervisor,
        ):
            supervisor.return_value.status.return_value = status
            self.assertEqual(mcp.serve_stream(io.BytesIO(request), output), 0)

        response = json.loads(output.getvalue())
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(
            json.loads(response["result"]["content"][0]["text"]),
            {"healthy": False},
        )

    def test_unknown_method_returns_json_rpc_error(self) -> None:
        output = io.BytesIO()

        mcp.serve_stream(
            io.BytesIO(b'{"jsonrpc":"2.0","id":7,"method":"unknown"}\n'),
            output,
        )

        response = json.loads(output.getvalue())
        self.assertEqual(response["error"]["code"], -32601)

    def test_notification_does_not_emit_response(self) -> None:
        request = b"".join(
            [
                b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n',
                b'{"jsonrpc":"2.0","method":"ping"}\n',
                b'{"jsonrpc":"2.0","method":"unknown"}\n',
            ]
        )
        output = io.BytesIO()

        self.assertEqual(mcp.serve_stream(io.BytesIO(request), output), 0)

        self.assertEqual(output.getvalue(), b"")


if __name__ == "__main__":
    unittest.main()
