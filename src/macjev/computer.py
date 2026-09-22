"""Standard computer-use boundary over structured desktop priors."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Protocol

from .errors import MacJevError


class ComputerDriverError(MacJevError):
    """The native desktop driver failed explicitly."""

    error_type = "computer_driver_error"


class ComputerRequestError(MacJevError):
    """The caller sent a malformed or non-admitted computer-use request."""

    error_type = "computer_request_error"


class ComputerDriver(Protocol):
    """Provide window observation and bounded operations."""

    name: str

    def list_windows(self) -> list[dict[str, Any]]:
        """Return capturable application windows."""

    def observe(self, window: str) -> dict[str, Any]:
        """Return a fresh AX tree, screenshot, and revision."""

    def act(self, request: dict[str, Any]) -> dict[str, Any]:
        """Perform one admitted operation."""

    def hit_test(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return the accessibility element at one window point."""


class MacOSComputerDriver:
    """Compile and invoke the native macOS accessibility driver."""

    name = "macos-ax"

    def __init__(
        self,
        *,
        source_path: Path | None = None,
        binary_path: Path | None = None,
        compile_timeout_seconds: float = 60.0,
        command_timeout_seconds: float = 30.0,
        screenshot_dir: Path | None = None,
        screenshot_retention: int = 200,
    ) -> None:
        self.source_path = source_path or Path(__file__).with_name(
            "computer_driver.swift"
        )
        self.binary_path = binary_path or _home_dir() / "bin" / "macjev-computer-driver"
        self.compile_timeout_seconds = compile_timeout_seconds
        self.command_timeout_seconds = command_timeout_seconds
        self.screenshot_dir = screenshot_dir or _home_dir() / "computer"
        self.observation_dir = self.screenshot_dir / "observations"
        self.screenshot_retention = screenshot_retention
        self.socket_path = _home_dir() / "run" / "computer-driver.sock"
        self.pid_path = _home_dir() / "run" / "computer-driver.pid"
        self.log_path = _home_dir() / "log" / "computer-driver.log"
        self._socket: socket.socket | None = None

    def _ensure_binary(self) -> Path:
        if not self.source_path.is_file():
            raise ComputerDriverError(
                f"native computer driver source is missing: {self.source_path}"
            )
        digest = _sha256_file(self.source_path)
        stamp_path = self.binary_path.with_suffix(".digest")
        if self.binary_path.is_file() and stamp_path.is_file():
            if stamp_path.read_text(encoding="utf-8").strip() == digest:
                return self.binary_path
        self.binary_path.parent.mkdir(parents=True, exist_ok=True)
        staging = self.binary_path.with_suffix(".staging")
        completed = subprocess.run(
            [
                "swiftc",
                "-parse-as-library",
                "-O",
                "-o",
                str(staging),
                str(self.source_path),
            ],
            text=True,
            capture_output=True,
            timeout=self.compile_timeout_seconds,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise ComputerDriverError(f"cannot compile native computer driver: {detail}")
        os.replace(staging, self.binary_path)
        stamp_path.write_text(digest, encoding="utf-8")
        return self.binary_path

    def _run(self, arguments: list[str]) -> dict[str, Any]:
        # Mutating commands must never be retried on another transport: a
        # dropped response could otherwise execute the same action twice.
        retryable = arguments[0] in {"list-windows", "observe", "hit-test"}
        value = self._run_socket(arguments, retryable=retryable)
        if value is not None:
            return value
        binary = self._ensure_binary()
        try:
            completed = subprocess.run(
                [str(binary), *arguments],
                text=True,
                capture_output=True,
                timeout=self.command_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ComputerDriverError(
                f"native computer driver timed out after "
                f"{self.command_timeout_seconds}s"
            ) from exc
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise ComputerDriverError(
                f"native computer driver returned invalid JSON: {detail[:500]}"
            ) from exc
        if completed.returncode != 0:
            error = value.get("error") if isinstance(value, dict) else None
            if isinstance(error, dict):
                raise ComputerDriverError(
                    f"{error.get('code', 'driver_error')}: "
                    f"{error.get('message', 'unknown driver failure')}"
                )
            raise ComputerDriverError(
                f"native computer driver exited {completed.returncode}"
            )
        if not isinstance(value, dict):
            raise ComputerDriverError("native computer driver returned a non-object")
        return value

    def _run_socket(
        self,
        arguments: list[str],
        *,
        retryable: bool,
    ) -> dict[str, Any] | None:
        """Use the shared driver socket when one is live; else fall back to exec.

        Returns ``None`` only when nothing was sent, so a caller may safely use
        another transport. Once a request is on the wire, failures raise.
        """

        if not self.socket_path.is_socket():
            return None
        if self._socket is None:
            try:
                connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                connection.settimeout(self.command_timeout_seconds)
                connection.connect(str(self.socket_path))
            except OSError:
                self._socket = None
                return None
            self._socket = connection
        payload = _socket_request(arguments)
        try:
            self._socket.sendall(json.dumps(payload).encode() + b"\n")
            line = _read_line(self._socket)
        except OSError as exc:
            self._socket = None
            if retryable:
                return None
            raise ComputerDriverError(
                f"computer driver socket failed after sending "
                f"{arguments[0]}: {exc}"
            ) from exc
        if line is None:
            self._socket = None
            if retryable:
                return None
            raise ComputerDriverError(
                f"computer driver socket closed before replying to {arguments[0]}"
            )
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            self._socket = None
            raise ComputerDriverError(
                f"computer driver socket returned invalid JSON: {line[:200]}"
            ) from exc
        if not isinstance(value, dict):
            raise ComputerDriverError("computer driver socket returned a non-object")
        if "error" in value:
            error = value["error"]
            if isinstance(error, dict):
                raise ComputerDriverError(
                    f"{error.get('code', 'driver_error')}: "
                    f"{error.get('message', 'unknown driver failure')}"
                )
            raise ComputerDriverError("computer driver socket returned an error")
        return value

    def status(self) -> dict[str, Any]:
        """Report the owned driver daemon without starting one."""

        pid = self._read_pid()
        alive = pid is not None and _process_alive(pid)
        return {
            "pid": pid,
            "alive": alive,
            "socket_path": str(self.socket_path),
            "socket_present": self.socket_path.is_socket(),
            "pid_path": str(self.pid_path),
            "log_path": str(self.log_path),
        }

    def start(self) -> tuple[int, bool]:
        """Ensure the driver daemon is live. Returns (pid, started_here)."""

        status = self.status()
        if status["alive"] and status["socket_present"]:
            return int(status["pid"]), False
        self.stop()
        binary = self._ensure_binary()
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("ab", buffering=0) as log:
            process = subprocess.Popen(
                [str(binary), "serve", "--socket", str(self.socket_path)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        self.pid_path.write_text(
            json.dumps({"pid": process.pid}, ensure_ascii=False),
            encoding="utf-8",
        )
        deadline = time.monotonic() + self.compile_timeout_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self._remove_pid_file()
                raise ComputerDriverError(
                    f"computer driver exited during startup; inspect {self.log_path}"
                )
            if self.socket_path.is_socket():
                return process.pid, True
            time.sleep(0.05)
        self.stop()
        raise ComputerDriverError(
            f"computer driver did not open {self.socket_path} before timeout"
        )

    def stop(self) -> bool:
        """Stop only the driver recorded in our PID file."""

        pid = self._read_pid()
        if pid is not None and _process_alive(pid):
            try:
                os.kill(pid, 15)
            except OSError as exc:
                raise ComputerDriverError(
                    f"cannot stop computer driver pid {pid}: {exc}"
                ) from exc
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and _process_alive(pid):
                time.sleep(0.05)
            if _process_alive(pid):
                raise ComputerDriverError(
                    f"computer driver pid {pid} did not exit after SIGTERM"
                )
        self._remove_pid_file()
        self.socket_path.unlink(missing_ok=True)
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        return pid is not None

    def _read_pid(self) -> int | None:
        if not self.pid_path.is_file():
            return None
        try:
            value = json.loads(self.pid_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        pid = value.get("pid") if isinstance(value, dict) else None
        return pid if isinstance(pid, int) and pid > 0 else None

    def _remove_pid_file(self) -> None:
        self.pid_path.unlink(missing_ok=True)

    def list_windows(self) -> list[dict[str, Any]]:
        value = self._run(["list-windows"])
        windows = value.get("windows")
        if not isinstance(windows, list) or not all(
            isinstance(window, dict) for window in windows
        ):
            raise ComputerDriverError("native computer driver returned invalid windows")
        return windows

    def observe(self, window: str) -> dict[str, Any]:
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="observe-",
            suffix=".png",
            dir=self.screenshot_dir,
            delete=False,
        ) as output:
            screenshot_path = Path(output.name)
        try:
            value = self._run(
                [
                    "observe",
                    "--window",
                    window,
                    "--output",
                    str(screenshot_path),
                ]
            )
        except MacJevError:
            screenshot_path.unlink(missing_ok=True)
            raise
        screenshot = Path(value.get("screenshot_path", screenshot_path))
        if not screenshot.is_file():
            raise ComputerDriverError("native computer driver did not write a screenshot")
        screenshot_digest = str(
            value.get("visual_digest") or _sha256_file(screenshot)
        )
        self._prune_screenshots()
        return {
            **value,
            "screenshot_ref": f"file://{screenshot}",
            "screenshot_digest": screenshot_digest,
        }

    def _prune_screenshots(self) -> None:
        if self.screenshot_retention <= 0:
            return
        artifacts = sorted(
            self.screenshot_dir.glob("observe-*.png"),
            key=lambda path: path.stat().st_mtime,
        )
        for path in artifacts[: max(0, len(artifacts) - self.screenshot_retention)]:
            path.unlink(missing_ok=True)

    def persist_observation(
        self,
        observation: dict[str, Any],
        request: dict[str, Any],
    ) -> Path:
        """Write one observation so other processes can resume its revision."""

        self.observation_dir.mkdir(parents=True, exist_ok=True)
        revision = str(observation["revision"])
        path = self.observation_dir / f"{revision.replace(':', '-')}.json"
        path.write_text(
            json.dumps(
                {
                    "window": observation["window"],
                    "revision": revision,
                    "elements": observation["elements"],
                    "truncated": observation.get("truncated", False),
                    "accessibility": observation.get("accessibility", "unknown"),
                    "screenshot": {
                        "ref": observation["screenshot_ref"],
                        "digest": observation["screenshot_digest"],
                        "width": observation.get("screenshot_width", 0),
                        "height": observation.get("screenshot_height", 0),
                        "scale": observation.get("screenshot_scale", 1.0),
                    },
                    "request": {"window": request.get("window")},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        if self.screenshot_retention > 0:
            stored = sorted(
                self.observation_dir.glob("*.json"),
                key=lambda item: item.stat().st_mtime,
            )
            for stale in stored[: max(0, len(stored) - self.screenshot_retention)]:
                stale.unlink(missing_ok=True)
        return path

    def load_observation(self, revision: str) -> dict[str, Any] | None:
        path = self.observation_dir / f"{revision.replace(':', '-')}.json"
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        screenshot = value.pop("screenshot")
        return {
            **value,
            "screenshot_ref": screenshot.get("ref", ""),
            "screenshot_digest": screenshot.get("digest", ""),
            "screenshot_width": screenshot.get("width", 0),
            "screenshot_height": screenshot.get("height", 0),
            "screenshot_scale": screenshot.get("scale", 1.0),
        }

    def act(self, request: dict[str, Any]) -> dict[str, Any]:
        operation = request["operation"]
        kind = operation.get("kind")
        if kind == "set_value":
            arguments = [
                "set-value",
                "--window",
                str(request["window_id"]),
                "--element",
                str(operation["element_id"]),
                "--value",
                str(operation["value"]),
            ]
        elif kind == "type_text":
            arguments = [
                "type-text",
                "--window",
                str(request["window_id"]),
                "--text",
                str(operation["text"]),
                "--expect-role",
                str(operation["expect_role"]),
                "--expect-identifier",
                str(operation["expect_identifier"]),
            ]
            if operation.get("expect_title") is not None:
                arguments += ["--expect-title", str(operation["expect_title"])]
        elif kind == "key_tap":
            arguments = [
                "key-tap",
                "--window",
                str(request["window_id"]),
                "--key",
                str(operation["key"]),
                "--expect-role",
                str(operation["expect_role"]),
                "--expect-identifier",
                str(operation["expect_identifier"]),
            ]
            if operation.get("expect_title") is not None:
                arguments += ["--expect-title", str(operation["expect_title"])]
            if operation.get("modifiers"):
                arguments += ["--modifiers", ",".join(operation["modifiers"])]
        elif kind == "scroll":
            arguments = [
                "scroll",
                "--window",
                str(request["window_id"]),
                "--x",
                str(operation["point"]["x"]),
                "--y",
                str(operation["point"]["y"]),
                "--dx",
                str(operation.get("dx", 0)),
                "--dy",
                str(operation.get("dy", 0)),
            ]
        elif kind == "mouse_move":
            arguments = [
                "mouse-move",
                "--window",
                str(request["window_id"]),
                "--x",
                str(operation["point"]["x"]),
                "--y",
                str(operation["point"]["y"]),
            ]
        elif kind == "drag":
            arguments = [
                "drag",
                "--window",
                str(request["window_id"]),
                "--x",
                str(operation["from"]["x"]),
                "--y",
                str(operation["from"]["y"]),
                "--to-x",
                str(operation["to"]["x"]),
                "--to-y",
                str(operation["to"]["y"]),
            ]
            if operation.get("steps") is not None:
                arguments += ["--steps", str(operation["steps"])]
        elif operation.get("mode") == "point":
            arguments = [
                "click-point",
                "--window",
                str(request["window_id"]),
                "--x",
                str(operation["point"]["x"]),
                "--y",
                str(operation["point"]["y"]),
            ]
        elif operation.get("mode") == "element":
            arguments = [
                "click-element",
                "--window",
                str(request["window_id"]),
                "--element",
                str(operation["element_id"]),
            ]
        else:
            raise ComputerDriverError(
                f"unsupported click mode {operation.get('mode')!r}"
            )
        return self._run(arguments)

    def hit_test(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._run(
            [
                "hit-test",
                "--window",
                str(request["window_id"]),
                "--x",
                str(request["point"]["x"]),
                "--y",
                str(request["point"]["y"]),
            ]
        )

    def window_at_point(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return the topmost on-screen window containing one screen point."""

        return self._run(
            [
                "window-at-point",
                "--x",
                str(request["point"]["x"]),
                "--y",
                str(request["point"]["y"]),
            ]
        )

    def mouse_move(self, request: dict[str, Any]) -> dict[str, Any]:
        """Move the pointer to one window point without pressing a button."""

        return self._run(
            [
                "mouse-move",
                "--window",
                str(request["window_id"]),
                "--x",
                str(request["point"]["x"]),
                "--y",
                str(request["point"]["y"]),
            ]
        )

    def drag(self, request: dict[str, Any]) -> dict[str, Any]:
        """Press at one window point, interpolate to another, and release."""

        arguments = [
            "drag",
            "--window",
            str(request["window_id"]),
            "--x",
            str(request["from"]["x"]),
            "--y",
            str(request["from"]["y"]),
            "--to-x",
            str(request["to"]["x"]),
            "--to-y",
            str(request["to"]["y"]),
        ]
        if request.get("steps") is not None:
            arguments += ["--steps", str(request["steps"])]
        if request.get("button") is not None:
            arguments += ["--button", str(request["button"])]
        return self._run(arguments)

    def scroll(self, request: dict[str, Any]) -> dict[str, Any]:
        """Scroll at one window point by a pixel delta."""

        return self._run(
            [
                "scroll",
                "--window",
                str(request["window_id"]),
                "--x",
                str(request["point"]["x"]),
                "--y",
                str(request["point"]["y"]),
                "--dx",
                str(request.get("dx", 0)),
                "--dy",
                str(request.get("dy", 0)),
            ]
        )

    def type_text(self, request: dict[str, Any]) -> dict[str, Any]:
        """Type text into the asserted focus holder.

        Keyboard input carries no coordinates, so the driver refuses to post it
        unless the caller names the element that must hold focus. Without that
        assertion a mis-click silently writes into the wrong control.
        """

        arguments = [
            "type-text",
            "--text",
            str(request["text"]),
            "--window",
            str(request["window_id"]),
            "--expect-role",
            str(request["expect_role"]),
            "--expect-identifier",
            str(request.get("expect_identifier", "")),
        ]
        if request.get("expect_title") is not None:
            arguments += ["--expect-title", str(request["expect_title"])]
        if request.get("modifiers"):
            arguments += ["--modifiers", ",".join(request["modifiers"])]
        return self._run(arguments)

    def key_tap(self, request: dict[str, Any]) -> dict[str, Any]:
        """Post one named key to the asserted focus holder."""

        arguments = [
            "key-tap",
            "--key",
            str(request["key"]),
            "--window",
            str(request["window_id"]),
            "--expect-role",
            str(request["expect_role"]),
            "--expect-identifier",
            str(request.get("expect_identifier", "")),
        ]
        if request.get("expect_title") is not None:
            arguments += ["--expect-title", str(request["expect_title"])]
        if request.get("modifiers"):
            arguments += ["--modifiers", ",".join(request["modifiers"])]
        return self._run(arguments)


def _home_dir() -> Path:
    override = os.environ.get("MACJEV_HOME")
    if override:
        return Path(override).expanduser()
    return Path("~/.macjev").expanduser()


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _socket_request(arguments: list[str]) -> dict[str, Any]:
    """Translate the CLI-shaped argument list into a socket request."""

    command = arguments[0]
    request: dict[str, Any] = {"command": command}
    index = 1
    while index + 1 < len(arguments):
        flag = arguments[index]
        value = arguments[index + 1]
        if flag == "--window":
            request["window"] = value
        elif flag == "--output":
            request["output"] = value
        elif flag == "--element":
            request["element"] = value
        elif flag == "--value":
            request["value"] = value
        elif flag == "--text":
            request["text"] = value
        elif flag == "--key":
            request["key"] = value
        elif flag == "--button":
            request["button"] = value
        elif flag == "--expect-role":
            request["expect_role"] = value
        elif flag == "--expect-identifier":
            request["expect_identifier"] = value
        elif flag == "--expect-title":
            request["expect_title"] = value
        elif flag == "--modifiers":
            request["modifiers"] = [item for item in value.split(",") if item]
        elif flag == "--x":
            request["x"] = float(value)
        elif flag == "--y":
            request["y"] = float(value)
        elif flag == "--to-x":
            request["to_x"] = float(value)
        elif flag == "--to-y":
            request["to_y"] = float(value)
        elif flag == "--dx":
            request["dx"] = float(value)
        elif flag == "--dy":
            request["dy"] = float(value)
        elif flag == "--steps":
            request["steps"] = int(value)
        elif flag == "--count":
            request["count"] = int(value)
        elif flag == "--activate":
            request["activate"] = value.lower() in {"1", "true", "yes"}
        # An unrecognized flag is dropped on purpose: the socket protocol is
        # command-and-argument, and the driver rejects unknown commands itself.
        index += 2
    return request


def _read_line(connection: socket.socket) -> str | None:
    chunks = bytearray()
    while True:
        byte = connection.recv(1)
        if not byte:
            return bytes(chunks).decode("utf-8") if chunks else None
        if byte == b"\n":
            return bytes(chunks).decode("utf-8")
        chunks.extend(byte)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


class ComputerService:
    """Validate and guard operations against one fresh observation."""

    SUPPORTED_OPERATIONS = {
        "click",
        "set_value",
        "type_text",
        "key_tap",
        "scroll",
        "drag",
        "mouse_move",
    }

    def __init__(self, driver: ComputerDriver) -> None:
        self.driver = driver
        self._observations: dict[str, dict[str, Any]] = {}

    def _resolve_observation(self, revision: str) -> dict[str, Any] | None:
        observation = self._observations.get(revision)
        if observation is not None:
            return observation
        loader = getattr(self.driver, "load_observation", None)
        if loader is None:
            return None
        try:
            value = loader(revision)
        except MacJevError:
            return None
        if value is None:
            return None
        self._observations[revision] = value
        return value

    def load_observation(self, value: dict[str, Any]) -> str:
        """Restore one previously observed revision without re-observing."""

        revision = _required_text(value, "revision")
        if not isinstance(value.get("window"), dict) or not isinstance(
            value.get("elements"), list
        ):
            raise ComputerRequestError("observation is missing window or elements")
        screenshot = value.get("screenshot")
        if not isinstance(screenshot, dict):
            raise ComputerRequestError("observation is missing screenshot")
        self._observations[revision] = {
            "window": value["window"],
            "revision": revision,
            "elements": value["elements"],
            "screenshot_ref": screenshot.get("ref", ""),
            "screenshot_digest": screenshot.get("digest", ""),
            "screenshot_width": screenshot.get("width", 0),
            "screenshot_height": screenshot.get("height", 0),
            "screenshot_scale": screenshot.get("scale", 1.0),
            "truncated": value.get("truncated", False),
        }
        return revision

    def observe(self, request: dict[str, Any]) -> dict[str, Any]:
        window = _required_text(request, "window")
        started = time.monotonic()
        observation = self.driver.observe(window)
        revision = _required_text(observation, "revision")
        self._observations[revision] = observation
        persist = getattr(self.driver, "persist_observation", None)
        if persist is not None:
            persist(observation, request)
        return {
            "api_version": "1",
            "request_id": request.get("request_id"),
            "revision": revision,
            "window": observation["window"],
            "screenshot": {
                "ref": observation["screenshot_ref"],
                "digest": observation["screenshot_digest"],
                "width": observation["screenshot_width"],
                "height": observation["screenshot_height"],
                "scale": observation["screenshot_scale"],
            },
            "elements": observation["elements"],
            "truncated": observation["truncated"],
            "diagnostics": {
                "driver": self.driver.name,
                "accessibility": observation.get("accessibility", "unknown"),
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
            },
        }

    def guard(self, request: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        revision = _required_text(request, "revision")
        observation = self._resolve_observation(revision)
        if observation is None:
            return _guard_result(
                request,
                "deny",
                "stale_revision",
                "revision has no active observation",
                started,
            )
        operation = _required_mapping(request, "operation")
        operation_kind = _required_text(operation, "kind")
        if operation_kind not in self.SUPPORTED_OPERATIONS:
            return _guard_result(
                request,
                "unknown",
                "operation_unsupported",
                f"operation kind {operation_kind!r} is not supported",
                started,
            )
        if operation_kind == "set_value":
            return self._guard_set_value(request, observation, operation, started)
        if operation_kind == "type_text":
            return self._guard_type_text(request, observation, operation, started)
        if operation_kind == "key_tap":
            return self._guard_key_tap(request, observation, operation, started)
        if operation_kind in {"scroll", "mouse_move"}:
            return self._guard_point_operation(
                request, observation, operation, operation_kind, started
            )
        if operation_kind == "drag":
            return self._guard_drag(request, observation, operation, started)
        element_id = operation.get("element_id")
        if isinstance(element_id, str) and element_id:
            return self._guard_click_element(
                request, observation, element_id, started
            )
        point = operation.get("point")
        if isinstance(point, dict):
            return self._guard_click_point(
                request, observation, operation, point, started
            )
        return _guard_result(
            request,
            "unknown",
            "operation_target_missing",
            "click requires element_id or point",
            started,
        )

    def _guard_click_element(
        self,
        request: dict[str, Any],
        observation: dict[str, Any],
        element_id: str,
        started: float,
    ) -> dict[str, Any]:
        element = _find_element(observation, element_id)
        if element is None:
            return _guard_result(
                request,
                "deny",
                "candidate_not_found",
                "element_id is not in the bound observation",
                started,
            )
        if element.get("enabled") is False:
            return _guard_result(
                request,
                "deny",
                "element_disabled",
                "selected element is disabled",
                started,
            )
        actions = element.get("actions")
        if not isinstance(actions, list) or "AXPress" not in actions:
            return _guard_result(
                request,
                "unknown",
                "element_action_unavailable",
                "selected element does not expose AXPress",
                started,
            )
        box = _element_box(element)
        if box is None:
            return _guard_result(
                request,
                "unknown",
                "element_geometry_missing",
                "selected element has no position and size",
                started,
            )
        if not _box_intersects_window(box, observation["window"]["bounds"]):
            return _guard_result(
                request,
                "deny",
                "element_outside_window",
                "selected element is outside the bound window",
                started,
            )
        return _guard_result(
            request,
            "allow",
            "structured_prior_match",
            "element belongs to the bound revision and exposes AXPress",
            started,
        )

    def _guard_set_value(
        self,
        request: dict[str, Any],
        observation: dict[str, Any],
        operation: dict[str, Any],
        started: float,
    ) -> dict[str, Any]:
        element_id = _required_text(operation, "element_id")
        value = operation.get("value")
        if not isinstance(value, str):
            return _guard_result(
                request,
                "unknown",
                "operation_value_missing",
                "set_value requires a string value",
                started,
            )
        element = _find_element(observation, element_id)
        if element is None:
            return _guard_result(
                request,
                "deny",
                "candidate_not_found",
                "element_id is not in the bound observation",
                started,
            )
        if element.get("enabled") is False:
            return _guard_result(
                request,
                "deny",
                "element_disabled",
                "selected element is disabled",
                started,
            )
        settable = element.get("settable")
        if settable is False:
            return _guard_result(
                request,
                "unknown",
                "element_value_not_settable",
                "selected element does not expose a settable value",
                started,
            )
        return _guard_result(
            request,
            "allow",
            "structured_prior_match",
            "element belongs to the bound revision and is writable",
            started,
        )

    def _guard_click_point(
        self,
        request: dict[str, Any],
        observation: dict[str, Any],
        operation: dict[str, Any],
        point: dict[str, Any],
        started: float,
    ) -> dict[str, Any]:
        expected = operation.get("expected_element_id")
        try:
            x = float(point["x"])
            y = float(point["y"])
        except (KeyError, TypeError, ValueError):
            return _guard_result(
                request,
                "unknown",
                "point_invalid",
                "click point requires numeric x and y",
                started,
            )
        if not _point_in_window(x, y, observation["window"]["bounds"]):
            return _guard_result(
                request,
                "deny",
                "point_outside_window",
                "click point is outside the bound window",
                started,
            )
        try:
            hit = self.driver.hit_test(
                {
                    "window_id": observation["window"]["window_id"],
                    "point": {"x": x, "y": y},
                }
            )
        except MacJevError as exc:
            return _guard_result(
                request,
                "unknown",
                "hit_test_unavailable",
                str(exc),
                started,
            )
        hit_id = hit.get("element_id")
        if not isinstance(expected, str) or not expected:
            return _guard_result(
                request,
                "unknown",
                "point_identity_unverified",
                f"click point maps to {hit_id!r}; no expected_element_id was supplied",
                started,
            )
        occlusion = self._occlusion_verdict(observation, x, y)
        if occlusion is not None:
            return _guard_result(
                request,
                "deny",
                "point_occluded",
                occlusion,
                started,
            )
        element = _find_element(observation, expected)
        if element is None:
            return _guard_result(
                request,
                "deny",
                "candidate_not_found",
                "expected_element_id is not in the bound observation",
                started,
            )
        if hit_id != expected and not _hit_is_within(hit, element, x, y):
            return _guard_result(
                request,
                "deny",
                "point_target_mismatch",
                f"click point maps to {hit_id!r}, not {expected!r}",
                started,
            )
        return _guard_result(
            request,
            "allow",
            "hit_test_match",
            "click point maps to the expected element",
            started,
        )

    def _guard_type_text(
        self,
        request: dict[str, Any],
        observation: dict[str, Any],
        operation: dict[str, Any],
        started: float,
    ) -> dict[str, Any]:
        """Type text is bounded by its focus target, not by a point.

        The text lands wherever focus sits, so the guard checks the element that
        is supposed to hold focus instead of guessing coordinates.
        """

        text = operation.get("text")
        if not isinstance(text, str) or not text:
            return _guard_result(
                request,
                "deny",
                "text_missing",
                "type_text requires non-empty text",
                started,
            )
        return self._guard_focus_target(
            request, observation, operation, "type_text", started
        )

    def _guard_focus_target(
        self,
        request: dict[str, Any],
        observation: dict[str, Any],
        operation: dict[str, Any],
        kind: str,
        started: float,
    ) -> dict[str, Any]:
        """Admit a keyboard operation only against a verified focus holder.

        Keystrokes carry no coordinates, so the element holding focus is the
        whole target. The observed identity is copied onto the operation so the
        driver can re-assert it at post time, after the click that was supposed
        to grant focus has already run.
        """

        expected = operation.get("expected_element_id")
        if not isinstance(expected, str) or not expected:
            return _guard_result(
                request,
                "unknown",
                "focus_target_unverified",
                f"{kind} requires expected_element_id to bind keyboard focus",
                started,
            )
        element = _find_element(observation, expected)
        if element is None:
            return _guard_result(
                request,
                "deny",
                "candidate_not_found",
                "expected_element_id is not in the bound observation",
                started,
            )
        if element.get("enabled") is False:
            return _guard_result(
                request,
                "deny",
                "element_disabled",
                "focus target is disabled",
                started,
            )
        if element.get("focused") is not True:
            return _guard_result(
                request,
                "deny",
                "focus_target_not_focused",
                f"element {expected!r} is not the keyboard focus holder",
                started,
            )
        focus_identity = _focus_identity(element)
        if focus_identity is None:
            return _guard_result(
                request,
                "unknown",
                "focus_identity_incomplete",
                "focus target has no role to assert against",
                started,
            )
        operation["expect_role"] = focus_identity["role"]
        operation["expect_identifier"] = focus_identity["identifier"]
        operation["expect_title"] = focus_identity["title"]
        return _guard_result(
            request,
            "allow",
            "focus_target_match",
            "keyboard focus is on the expected element",
            started,
        )

    def _guard_key_tap(
        self,
        request: dict[str, Any],
        observation: dict[str, Any],
        operation: dict[str, Any],
        started: float,
    ) -> dict[str, Any]:
        key = operation.get("key")
        if not isinstance(key, str) or not key:
            return _guard_result(
                request,
                "deny",
                "key_missing",
                "key_tap requires a key name",
                started,
            )
        window = observation["window"]
        if window.get("on_screen") is False:
            return _guard_result(
                request,
                "deny",
                "window_offscreen",
                "keyboard input would go to an off-screen window",
                started,
            )
        # A keystroke is delivered to the focus holder, so admitting a key tap
        # without naming that holder would let the event land anywhere.
        return self._guard_focus_target(
            request, observation, operation, "key_tap", started
        )

    def _guard_point_operation(
        self,
        request: dict[str, Any],
        observation: dict[str, Any],
        operation: dict[str, Any],
        kind: str,
        started: float,
    ) -> dict[str, Any]:
        """Bound a point-driven input at the window and occlusion level."""

        point = _required_mapping(operation, "point")
        x = point.get("x")
        y = point.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return _guard_result(
                request,
                "deny",
                "point_invalid",
                f"{kind} requires numeric point x and y",
                started,
            )
        bounds = observation["window"]["bounds"]
        if not (
            bounds["x"] <= float(x) <= bounds["x"] + bounds["width"]
            and bounds["y"] <= float(y) <= bounds["y"] + bounds["height"]
        ):
            return _guard_result(
                request,
                "deny",
                "point_outside_window",
                f"point {x},{y} is outside the bound window",
                started,
            )
        occlusion = self._occlusion_verdict(observation, float(x), float(y))
        if occlusion is not None:
            return _guard_result(request, "deny", "point_occluded", occlusion, started)
        return _guard_result(
            request,
            "allow",
            "point_in_window",
            f"{kind} point is inside the bound window",
            started,
        )

    def _guard_drag(
        self,
        request: dict[str, Any],
        observation: dict[str, Any],
        operation: dict[str, Any],
        started: float,
    ) -> dict[str, Any]:
        """A drag needs both endpoints admissible, not just its start."""

        for key in ("from", "to"):
            endpoint = operation.get(key)
            if not isinstance(endpoint, dict):
                return _guard_result(
                    request,
                    "deny",
                    "drag_endpoint_missing",
                    f"drag requires a {key!r} point",
                    started,
                )
            verdict = self._guard_point_operation(
                request,
                observation,
                {"point": endpoint},
                f"drag {key}",
                started,
            )
            if verdict["verdict"] != "allow":
                return verdict
        return _guard_result(
            request,
            "allow",
            "drag_endpoints_in_window",
            "both drag endpoints are inside the bound window",
            started,
        )

    def _occlusion_verdict(
        self,
        observation: dict[str, Any],
        x: float,
        y: float,
    ) -> str | None:
        """Return a denial message when another window covers the point."""

        lookup = getattr(self.driver, "window_at_point", None)
        if lookup is None:
            return None
        window = observation["window"]
        try:
            found = lookup({"point": {"x": x, "y": y}})
        except MacJevError:
            return None
        found_id = found.get("window_id")
        if found_id is None or found_id == window["window_id"]:
            return None
        # Dock, menu bar and other chrome sit in a high layer; they do not
        # steal clicks from an application window.
        if int(found.get("layer") or 0) > 0:
            return None
        return (
            f"point {x},{y} is covered by window {found_id} "
            f"({found.get('application_name', '')!r})"
        )

    def act(self, request: dict[str, Any]) -> dict[str, Any]:
        revision = _required_text(request, "revision")
        observation = self._resolve_observation(revision)
        if observation is None:
            raise ComputerRequestError(
                "stale_revision: revision has no active observation"
            )
        operation = _required_mapping(request, "operation")
        verdict = self.guard({"revision": revision, "operation": operation})
        if verdict["verdict"] != "allow":
            raise ComputerRequestError(
                f"{verdict['reason_code']}: {verdict['message']}"
            )
        window_id = observation["window"]["window_id"]
        driver_operation: dict[str, Any] = {"kind": operation["kind"]}
        if operation["kind"] == "set_value":
            driver_operation["element_id"] = operation["element_id"]
            driver_operation["value"] = operation["value"]
        elif operation["kind"] == "type_text":
            driver_operation["text"] = operation["text"]
            for key in ("expect_role", "expect_identifier", "expect_title"):
                driver_operation[key] = operation[key]
        elif operation["kind"] == "key_tap":
            driver_operation["key"] = operation["key"]
            for key in ("expect_role", "expect_identifier", "expect_title"):
                driver_operation[key] = operation[key]
            if operation.get("modifiers"):
                driver_operation["modifiers"] = operation["modifiers"]
        elif operation["kind"] == "scroll":
            driver_operation["mode"] = "point"
            driver_operation["point"] = operation["point"]
            driver_operation["dx"] = operation.get("dx", 0)
            driver_operation["dy"] = operation.get("dy", 0)
        elif operation["kind"] == "mouse_move":
            driver_operation["mode"] = "point"
            driver_operation["point"] = operation["point"]
        elif operation["kind"] == "drag":
            driver_operation["mode"] = "drag"
            driver_operation["from"] = operation["from"]
            driver_operation["to"] = operation["to"]
            if operation.get("steps") is not None:
                driver_operation["steps"] = operation["steps"]
        elif isinstance(operation.get("point"), dict):
            driver_operation["mode"] = "point"
            driver_operation["point"] = operation["point"]
            driver_operation["verified_element_id"] = operation["expected_element_id"]
        else:
            driver_operation["mode"] = "element"
            driver_operation["element_id"] = operation["element_id"]
        result = self.driver.act(
            {
                "window_id": window_id,
                "operation": driver_operation,
            }
        )
        return {
            "api_version": "1",
            "request_id": request.get("request_id"),
            "revision": revision,
            "result": result,
        }

    def verify(self, request: dict[str, Any]) -> dict[str, Any]:
        revision = _required_text(request, "previous_revision")
        window = _required_text(request, "window")
        element_id = _required_text(request, "element_id")
        current = self.observe({"window": window})
        element = _find_element(current, element_id)
        return {
            "api_version": "1",
            "request_id": request.get("request_id"),
            "previous_revision": revision,
            "revision": current["revision"],
            "revision_changed": revision != current["revision"],
            "element": element,
            "found": element is not None,
        }


def _guard_result(
    request: dict[str, Any],
    verdict: str,
    reason_code: str,
    message: str,
    started: float,
) -> dict[str, Any]:
    return {
        "api_version": "1",
        "request_id": request.get("request_id"),
        "revision": request.get("revision"),
        "verdict": verdict,
        "reason_code": reason_code,
        "message": message,
        "diagnostics": {
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
        },
    }


def _find_element(
    observation: dict[str, Any],
    element_id: str,
) -> dict[str, Any] | None:
    elements = observation.get("elements")
    if not isinstance(elements, list):
        return None
    return next(
        (
            element
            for element in elements
            if isinstance(element, dict) and element.get("element_id") == element_id
        ),
        None,
    )


def _element_box(element: dict[str, Any]) -> tuple[float, float, float, float] | None:
    position = element.get("position")
    size = element.get("size")
    if not isinstance(position, dict) or not isinstance(size, dict):
        return None
    try:
        x = float(position["x"])
        y = float(position["y"])
        width = float(size["width"])
        height = float(size["height"])
    except (KeyError, TypeError, ValueError):
        return None
    return (x, y, x + width, y + height)


def _focus_identity(element: dict[str, Any]) -> dict[str, str] | None:
    """Return the role/identifier/title that identify a focus target.

    The driver compares these three values against what the application reports
    as its focus holder, so they must come from the same observation the caller
    was given rather than from a fresh read.
    """

    role = element.get("role")
    if not isinstance(role, str) or not role:
        return None
    identifier = element.get("identifier")
    title = element.get("title")
    return {
        "role": role,
        "identifier": identifier if isinstance(identifier, str) else "",
        "title": title if isinstance(title, str) else "",
    }


def _hit_is_within(
    hit: dict[str, Any],
    element: dict[str, Any],
    x: float,
    y: float,
) -> bool:
    """Whether a hit-test result belongs to the expected control.

    Hit-test is anchored at the application root and observe at the window
    root, so IDs legitimately differ. A hit belongs to the expected element
    when it lands inside that element's box, or the other way around.
    """

    expected = _element_box(element)
    if expected is None:
        return False
    if not (expected[0] <= x <= expected[2] and expected[1] <= y <= expected[3]):
        return False
    hit_position = hit.get("position")
    hit_size = hit.get("size")
    if not isinstance(hit_position, dict) or not isinstance(hit_size, dict):
        # The point is inside the expected control even if the hit node
        # carries no geometry of its own.
        return True
    actual = _element_box(hit)
    if actual is None:
        return True
    tolerance = 1.0
    return (
        actual[0] >= expected[0] - tolerance
        and actual[1] >= expected[1] - tolerance
        and actual[2] <= expected[2] + tolerance
        and actual[3] <= expected[3] + tolerance
    )


def _point_in_window(x: float, y: float, bounds: dict[str, Any]) -> bool:
    try:
        left = float(bounds["x"])
        top = float(bounds["y"])
        right = left + float(bounds["width"])
        bottom = top + float(bounds["height"])
    except (KeyError, TypeError, ValueError):
        return False
    return left <= x <= right and top <= y <= bottom


def _box_intersects_window(
    box: tuple[float, float, float, float],
    bounds: dict[str, Any],
) -> bool:
    try:
        left = float(bounds["x"])
        top = float(bounds["y"])
        right = left + float(bounds["width"])
        bottom = top + float(bounds["height"])
    except (KeyError, TypeError, ValueError):
        return False
    return box[0] < right and box[2] > left and box[1] < bottom and box[3] > top


def _required_mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ComputerRequestError(f"{key} must be an object")
    return item


def _required_text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ComputerRequestError(f"{key} must be a non-empty string")
    return item
