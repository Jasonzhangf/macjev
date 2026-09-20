from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from macjev.backends.diffgemma import DiffGemmaBackend


class DiffGemmaBackendTests(unittest.TestCase):
    def test_serializes_state_as_json(self) -> None:
        captured: dict = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                captured.update(json.loads(self.rfile.read(length)))
                body = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "answers": {
                                                "urgent": {
                                                    "noul": 0.75,
                                                    "probabilities": {
                                                        "yes": 0.75,
                                                        "no": 0.25,
                                                    },
                                                }
                                            }
                                        }
                                    )
                                }
                            }
                        ]
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            backend = DiffGemmaBackend(
                f"http://127.0.0.1:{server.server_port}", "test-model"
            )
            backend.decide(
                "Production outage",
                {
                    "questions": [
                        {
                            "id": "urgent",
                            "type": "noul",
                            "instructions": "Urgent?",
                        }
                    ]
                },
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

        self.assertEqual(
            json.loads(captured["messages"][1]["content"]),
            {"state": "Production outage"},
        )

    def test_preserves_structured_json_state(self) -> None:
        captured: dict = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                captured.update(json.loads(self.rfile.read(length)))
                body = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "answers": {
                                                "urgent": {
                                                    "noul": 0.75,
                                                    "probabilities": {
                                                        "yes": 0.75,
                                                        "no": 0.25,
                                                    },
                                                }
                                            }
                                        }
                                    )
                                }
                            }
                        ]
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            backend = DiffGemmaBackend(
                f"http://127.0.0.1:{server.server_port}", "test-model"
            )
            backend.decide(
                {"message": "Production outage", "attempt": 2},
                {
                    "questions": [
                        {
                            "id": "urgent",
                            "type": "noul",
                            "instructions": "Urgent?",
                        }
                    ]
                },
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

        self.assertEqual(
            json.loads(captured["messages"][1]["content"]),
            {"state": {"message": "Production outage", "attempt": 2}},
        )

    def test_preserves_state_and_adds_images(self) -> None:
        captured: dict = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                captured.update(json.loads(self.rfile.read(length)))
                body = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "answers": {
                                                "target": {
                                                    "probabilities": {
                                                        "left": 0.9,
                                                        "right": 0.1,
                                                    }
                                                }
                                            }
                                        }
                                    )
                                }
                            }
                        ]
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            backend = DiffGemmaBackend(
                f"http://127.0.0.1:{server.server_port}", "test-model"
            )
            backend.decide(
                {"viewport": {"width": 1280, "height": 720}},
                {
                    "questions": [
                        {
                            "id": "target",
                            "type": "choice",
                            "instructions": "Which button?",
                            "options": [
                                {"name": "left", "description": "Left"},
                                {"name": "right", "description": "Right"},
                            ],
                        }
                    ]
                },
                images=[{"url": "data:image/png;base64,AAAA"}],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

        content = captured["messages"][1]["content"]
        self.assertEqual(
            content,
            [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"state": {"viewport": {"width": 1280, "height": 720}}},
                        ensure_ascii=False,
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AAAA"},
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
