from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from macjev.backends.mock import MockBackend
from macjev.http import MacJevHandler
from macjev.service import DecisionService


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
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

    def get_json(self, path: str) -> dict:
        with urllib.request.urlopen(self.base_url + path) as response:
            return json.load(response)

    def test_health_and_models(self) -> None:
        self.assertEqual(self.get_json("/health")["backend"], "mock")
        self.assertEqual(
            self.get_json("/v1/models")["data"][0]["id"],
            "macjev-playground",
        )

    def test_systemone(self) -> None:
        request = urllib.request.Request(
            self.base_url + "/v1/systemone",
            data=json.dumps(
                {
                    "state": "Production outage",
                    "questions": {"urgent": {"type": "noul"}},
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            result = json.load(response)

        self.assertTrue(result["diagnostics"]["is_mock"])
        self.assertEqual(
            result["diagnostics"]["raw_backend_response"]["diagnostics"]["backend"],
            "mock",
        )

    def test_invalid_schema_is_422(self) -> None:
        request = urllib.request.Request(
            self.base_url + "/v1/systemone",
            data=b'{"state":"x","questions":{"q":{"type":"choice"}}}',
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


if __name__ == "__main__":
    unittest.main()
