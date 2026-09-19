"""Command-line entry point for the MacJev runtime."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .backends.diffgemma import DiffGemmaBackend
from .config import (
    DEFAULT_CONFIG_PATH,
    MacJevConfig,
    load_config,
    write_default_config,
)
from .errors import ConfigError, DaemonError, MacJevError
from .http import serve
from .service import DecisionService
from .supervisor import RuntimeSupervisor


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="macjev")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="runtime configuration file",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_parser = subparsers.add_parser("config", help="manage configuration")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    init_parser = config_subparsers.add_parser("init", help="write a starter config")
    init_parser.add_argument("--force", action="store_true")
    init_parser.add_argument("--model-path")

    daemon_parser = subparsers.add_parser("daemon", help="manage the model daemon")
    daemon_subparsers = daemon_parser.add_subparsers(
        dest="daemon_command", required=True
    )
    daemon_subparsers.add_parser("start")
    daemon_subparsers.add_parser("stop")
    daemon_subparsers.add_parser("status")

    serve_parser = subparsers.add_parser("serve", help="start the Jev API server")
    serve_parser.add_argument(
        "--no-daemon",
        action="store_true",
        help="do not start the managed model daemon",
    )
    return parser


def _load(args: argparse.Namespace) -> MacJevConfig:
    return load_config(args.config)


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _config_init(args: argparse.Namespace) -> int:
    kwargs = {"force": args.force}
    if args.model_path:
        kwargs["model_path"] = args.model_path
    target = write_default_config(args.config, **kwargs)
    print(f"macjev: wrote {target}")
    return 0


def _daemon(args: argparse.Namespace) -> int:
    config = _load(args)
    supervisor = RuntimeSupervisor(config)
    if args.daemon_command == "start":
        pid, started = supervisor.start()
        if started:
            print(f"macjev: started diffgemma pid={pid}")
        else:
            print("macjev: diffgemma already healthy")
        return 0
    if args.daemon_command == "stop":
        stopped = supervisor.stop()
        print("macjev: stopped diffgemma" if stopped else "macjev: diffgemma not running")
        return 0
    _print_json(supervisor.status().as_dict())
    return 0


def _serve(args: argparse.Namespace) -> int:
    config = _load(args)
    supervisor: RuntimeSupervisor | None = None
    started_pid: int | None = None
    if not args.no_daemon:
        supervisor = RuntimeSupervisor(config)
        pid, started = supervisor.start()
        if started:
            started_pid = pid
            print(f"macjev: started diffgemma pid={pid}")
    try:
        backend = DiffGemmaBackend(
            base_url=config.backend.base_url,
            model=config.backend.model,
            timeout_seconds=config.backend.timeout_seconds,
            schema_options=config.backend.schema_options,
        )
        backend.ensure_ready()
        serve(
            DecisionService(backend),
            config.server.host,
            config.server.port,
            api_key=config.auth.api_key,
            origin_secret=config.auth.origin_secret,
            max_body_bytes=config.server.max_body_bytes,
        )
    except MacJevError as exc:
        raise DaemonError(
            f"backend health check failed at {config.backend.base_url}: {exc}"
        ) from exc
    finally:
        if supervisor is not None and started_pid is not None:
            supervisor.stop()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "config":
            return _config_init(args)
        if args.command == "daemon":
            return _daemon(args)
        if args.command == "serve":
            return _serve(args)
    except (ConfigError, DaemonError, MacJevError) as exc:
        print(f"macjev: error: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
