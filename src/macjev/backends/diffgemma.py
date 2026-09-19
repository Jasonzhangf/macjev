"""HTTP client for the local Apple Silicon diffgemma server."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..errors import BackendError


class DiffGemmaBackend:
    """Talk to `diffgemma serve` over its OpenAI-compatible HTTP API."""

    name = "diffgemma-metal"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model: str = "diffgemma-26b-a4b-it-q4",
        timeout_seconds: float = 180.0,
        schema_options: dict[str, Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.schema_options = dict(schema_options or {})

    def health(self) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/health", headers={"Accept": "application/json"}
        )
        return self._request_json(request)

    def models(self) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/v1/models", headers={"Accept": "application/json"}
        )
        return self._request_json(request)

    def decide(self, state: Any, schema: dict[str, Any]) -> dict[str, Any]:
        if self.schema_options:
            schema = dict(schema)
            schema.update(self.schema_options)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": json.dumps(schema, ensure_ascii=False)},
                {
                    "role": "user",
                    "content": json.dumps({"state": state}, ensure_ascii=False),
                },
            ],
            "stream": False,
        }
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        response = self._request_json(request)
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise BackendError(f"unexpected diffgemma response envelope: {exc}") from exc

        if isinstance(content, dict):
            parsed = content
        else:
            try:
                parsed = json.loads(content)
            except (TypeError, json.JSONDecodeError) as exc:
                raise BackendError("diffgemma content is not structured JSON") from exc

        if not isinstance(parsed, dict) or not isinstance(parsed.get("answers"), dict):
            raise BackendError("diffgemma content has no answers object")
        parsed.setdefault("diagnostics", {})
        parsed["diagnostics"]["backend"] = self.name
        parsed["diagnostics"]["is_mock"] = False
        parsed["diagnostics"]["model"] = self.model
        return parsed

    def _request_json(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise BackendError(
                f"diffgemma HTTP {exc.code}: {detail[:500]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise BackendError(
                f"diffgemma is unavailable at {self.base_url}: {exc.reason}"
            ) from exc

        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BackendError("diffgemma returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise BackendError("diffgemma returned a non-object JSON value")
        return value
