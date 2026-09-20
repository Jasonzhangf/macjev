from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from macjev.backends.mock import MockBackend
from macjev.http import MacJevHandler
from macjev.service import DecisionService


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.previous_api_key = os.environ.pop("OPENJEV_API_KEY", None)
        cls.previous_origin_secret = os.environ.pop("OPENJEV_ORIGIN_SECRET", None)
        handler = type(
            "TestMacJevHandler",
            (MacJevHandler,),
            {"service": DecisionService(MockBackend())},
        )
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        if cls.previous_api_key is not None:
            os.environ["OPENJEV_API_KEY"] = cls.previous_api_key
        if cls.previous_origin_secret is not None:
            os.environ["OPENJEV_ORIGIN_SECRET"] = cls.previous_origin_secret

    def get_json(self, path: str) -> dict:
        with urllib.request.urlopen(self.base_url + path) as response:
            return json.load(response)

    def test_health_and_models(self) -> None:
        self.assertEqual(self.get_json("/health")["backend"], "mock")
        self.assertEqual(
            [model["name"] for model in self.get_json("/v1/models")["models"]],
            ["openjev-latest", "openjev-0.1"],
        )

    def test_systemone(self) -> None:
        request = urllib.request.Request(
            self.base_url + "/v1/systemone",
            data=json.dumps(
                {
                    "model": "jev-latest",
                    "state": "Production outage",
                    "questions": {"urgent": {"type": "noul"}},
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            result = json.load(response)

        self.assertEqual(set(result), {"model", "answers", "usage"})
        self.assertEqual(result["model"], "openjev-0.1")
        self.assertEqual(result["answers"]["urgent"]["type"], "noul")
        self.assertNotIn("diagnostics", result)
        self.assertEqual(result["usage"]["output_tokens"], 0)

    def test_accepts_json_state_and_all_model_aliases(self) -> None:
        for model in ("openjev-latest", "openjev-0.1", "jev-latest", "jev-preview"):
            with self.subTest(model=model):
                request = urllib.request.Request(
                    self.base_url + "/v1/systemone",
                    data=json.dumps(
                        {
                            "model": model,
                            "state": {"message": "Production outage", "attempt": 2},
                            "questions": {
                                "urgent": {
                                    "type": "noul",
                                    "instructions": "Is this urgent?",
                                }
                            },
                        }
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request) as response:
                    result = json.load(response)

                self.assertEqual(result["model"], "openjev-0.1")
                self.assertGreater(result["answers"]["urgent"]["noul"], 0.8)

    def test_unknown_model_is_404(self) -> None:
        request = urllib.request.Request(
            self.base_url + "/v1/systemone",
            data=json.dumps(
                {
                    "model": "unknown",
                    "state": "x",
                    "questions": {"q": {"type": "noul", "instructions": "Q?"}},
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)

        error = caught.exception
        self.assertEqual(error.code, 404)
        detail = json.load(error)["detail"]
        error.close()
        self.assertEqual(detail["error_type"], "not_found_error")

    def test_invalid_schema_is_422(self) -> None:
        request = urllib.request.Request(
            self.base_url + "/v1/systemone",
            data=b'{"model":"jev-latest","state":"x","questions":{"q":{"type":"choice"}}}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)

        error = caught.exception
        self.assertEqual(error.code, 422)
        detail = json.load(error)["detail"]
        error.close()
        self.assertEqual(detail["error_type"], "schema_error")

    def test_documented_example_request_is_valid(self) -> None:
        example = json.loads(
            Path(__file__).parents[1]
            .joinpath("playground", "example_request.json")
            .read_text(encoding="utf-8")
        )
        request = urllib.request.Request(
            self.base_url + "/v1/systemone",
            data=json.dumps(example).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            result = json.load(response)

        self.assertEqual(result["model"], "openjev-0.1")


class AuthHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        handler = type(
            "AuthTestMacJevHandler",
            (MacJevHandler,),
            {
                "service": DecisionService(MockBackend()),
                "api_key": "api-secret",
                "origin_secret": "origin-secret",
            },
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, headers: dict[str, str]) -> urllib.request.Request:
        return urllib.request.Request(
            self.base_url + "/v1/systemone",
            data=json.dumps(
                {
                    "model": "jev-latest",
                    "state": "x",
                    "questions": {
                        "q": {"type": "noul", "instructions": "Is this true?"}
                    },
                }
            ).encode(),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )

    def test_requires_origin_secret(self) -> None:
        with urllib.request.urlopen(self.base_url + "/health") as response:
            self.assertEqual(json.load(response)["status"], "ok")

        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(
                self.request({"Authorization": "Bearer api-secret"})
            )
        error = caught.exception
        self.assertEqual(error.code, 403)
        self.assertEqual(json.load(error)["detail"]["error_type"], "permission_error")
        error.close()

    def test_requires_valid_bearer_token(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(
                self.request(
                    {
                        "Authorization": "Bearer wrong",
                        "X-Origin-Secret": "origin-secret",
                    }
                )
            )
        error = caught.exception
        self.assertEqual(error.code, 401)
        self.assertEqual(
            json.load(error)["detail"]["error_type"], "authentication_error"
        )
        error.close()

    def test_rejects_non_bearer_authorization(self) -> None:
        for authorization in ("api-secret", "Basic api-secret"):
            with self.subTest(authorization=authorization):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(
                        self.request(
                            {
                                "Authorization": authorization,
                                "X-Origin-Secret": "origin-secret",
                            }
                        )
                    )
                error = caught.exception
                self.assertEqual(error.code, 403)
                self.assertEqual(
                    json.load(error)["detail"]["error_type"],
                    "authentication_error",
                )
                error.close()

    def test_accepts_valid_auth(self) -> None:
        with urllib.request.urlopen(
            self.request(
                {
                    "Authorization": "Bearer api-secret",
                    "X-Origin-Secret": "origin-secret",
                }
            )
        ) as response:
            result = json.load(response)

        self.assertEqual(result["model"], "openjev-0.1")


class PlaygroundEntrypointAuthTests(unittest.TestCase):
    def test_environment_auth_is_enforced_by_playground_entrypoint(self) -> None:
        cases = (
            (
                {"OPENJEV_ORIGIN_SECRET": "origin-secret"},
                {},
                {"X-Origin-Secret": "origin-secret"},
            ),
            (
                {"OPENJEV_API_KEY": "api-secret"},
                {},
                {"Authorization": "Bearer api-secret"},
            ),
        )
        for environment, unauthorized_headers, authorized_headers in cases:
            with self.subTest(environment=environment):
                self._exercise_entrypoint(
                    environment, unauthorized_headers, authorized_headers
                )

    def _exercise_entrypoint(
        self,
        extra_environment: dict[str, str],
        unauthorized_headers: dict[str, str],
        authorized_headers: dict[str, str],
    ) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        environment = os.environ.copy()
        environment.pop("OPENJEV_API_KEY", None)
        environment.pop("OPENJEV_ORIGIN_SECRET", None)
        environment.update(extra_environment)
        environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")

        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "playground.run_mock",
                "--port",
                str(port),
            ],
            cwd=Path(__file__).parents[1],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 10
            while True:
                if process.poll() is not None:
                    output, _ = process.communicate()
                    self.fail(f"playground exited before becoming healthy:\n{output}")
                try:
                    with urllib.request.urlopen(base_url + "/health", timeout=0.2):
                        break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() >= deadline:
                        self.fail("playground did not become healthy")
                    time.sleep(0.05)

            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(
                    urllib.request.Request(
                        base_url + "/v1/models", headers=unauthorized_headers
                    )
                )
            error = caught.exception
            self.assertEqual(error.code, 403)
            error.close()

            with urllib.request.urlopen(
                urllib.request.Request(
                    base_url + "/v1/models", headers=authorized_headers
                )
            ) as response:
                self.assertIn("models", json.load(response))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()


if __name__ == "__main__":
    unittest.main()
