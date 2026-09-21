from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from macjev.config import load_config
from macjev.errors import DaemonError
from macjev.supervisor import RuntimeSupervisor


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            value = {"status": "ok"}
        elif self.path == "/v1/models":
            value = {"data": [{"id": "test"}]}
        else:
            self.send_error(404)
            return
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class SupervisorTests(unittest.TestCase):
    def test_downloads_missing_model_before_starting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model"
            config_path = root / "config.toml"
            config_path.write_text(
                f"""
[server]
host = "127.0.0.1"
port = 18091

[backend]
type = "diffgemma"
base_url = "http://127.0.0.1:18080"
model = "test"

[daemon]
managed = true
executable = "diffgemma"
model_path = "{model}"

[paths]
run_dir = "{root / 'run'}"
log_dir = "{root / 'log'}"
""",
                encoding="utf-8",
            )
            supervisor = RuntimeSupervisor(load_config(config_path))

            def download(command, **kwargs):
                model.mkdir()
                return mock.Mock(returncode=0, stdout="", stderr="")

            with (
                mock.patch.object(supervisor, "_healthy", side_effect=[False, True]),
                mock.patch("macjev.supervisor.subprocess.run", side_effect=download) as run,
                mock.patch("macjev.supervisor.subprocess.Popen") as popen,
                mock.patch.object(supervisor, "_write_pid"),
            ):
                popen.return_value.pid = 12345
                pid, started = supervisor.start()

            self.assertEqual((pid, started), (12345, True))
            self.assertEqual(
                run.call_args.args[0],
                [
                    "diffgemma",
                    "download",
                    "--repo",
                    "mmastrac/diffgemma-26b-a4b-it-q4",
                    "--revision",
                    "be312db884e99c963518a5e5a97de6080263f2a8",
                    "-o",
                    str(model.resolve()),
                ],
            )

    def test_model_download_failure_aborts_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model"
            config_path = root / "config.toml"
            config_path.write_text(
                f"""
[server]
host = "127.0.0.1"
port = 18091

[backend]
type = "diffgemma"
base_url = "http://127.0.0.1:18080"
model = "test"

[daemon]
managed = true
executable = "diffgemma"
model_path = "{model}"

[paths]
run_dir = "{root / 'run'}"
log_dir = "{root / 'log'}"
""",
                encoding="utf-8",
            )
            supervisor = RuntimeSupervisor(load_config(config_path))

            with (
                mock.patch("macjev.supervisor.subprocess.run") as run,
                mock.patch("macjev.supervisor.subprocess.Popen") as popen,
            ):
                run.return_value = mock.Mock(
                    returncode=1,
                    stdout="",
                    stderr="network unavailable",
                )
                with self.assertRaisesRegex(DaemonError, "network unavailable"):
                    supervisor.start()

            popen.assert_not_called()

    def test_builds_managed_diffgemma_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model"
            model.mkdir()
            config_path = root / "config.toml"
            config_path.write_text(
                f"""
[server]
host = "127.0.0.1"
port = 18091

[backend]
type = "diffgemma"
base_url = "http://127.0.0.1:18080"
model = "diffgemma-26b-a4b-it-q4"

[daemon]
managed = true
executable = "diffgemma"
model_path = "{model}"
context_size = 4096
extra_args = ["--temperature", "0"]

[paths]
run_dir = "{root / 'run'}"
log_dir = "{root / 'log'}"
""",
                encoding="utf-8",
            )
            config = load_config(config_path)
            command = RuntimeSupervisor(config).build_command()

            self.assertEqual(
                command,
                [
                    "diffgemma",
                    "-m",
                    str(model.resolve()),
                    "--addr",
                    "127.0.0.1:18080",
                    "--ctx",
                    "4096",
                    "serve",
                    "--temperature",
                    "0",
                ],
            )

    def test_healthy_external_backend_is_not_stopped(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                config_path = root / "config.toml"
                config_path.write_text(
                    f"""
[server]
host = "127.0.0.1"
port = 18091

[backend]
type = "diffgemma"
base_url = "http://127.0.0.1:{server.server_port}"
model = "test"

[daemon]
managed = false

[paths]
run_dir = "{root / 'run'}"
log_dir = "{root / 'log'}"
""",
                    encoding="utf-8",
                )
                supervisor = RuntimeSupervisor(load_config(config_path))

                pid, started = supervisor.start()

                self.assertIsNone(pid)
                self.assertFalse(started)
                self.assertFalse(supervisor.stop())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_unmanaged_unhealthy_backend_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "config.toml"
            config_path.write_text(
                f"""
[server]
host = "127.0.0.1"
port = 18091

[backend]
type = "diffgemma"
base_url = "http://127.0.0.1:1"
model = "test"

[daemon]
managed = false

[paths]
run_dir = "{root / 'run'}"
log_dir = "{root / 'log'}"
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DaemonError, "daemon.managed is false"):
                RuntimeSupervisor(load_config(config_path)).start()

    def test_unmanaged_mode_never_stops_stale_pid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            run_dir.mkdir()
            (run_dir / "diffgemma.pid").write_text(
                json.dumps(
                    {
                        "pid": 12345,
                        "started_at": "old-start",
                        "command": ["diffgemma old"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            config_path = root / "config.toml"
            config_path.write_text(
                f"""
[server]
host = "127.0.0.1"
port = 18091

[backend]
type = "diffgemma"
base_url = "http://127.0.0.1:1"
model = "test"

[daemon]
managed = false
model_path = "{root / 'model'}"

[paths]
run_dir = "{run_dir}"
log_dir = "{root / 'log'}"
""",
                encoding="utf-8",
            )
            supervisor = RuntimeSupervisor(load_config(config_path))

            with mock.patch("macjev.supervisor.os.kill") as kill:
                self.assertFalse(supervisor.stop())
            kill.assert_not_called()

    def test_mismatched_process_identity_is_not_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            run_dir.mkdir()
            pid_file = run_dir / "diffgemma.pid"
            pid_file.write_text(
                json.dumps(
                    {
                        "pid": 12345,
                        "started_at": "old-start",
                        "command": ["diffgemma old"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            config_path = root / "config.toml"
            config_path.write_text(
                f"""
[server]
host = "127.0.0.1"
port = 18091

[backend]
type = "diffgemma"
base_url = "http://127.0.0.1:1"
model = "test"

[daemon]
managed = true
model_path = "{root / 'model'}"

[paths]
run_dir = "{run_dir}"
log_dir = "{root / 'log'}"
""",
                encoding="utf-8",
            )
            supervisor = RuntimeSupervisor(load_config(config_path))

            with (
                mock.patch.object(
                    supervisor,
                    "_process_started_at",
                    return_value="new-start",
                ),
                mock.patch.object(
                    supervisor,
                    "_process_command",
                    return_value=["diffgemma new"],
                ),
                mock.patch("macjev.supervisor.os.kill") as kill,
            ):
                self.assertFalse(supervisor.stop())
            kill.assert_not_called()
            self.assertFalse(pid_file.exists())

    def test_tampered_identity_cannot_stop_unrelated_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            run_dir.mkdir()
            pid_file = run_dir / "diffgemma.pid"
            pid_file.write_text(
                json.dumps(
                    {
                        "pid": 12345,
                        "started_at": "same-start",
                        "command": ["python unrelated.py"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            config_path = root / "config.toml"
            config_path.write_text(
                f"""
[server]
host = "127.0.0.1"
port = 18091

[backend]
type = "diffgemma"
base_url = "http://127.0.0.1:1"
model = "test"

[daemon]
managed = true
model_path = "{root / 'model'}"

[paths]
run_dir = "{run_dir}"
log_dir = "{root / 'log'}"
""",
                encoding="utf-8",
            )
            supervisor = RuntimeSupervisor(load_config(config_path))

            with (
                mock.patch.object(
                    supervisor,
                    "_process_started_at",
                    return_value="same-start",
                ),
                mock.patch.object(
                    supervisor,
                    "_process_command",
                    return_value=["python unrelated.py"],
                ),
                mock.patch("macjev.supervisor.os.kill") as kill,
            ):
                with self.assertRaisesRegex(DaemonError, "does not match"):
                    supervisor.stop()
            kill.assert_not_called()

    def test_configured_command_with_spaces_matches_posix_ps_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model with spaces"
            model.mkdir()
            config_path = root / "config.toml"
            config_path.write_text(
                f"""
[server]
host = "127.0.0.1"
port = 18091

[backend]
type = "diffgemma"
base_url = "http://127.0.0.1:18080"
model = "test"

[daemon]
managed = true
executable = "diffgemma"
model_path = "{model}"

[paths]
run_dir = "{root / 'run'}"
log_dir = "{root / 'log'}"
""",
                encoding="utf-8",
            )
            supervisor = RuntimeSupervisor(load_config(config_path))
            configured = supervisor.build_command()

            supervisor._assert_configured_command(
                {"command": [" ".join(configured)]}
            )

    def test_changed_configured_command_is_not_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "config.toml"
            config_path.write_text(
                f"""
[server]
host = "127.0.0.1"
port = 18091

[backend]
type = "diffgemma"
base_url = "http://127.0.0.1:18080"
model = "test"

[daemon]
managed = true
executable = "diffgemma"
model_path = "{root / 'model'}"

[paths]
run_dir = "{root / 'run'}"
log_dir = "{root / 'log'}"
""",
                encoding="utf-8",
            )
            supervisor = RuntimeSupervisor(load_config(config_path))

            with self.assertRaisesRegex(DaemonError, "does not match"):
                supervisor._assert_configured_command(
                    {"command": ["diffgemma -m /old/model serve"]}
                )


if __name__ == "__main__":
    unittest.main()
