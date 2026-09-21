"""Minimal stdio MCP server for MacJev runtime capabilities."""

from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO

from .config import load_config
from .release import build_version
from .supervisor import RuntimeSupervisor

PROTOCOL_VERSION = "2024-11-05"


def _response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        },
    }


def _tools() -> list[dict[str, Any]]:
    config = {"type": "string", "description": "Runtime TOML path."}
    return [
        _tool(
            "macjev_daemon_status",
            "Return the configured managed DiffGemma daemon status.",
            {"config": config},
        ),
        _tool(
            "macjev_daemon_start",
            "Start the configured managed DiffGemma daemon if it is unhealthy.",
            {"config": config},
        ),
        _tool(
            "macjev_daemon_stop",
            "Stop the managed DiffGemma daemon recorded by the configured PID file.",
            {"config": config},
        ),
    ]


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    config_path = arguments.get("config")
    supervisor = RuntimeSupervisor(load_config(config_path))
    if name == "macjev_daemon_status":
        value = supervisor.status().as_dict()
    elif name == "macjev_daemon_start":
        pid, started = supervisor.start()
        value = {"pid": pid, "started": started, "status": supervisor.status().as_dict()}
    elif name == "macjev_daemon_stop":
        value = {"stopped": supervisor.stop(), "status": supervisor.status().as_dict()}
    else:
        raise ValueError(f"unknown tool: {name}")
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(value, ensure_ascii=False, sort_keys=True),
            }
        ],
        "isError": False,
    }


def _dispatch(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return _response(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "macjev", "version": build_version()},
            },
        )
    if method == "ping":
        return _response(request_id, {})
    if method == "tools/list":
        return _response(request_id, {"tools": _tools()})
    if method == "tools/call":
        params = message.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return _error(request_id, -32602, "tools/call requires params.name")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return _error(request_id, -32602, "tools/call arguments must be an object")
        try:
            return _response(request_id, _call_tool(params["name"], arguments))
        except Exception as exc:
            return _response(
                request_id,
                {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            )
    return _error(request_id, -32601, f"method not found: {method}")


def serve_stream(reader: BinaryIO, writer: BinaryIO) -> int:
    """Serve newline-delimited JSON-RPC messages until EOF."""

    while True:
        raw = reader.readline()
        if not raw:
            return 0
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            response = _error(None, -32700, f"parse error: {exc}")
        else:
            if not isinstance(message, dict):
                response = _error(None, -32600, "request must be an object")
            else:
                response = _dispatch(message)
                if "id" not in message:
                    response = None
        if response is not None:
            writer.write(
                json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
                + b"\n"
            )
            writer.flush()


def main() -> int:
    return serve_stream(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
