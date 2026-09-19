"""Run the protocol playground with an explicit mock backend."""

from __future__ import annotations

import argparse

from macjev.backends.mock import MockBackend
from macjev.http import serve
from macjev.service import DecisionService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    serve(DecisionService(MockBackend()), args.host, args.port)


if __name__ == "__main__":
    main()
