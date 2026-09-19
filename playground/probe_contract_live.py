"""Exercise the MacJev TypeSafe contract against the real Metal backend."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
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

    request_body = json.loads(args.request.read_text(encoding="utf-8"))
    backend = DiffGemmaBackend(args.upstream, args.model)
    started = time.perf_counter()
    result = DecisionService(backend).decide(request_body)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    public_result = {
        "model": result["model"],
        "answers": result["answers"],
        "usage": result["usage"],
    }

    print("REQUEST")
    print(json.dumps(request_body, indent=2, ensure_ascii=False))
    print("PUBLIC_RESULT")
    print(json.dumps(public_result, indent=2, ensure_ascii=False))
    print("DIAGNOSTICS")
    print(json.dumps(result["diagnostics"], indent=2, ensure_ascii=False))
    print(f"elapsed_ms={elapsed_ms:.1f}")


if __name__ == "__main__":
    main()
