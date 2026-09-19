from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from macjev.backends.diffgemma import DiffGemmaBackend
from macjev.errors import BackendError


class _BackendHandler(BaseHTTPRequestHandler):
    health = {"status": "ok"}
    models = {"data": [{"id": "configured-model"}]}

    def do_GET(self) -> None:
        if self.path == "/health":
            value = self.health
        elif self.path == "/v1/models":
            value = self.models
        else:
            self.send_error(404)
            return
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class DiffGemmaReadinessTests(unittest.TestCase):
    def _serve(self, handler: type[_BackendHandler]) -> tuple[ThreadingHTTPServer, threading.Thread]:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_rejects_unhealthy_status(self) -> None:
        handler = type(
            "UnhealthyHandler",
            (_BackendHandler,),
            {"health": {"status": "error"}},
        )
        server, thread = self._serve(handler)
        try:
            backend = DiffGemmaBackend(
                f"http://127.0.0.1:{server.server_port}",
                "configured-model",
            )
            with self.assertRaisesRegex(BackendError, "health status"):
                backend.ensure_ready()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_rejects_missing_configured_model(self) -> None:
        handler = type(
            "WrongModelHandler",
            (_BackendHandler,),
            {"models": {"data": [{"id": "other-model"}]}},
        )
        server, thread = self._serve(handler)
        try:
            backend = DiffGemmaBackend(
                f"http://127.0.0.1:{server.server_port}",
                "configured-model",
            )
            with self.assertRaisesRegex(BackendError, "configured model"):
                backend.ensure_ready()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_accepts_healthy_configured_model(self) -> None:
        server, thread = self._serve(_BackendHandler)
        try:
            backend = DiffGemmaBackend(
                f"http://127.0.0.1:{server.server_port}",
                "configured-model",
            )
            backend.ensure_ready()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
