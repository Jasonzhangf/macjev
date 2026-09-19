"""Small stdlib HTTP server for the MacJev playground."""

from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .errors import MacJevError, ModelNotFound
from .service import MODEL_VERSION, DecisionService

MAX_BODY_BYTES = 1_048_576
MODELS = [
    {
        "name": "openjev-latest",
        "description": f"Alias for {MODEL_VERSION}.",
        "release_date": "2026-09-19",
    },
    {
        "name": MODEL_VERSION,
        "description": "DiffusionGemma 26B-A4B on the Mac Metal backend.",
        "release_date": "2026-09-19",
    },
]


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

    def _error(
        self, status: int, error_type: str, message: str
    ) -> None:
        self._send(
            status,
            {"detail": {"error_type": error_type, "message": message}},
        )

    def _check_auth(self) -> bool:
        origin_secret = os.environ.get("OPENJEV_ORIGIN_SECRET", "")
        if origin_secret:
            supplied = self.headers.get("X-Origin-Secret", "")
            if not hmac.compare_digest(supplied, origin_secret):
                self._error(
                    403,
                    "permission_error",
                    "Direct access to this origin is not allowed.",
                )
                return False

        api_key = os.environ.get("OPENJEV_API_KEY", "")
        if api_key:
            authorization = self.headers.get("Authorization", "")
            if not authorization:
                self._error(
                    403,
                    "authentication_error",
                    "Must supply an API key.",
                )
                return False
            supplied = authorization.removeprefix("Bearer ").strip()
            if not hmac.compare_digest(supplied, api_key):
                self._error(
                    401,
                    "authentication_error",
                    "Cannot authenticate with the server.",
                )
                return False
        return True

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok", "backend": self.service.backend.name})
            return
        if not self._check_auth():
            return
        if self.path == "/v1/models":
            self._send(200, {"models": MODELS})
            return
        self._error(404, "not_found_error", "unknown route")

    def do_POST(self) -> None:
        if not self._check_auth():
            return
        if self.path != "/v1/systemone":
            self._error(404, "not_found_error", "unknown route")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._error(400, "invalid_request", "invalid Content-Length")
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._error(
                413,
                "invalid_request",
                "request body is empty or too large",
            )
            return

        try:
            request = json.loads(self.rfile.read(length))
            result = self.service.decide(request)
        except json.JSONDecodeError:
            self._error(400, "invalid_json", "request body is not valid JSON")
            return
        except MacJevError as exc:
            status = 404 if isinstance(exc, ModelNotFound) else 422
            self._error(status, exc.error_type, str(exc))
            return

        self._send(
            200,
            {
                "model": result["model"],
                "answers": result["answers"],
                "usage": result["usage"],
            },
        )


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
