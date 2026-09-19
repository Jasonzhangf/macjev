"""TOML configuration for the MacJev production runtime."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import ConfigError

DEFAULT_CONFIG_PATH = Path("~/.macjev/config.toml").expanduser()
DEFAULT_MODEL_PATH = Path("~/code/macjev/model/diffgemma-26b-a4b-it-q4").expanduser()


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    max_body_bytes: int


@dataclass(frozen=True)
class BackendConfig:
    type: str
    base_url: str
    model: str
    timeout_seconds: float
    schema_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DaemonConfig:
    managed: bool
    executable: str
    model_path: Path | None
    context_size: int
    extra_args: tuple[str, ...]
    startup_timeout_seconds: float
    poll_interval_seconds: float
    working_dir: Path | None = None


@dataclass(frozen=True)
class PathsConfig:
    run_dir: Path
    log_dir: Path


@dataclass(frozen=True)
class AuthConfig:
    api_key: str = ""
    origin_secret: str = ""


@dataclass(frozen=True)
class MacJevConfig:
    source: Path
    server: ServerConfig
    backend: BackendConfig
    daemon: DaemonConfig
    paths: PathsConfig
    auth: AuthConfig


def _table(data: dict[str, Any], key: str, *, required: bool = True) -> dict[str, Any]:
    value = data.get(key)
    if value is None and not required:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be a TOML table")
    return value


def _text(
    data: dict[str, Any],
    key: str,
    *,
    default: str | None = None,
    required: bool = True,
) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value.strip():
        if not required and value == "":
            return ""
        raise ConfigError(f"{key} must be a non-empty string")
    return value.strip()


def _number(
    data: dict[str, Any],
    key: str,
    *,
    default: float,
    minimum: float,
) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key} must be numeric")
    value = float(value)
    if value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}")
    return value


def _integer(
    data: dict[str, Any],
    key: str,
    *,
    default: int,
    minimum: int,
) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer")
    if value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}")
    return value


def _boolean(data: dict[str, Any], key: str, *, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be a boolean")
    return value


def _path(value: str, *, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _validate_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("backend.base_url must be an http or https URL")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ConfigError("backend.base_url must not include a path, query, or fragment")
    return value.rstrip("/")


def load_config(path: str | Path | None = None) -> MacJevConfig:
    """Load and validate the single runtime configuration file."""

    source = Path(path or DEFAULT_CONFIG_PATH).expanduser().resolve()
    if not source.is_file():
        raise ConfigError(
            f"configuration file does not exist: {source}; run `macjev config init`"
        )

    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read configuration {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("configuration root must be a TOML table")

    base = source.parent
    server_data = _table(data, "server")
    backend_data = _table(data, "backend")
    daemon_data = _table(data, "daemon")
    paths_data = _table(data, "paths")
    auth_data = _table(data, "auth", required=False)

    server = ServerConfig(
        host=_text(server_data, "host", default="127.0.0.1"),
        port=_integer(server_data, "port", default=8091, minimum=1),
        max_body_bytes=_integer(
            server_data, "max_body_bytes", default=1_048_576, minimum=1
        ),
    )
    if server.port > 65535:
        raise ConfigError("server.port must be <= 65535")

    backend = BackendConfig(
        type=_text(backend_data, "type", default="diffgemma"),
        base_url=_validate_url(
            _text(backend_data, "base_url", default="http://127.0.0.1:8080")
        ),
        model=_text(
            backend_data,
            "model",
            default="diffgemma-26b-a4b-it-q4",
        ),
        timeout_seconds=_number(
            backend_data, "timeout_seconds", default=180.0, minimum=0.1
        ),
        schema_options=_table(backend_data, "schema_options", required=False),
    )
    if backend.type != "diffgemma":
        raise ConfigError("backend.type must be diffgemma for the production runtime")

    model_path_value = daemon_data.get("model_path")
    model_path = (
        _path(model_path_value, base=base)
        if isinstance(model_path_value, str) and model_path_value.strip()
        else None
    )
    working_dir_value = daemon_data.get("working_dir")
    working_dir = (
        _path(working_dir_value, base=base)
        if isinstance(working_dir_value, str) and working_dir_value.strip()
        else None
    )
    extra_args = daemon_data.get("extra_args", [])
    if not isinstance(extra_args, list) or not all(
        isinstance(value, str) for value in extra_args
    ):
        raise ConfigError("daemon.extra_args must be an array of strings")

    daemon = DaemonConfig(
        managed=_boolean(daemon_data, "managed", default=True),
        executable=_text(
            daemon_data,
            "executable",
            default="diffgemma",
        ),
        model_path=model_path,
        context_size=_integer(
            daemon_data,
            "context_size",
            default=131072,
            minimum=1,
        ),
        extra_args=tuple(extra_args),
        startup_timeout_seconds=_number(
            daemon_data,
            "startup_timeout_seconds",
            default=180.0,
            minimum=0.1,
        ),
        poll_interval_seconds=_number(
            daemon_data,
            "poll_interval_seconds",
            default=0.5,
            minimum=0.01,
        ),
        working_dir=working_dir,
    )
    if daemon.managed and daemon.model_path is None:
        raise ConfigError("daemon.model_path is required when daemon.managed is true")
    if daemon.managed and not backend.base_url.startswith("http://"):
        raise ConfigError("managed daemon requires backend.base_url to use http://")

    paths = PathsConfig(
        run_dir=_path(
            _text(paths_data, "run_dir", default="~/.macjev/run"),
            base=base,
        ),
        log_dir=_path(
            _text(paths_data, "log_dir", default="~/.macjev/log"),
            base=base,
        ),
    )
    auth = AuthConfig(
        api_key=_text(auth_data, "api_key", default="", required=False),
        origin_secret=_text(auth_data, "origin_secret", default="", required=False),
    )

    return MacJevConfig(
        source=source,
        server=server,
        backend=backend,
        daemon=daemon,
        paths=paths,
        auth=auth,
    )


def default_config_text(
    *,
    server_host: str = "127.0.0.1",
    server_port: int = 8091,
    model_path: str | Path = DEFAULT_MODEL_PATH,
) -> str:
    """Return a complete, explicit starter configuration."""

    return f"""\
[server]
host = "{server_host}"
port = {server_port}
max_body_bytes = 1048576

[backend]
type = "diffgemma"
base_url = "http://127.0.0.1:8080"
model = "diffgemma-26b-a4b-it-q4"
timeout_seconds = 180.0

[backend.schema_options]

[daemon]
managed = true
executable = "diffgemma"
model_path = "{Path(model_path).expanduser()}"
context_size = 131072
extra_args = []
startup_timeout_seconds = 180.0
poll_interval_seconds = 0.5

[paths]
run_dir = "~/.macjev/run"
log_dir = "~/.macjev/log"

[auth]
api_key = ""
origin_secret = ""
"""


def write_default_config(
    path: str | Path | None = None,
    *,
    force: bool = False,
    model_path: str | Path = DEFAULT_MODEL_PATH,
) -> Path:
    """Create the starter config without silently overwriting an existing one."""

    target = Path(path or DEFAULT_CONFIG_PATH).expanduser().resolve()
    if target.exists() and not force:
        raise ConfigError(f"configuration already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        default_config_text(model_path=model_path),
        encoding="utf-8",
    )
    os.chmod(target, 0o600)
    return target
