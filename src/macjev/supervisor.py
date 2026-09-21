"""Process lifecycle for the managed DiffusionGemma daemon."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import MacJevConfig
from .errors import DaemonError

MODEL_REPO = "mmastrac/diffgemma-26b-a4b-it-q4"
MODEL_REVISION = "be312db884e99c963518a5e5a97de6080263f2a8"


@dataclass(frozen=True)
class DaemonStatus:
    managed: bool
    pid: int | None
    alive: bool
    healthy: bool
    pid_file: Path
    log_file: Path

    def as_dict(self) -> dict[str, object]:
        return {
            "managed": self.managed,
            "pid": self.pid,
            "alive": self.alive,
            "healthy": self.healthy,
            "pid_file": str(self.pid_file),
            "log_file": str(self.log_file),
        }


class RuntimeSupervisor:
    """Start, inspect, and stop only the daemon owned by this config."""

    def __init__(self, config: MacJevConfig) -> None:
        self.config = config
        self.pid_file = config.paths.run_dir / "diffgemma.pid"
        self.log_file = config.paths.log_dir / "diffgemma.log"

    def build_command(self) -> list[str]:
        daemon = self.config.daemon
        if daemon.model_path is None:
            raise DaemonError("daemon.model_path is not configured")
        backend_url = self.config.backend.base_url
        if backend_url.startswith("http://"):
            address = backend_url.removeprefix("http://")
        elif backend_url.startswith("https://"):
            address = backend_url.removeprefix("https://")
        else:
            raise DaemonError("daemon backend URL must use http")
        return [
            daemon.executable,
            "-m",
            str(daemon.model_path),
            "--addr",
            address,
            "--ctx",
            str(daemon.context_size),
            "serve",
            *daemon.extra_args,
        ]

    def status(self) -> DaemonStatus:
        identity = self._read_pid()
        pid = identity["pid"] if identity is not None else None
        alive = identity is not None and self._matches_identity(identity)
        return DaemonStatus(
            managed=self.config.daemon.managed,
            pid=pid,
            alive=alive,
            healthy=self._healthy(),
            pid_file=self.pid_file,
            log_file=self.log_file,
        )

    def start(self) -> tuple[int | None, bool]:
        """Ensure the configured backend is healthy.

        Returns ``(pid, started_by_this_call)``. An already healthy external
        backend is left untouched and returns ``(None, False)``.
        """

        status = self.status()
        if status.healthy:
            if status.pid is not None and not status.alive:
                self._remove_pid_file()
            return status.pid, False
        if not self.config.daemon.managed:
            raise DaemonError(
                f"backend is unhealthy at {self.config.backend.base_url} "
                "and daemon.managed is false"
            )
        if status.pid is not None and status.alive:
            raise DaemonError(
                f"diffgemma pid {status.pid} is alive but not healthy; "
                f"inspect {self.log_file}"
            )
        if status.pid is not None:
            self._remove_pid_file()

        self.config.paths.run_dir.mkdir(parents=True, exist_ok=True)
        self.config.paths.log_dir.mkdir(parents=True, exist_ok=True)
        if self.config.daemon.model_path is None:
            raise DaemonError("daemon.model_path is not configured")
        if not self.config.daemon.model_path.is_dir():
            self._download_model()
        if self.config.daemon.working_dir is not None and not self.config.daemon.working_dir.is_dir():
            raise DaemonError(
                f"daemon.working_dir is not a directory: {self.config.daemon.working_dir}"
            )
        command = self.build_command()
        try:
            with self.log_file.open("ab", buffering=0) as log:
                process = subprocess.Popen(
                    command,
                    cwd=self.config.daemon.working_dir or Path.cwd(),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
        except OSError as exc:
            raise DaemonError(
                f"cannot start diffgemma executable {self.config.daemon.executable!r}: {exc}"
            ) from exc

        try:
            self._write_pid(process.pid)
        except DaemonError:
            self._terminate_pid(process.pid)
            raise
        try:
            self.wait_until_healthy()
        except DaemonError:
            identity = self._read_pid()
            if identity is not None and identity["pid"] == process.pid:
                self._terminate_pid(process.pid)
            self._remove_pid_file()
            raise
        return process.pid, True

    def _download_model(self) -> None:
        assert self.config.daemon.model_path is not None
        target = self.config.daemon.model_path
        target.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.config.daemon.executable,
            "download",
            "--repo",
            MODEL_REPO,
            "--revision",
            MODEL_REVISION,
            "-o",
            str(target),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=self.config.daemon.working_dir or Path.cwd(),
                text=True,
                capture_output=True,
            )
        except OSError as exc:
            raise DaemonError(
                f"cannot download model with {self.config.daemon.executable!r}: {exc}"
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise DaemonError(f"model download failed for {target}: {detail}")
        if not target.is_dir():
            raise DaemonError(f"model download did not create {target}")

    def stop(self) -> bool:
        """Stop the daemon recorded in the PID file.

        The PID file is the ownership boundary. A healthy external server
        without a PID file is never stopped.
        """

        if not self.config.daemon.managed:
            return False
        identity = self._read_pid()
        if identity is None:
            return False
        pid = identity["pid"]
        if not self._matches_identity(identity):
            self._remove_pid_file()
            return False
        self._assert_configured_command(identity)
        self._terminate_pid(pid)
        self._remove_pid_file()
        return True

    def wait_until_healthy(self) -> None:
        deadline = time.monotonic() + self.config.daemon.startup_timeout_seconds
        while time.monotonic() < deadline:
            if self._healthy():
                return
            time.sleep(self.config.daemon.poll_interval_seconds)
        raise DaemonError(
            f"diffgemma did not become healthy at {self.config.backend.base_url} "
            f"within {self.config.daemon.startup_timeout_seconds:.1f}s; "
            f"inspect {self.log_file}"
        )

    def _healthy(self) -> bool:
        health = self._request_json("/health")
        if not isinstance(health, dict) or health.get("status") != "ok":
            return False
        models = self._request_json("/v1/models")
        if not isinstance(models, dict) or not isinstance(models.get("data"), list):
            return False
        return any(
            isinstance(model, dict)
            and model.get("id") == self.config.backend.model
            for model in models["data"]
        )

    def _request_json(self, path: str) -> object | None:
        request = urllib.request.Request(
            f"{self.config.backend.base_url}{path}",
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=2.0) as response:
                body = response.read()
        except (OSError, urllib.error.URLError):
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None

    def _read_pid(self) -> dict[str, object] | None:
        if not self.pid_file.is_file():
            return None
        try:
            value = json.loads(self.pid_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DaemonError(f"invalid PID file {self.pid_file}: {exc}") from exc
        if not isinstance(value, dict):
            raise DaemonError(f"invalid PID file {self.pid_file}: expected an object")
        pid = value.get("pid")
        started_at = value.get("started_at")
        command = value.get("command")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise DaemonError(f"invalid PID in {self.pid_file}: {pid!r}")
        if not isinstance(started_at, str) or not started_at:
            raise DaemonError(
                f"invalid process start identity in {self.pid_file}"
            )
        if not isinstance(command, list) or not command or not all(
            isinstance(argument, str) for argument in command
        ):
            raise DaemonError(f"invalid process command in {self.pid_file}")
        return {"pid": pid, "started_at": started_at, "command": command}

    def _write_pid(self, pid: int) -> None:
        temporary = self.pid_file.with_suffix(".tmp")
        started_at = self._process_started_at(pid)
        command = self._process_command(pid)
        if not started_at or not command:
            raise DaemonError(
                f"cannot establish identity for managed diffgemma pid {pid}"
            )
        identity = {
            "pid": pid,
            "started_at": started_at,
            "command": command,
        }
        temporary.write_text(
            json.dumps(identity, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.pid_file)

    def _remove_pid_file(self) -> None:
        try:
            self.pid_file.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _process_started_at(pid: int) -> str:
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "lstart="],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return ""
        return result.stdout.strip()

    def _matches_identity(self, identity: dict[str, object]) -> bool:
        pid = identity["pid"]
        started_at = identity["started_at"]
        command = identity["command"]
        if (
            not isinstance(pid, int)
            or not isinstance(started_at, str)
            or not isinstance(command, list)
        ):
            return False
        return (
            self._process_started_at(pid) == started_at
            and self._process_command(pid) == command
        )

    def _assert_configured_command(self, identity: dict[str, object]) -> None:
        command = identity["command"]
        configured = self.build_command()
        if command != [" ".join(configured)]:
            raise DaemonError(
                "refusing to stop daemon; live command does not match the "
                "configured managed command"
            )

    @staticmethod
    def _process_command(pid: int) -> list[str]:
        try:
            result = subprocess.run(
                ["ps", "-ww", "-p", str(pid), "-o", "command="],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return []
        command = result.stdout.strip()
        return [command] if command else []

    @staticmethod
    def _is_alive(pid: int) -> bool:
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "stat="],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return False
        return not result.stdout.strip().startswith("Z")

    def _terminate_pid(self, pid: int) -> None:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + self.config.daemon.startup_timeout_seconds
        while time.monotonic() < deadline:
            if not self._is_alive(pid):
                return
            time.sleep(self.config.daemon.poll_interval_seconds)
        raise DaemonError(
            f"diffgemma pid {pid} did not stop within "
            f"{self.config.daemon.startup_timeout_seconds:.1f}s"
        )
