"""Small stdlib HTTP server for the MacJev service."""

from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .computer import ComputerDriverError, ComputerService
from .errors import BackendError, MacJevError, ModelNotFound
from .service import MODEL_VERSION, DecisionService

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
    """Expose the minimal Jev-compatible MacJev API."""

    service: DecisionService
    computer_service: ComputerService | None = None
    api_key = ""
    origin_secret = ""
    max_body_bytes = 1_048_576

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
        if self.origin_secret:
            supplied = self.headers.get("X-Origin-Secret", "")
            if not hmac.compare_digest(supplied, self.origin_secret):
                self._error(
                    403,
                    "permission_error",
                    "Direct access to this origin is not allowed.",
                )
                return False

        if self.api_key:
            authorization = self.headers.get("Authorization", "")
            scheme, separator, token = authorization.partition(" ")
            if not separator or scheme.lower() != "bearer":
                self._error(
                    403,
                    "authentication_error",
                    "Must supply a Bearer API key.",
                )
                return False
            supplied = token.strip()
            if not hmac.compare_digest(supplied, self.api_key):
                self._error(
                    401,
                    "authentication_error",
                    "Cannot authenticate with the server.",
                )
                return False
        return True

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._error(400, "invalid_request", "invalid Content-Length")
            return None
        if length <= 0 or length > self.max_body_bytes:
            self._error(
                413,
                "invalid_request",
                "request body is empty or too large",
            )
            return None
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._error(400, "invalid_json", "request body is not valid JSON")
            return None
        if not isinstance(value, dict):
            self._error(400, "invalid_request", "request body must be an object")
            return None
        return value

    def _computer(self) -> ComputerService | None:
        if self.computer_service is None:
            self._error(
                503,
                "capability_unavailable",
                "computer-use driver is not configured",
            )
            return None
        return self.computer_service

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok", "backend": self.service.backend.name})
            return
        if not self._check_auth():
            return
        if self.path == "/v1/models":
            self._send(200, {"models": MODELS})
            return
        if self.path == "/v1/computer/windows":
            computer = self._computer()
            if computer is None:
                return
            try:
                self._send(
                    200,
                    {
                        "api_version": "1",
                        "windows": computer.driver.list_windows(),
                    },
                )
            except MacJevError as exc:
                self._error(503, exc.error_type, str(exc))
            return
        self._error(404, "not_found_error", "unknown route")

    def do_POST(self) -> None:
        if not self._check_auth():
            return
        if self.path.startswith("/v1/computer/"):
            computer = self._computer()
            if computer is None:
                return
            request = self._read_json()
            if request is None:
                return
            try:
                if self.path == "/v1/computer/observe":
                    result = computer.observe(request)
                elif self.path == "/v1/computer/guard":
                    result = computer.guard(request)
                elif self.path == "/v1/computer/act":
                    result = computer.act(request)
                elif self.path == "/v1/computer/verify":
                    result = computer.verify(request)
                else:
                    self._error(404, "not_found_error", "unknown route")
                    return
            except MacJevError as exc:
                status = 503 if isinstance(exc, ComputerDriverError) else 422
                self._error(status, exc.error_type, str(exc))
                return
            self._send(200, result)
            return
        if self.path != "/v1/systemone":
            self._error(404, "not_found_error", "unknown route")
            return
        request = self._read_json()
        if request is None:
            return

        try:
            result = self.service.decide(request)
        except MacJevError as exc:
            if isinstance(exc, ModelNotFound):
                status = 404
            elif isinstance(exc, BackendError):
                status = 503
            else:
                status = 422
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


def serve(
    service: DecisionService,
    host: str,
    port: int,
    *,
    api_key: str | None = None,
    origin_secret: str | None = None,
    max_body_bytes: int = 1_048_576,
    computer_service: ComputerService | None = None,
) -> None:
    if api_key is None:
        api_key = os.environ.get("OPENJEV_API_KEY", "")
    if origin_secret is None:
        origin_secret = os.environ.get("OPENJEV_ORIGIN_SECRET", "")
    handler = type(
        "BoundMacJevHandler",
        (MacJevHandler,),
        {
            "service": service,
            "computer_service": computer_service,
            "api_key": api_key,
            "origin_secret": origin_secret,
            "max_body_bytes": max_body_bytes,
        },
    )
    server = ThreadingHTTPServer((host, port), handler)
    print(f"macjev: backend={service.backend.name} listening=http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("macjev: stopping")
    finally:
        server.server_close()
