"""Probe a local diffgemma server with a Jev-shaped decision request."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from macjev.backends.diffgemma import DiffGemmaBackend
from macjev.service import DecisionService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="diffgemma-26b-a4b-it-q4")
    parser.add_argument(
        "--request",
        type=Path,
        default=Path(__file__).with_name("example_request.json"),
    )
    args = parser.parse_args()

    backend = DiffGemmaBackend(args.upstream, args.model)
    print(json.dumps(backend.health(), indent=2, ensure_ascii=False))
    print(json.dumps(backend.models(), indent=2, ensure_ascii=False))

    request = json.loads(args.request.read_text(encoding="utf-8"))
    started = time.perf_counter()
    result = DecisionService(backend).decide(request)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    raw = result["diagnostics"]["raw_backend_response"]
    print("RAW_BACKEND_RESPONSE")
    print(json.dumps(raw, indent=2, ensure_ascii=False))
    print("NORMALIZED_RESULT")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"elapsed_ms={elapsed_ms:.1f}")


if __name__ == "__main__":
    main()
