"""Small stdlib HTTP server for the MacJev playground."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .errors import MacJevError
from .service import DecisionService

MAX_BODY_BYTES = 1_048_576


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class MacJevHandler(BaseHTTPRequestHandler):
    """Expose the minimal Jev-compatible playground API."""

    service: DecisionService

    def log_message(self, format: str, *args: Any) -> None:
        print(f"macjev: {self.address_string()} {format % args}")

    def _send(self, status: int, body: dict[str, Any]) -> None:
        payload = _json_bytes(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok", "backend": self.service.backend.name})
            return
        if self.path == "/v1/models":
            self._send(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "macjev-playground",
                            "object": "model",
                            "owned_by": "local",
                        }
                    ],
                },
            )
            return
        self._send(404, {"detail": {"error_type": "not_found", "message": "unknown route"}})

    def do_POST(self) -> None:
        if self.path != "/v1/systemone":
            self._send(
                404, {"detail": {"error_type": "not_found", "message": "unknown route"}}
            )
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(
                400,
                {
                    "detail": {
                        "error_type": "invalid_request",
                        "message": "invalid Content-Length",
                    }
                },
            )
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send(
                413,
                {
                    "detail": {
                        "error_type": "invalid_request",
                        "message": "request body is empty or too large",
                    }
                },
            )
            return

        try:
            request = json.loads(self.rfile.read(length))
            result = self.service.decide(request)
        except json.JSONDecodeError:
            self._send(
                400,
                {
                    "detail": {
                        "error_type": "invalid_json",
                        "message": "request body is not valid JSON",
                    }
                },
            )
            return
        except MacJevError as exc:
            self._send(
                422,
                {
                    "detail": {
                        "error_type": exc.error_type,
                        "message": str(exc),
                    }
                },
            )
            return

        self._send(200, result)


def serve(service: DecisionService, host: str, port: int) -> None:
    handler = type(
        "BoundMacJevHandler",
        (MacJevHandler,),
        {"service": service},
    )
    server = ThreadingHTTPServer((host, port), handler)
    print(f"macjev: backend={service.backend.name} listening=http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("macjev: stopping")
    finally:
        server.server_close()
