"""Run the Jev API with the real Mac diffgemma backend."""

from __future__ import annotations

import argparse

from macjev.backends.diffgemma import DiffGemmaBackend
from macjev.http import serve
from macjev.service import DecisionService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--upstream", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="diffgemma-26b-a4b-it-q4")
    args = parser.parse_args()

    backend = DiffGemmaBackend(args.upstream, args.model)
    health = backend.health()
    print(f"macjev: upstream health={health}")
    serve(DecisionService(backend), args.host, args.port)


if __name__ == "__main__":
    main()
