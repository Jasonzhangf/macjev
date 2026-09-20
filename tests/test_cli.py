from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macjev.cli import _build_parser, _optiq_serve, _serve
from macjev.errors import BackendError, DaemonError


class CliServeTests(unittest.TestCase):
    def test_optiq_serve_builds_python_launcher_command(self) -> None:
        args = _build_parser().parse_args(
            [
                "optiq-serve",
                "--python",
                "/tmp/optiq/bin/python",
                "--model",
                "/tmp/model",
                "--host",
                "127.0.0.1",
                "--port",
                "18092",
                "--",
                "--max-context",
                "32768",
            ]
        )

        self.assertEqual(args.command, "optiq-serve")
        self.assertEqual(args.python, "/tmp/optiq/bin/python")
        self.assertEqual(args.model, "/tmp/model")
        self.assertEqual(args.extra_args, ["--max-context", "32768"])

    def test_optiq_serve_runs_launcher_with_source_on_pythonpath(self) -> None:
        args = argparse.Namespace(
            python="/tmp/optiq/bin/python",
            model="/tmp/model",
            host="127.0.0.1",
            port=18092,
            extra_args=["--max-context", "32768"],
        )

        with mock.patch("macjev.cli.subprocess.run") as run:
            run.return_value.returncode = 0
            self.assertEqual(_optiq_serve(args), 0)

        command = run.call_args.args[0]
        self.assertEqual(
            command,
            [
                "/tmp/optiq/bin/python",
                "-m",
                "macjev.optiq_serve",
                "serve",
                "--model",
                "/tmp/model",
                "--host",
                "127.0.0.1",
                "--port",
                "18092",
                "--max-context",
                "32768",
            ],
        )
        source_root = str(Path(__file__).resolve().parents[1] / "src")
        self.assertEqual(
            run.call_args.kwargs["env"]["PYTHONPATH"].split(":", 1)[0],
            source_root,
        )

    def test_optiq_serve_reports_interrupt_without_traceback(self) -> None:
        args = argparse.Namespace(
            python="/tmp/optiq/bin/python",
            model="/tmp/model",
            host="127.0.0.1",
            port=18092,
            extra_args=[],
        )

        with mock.patch(
            "macjev.cli.subprocess.run",
            side_effect=KeyboardInterrupt,
        ):
            self.assertEqual(_optiq_serve(args), 130)

    def test_health_failure_stops_daemon_started_by_this_call(self) -> None:
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
            args = argparse.Namespace(
                config=str(config_path),
                no_daemon=False,
            )

            with (
                mock.patch(
                    "macjev.cli.RuntimeSupervisor.start",
                    return_value=(12345, True),
                ),
                mock.patch("macjev.cli.RuntimeSupervisor.stop") as stop,
                mock.patch(
                    "macjev.cli.DiffGemmaBackend.ensure_ready",
                    side_effect=BackendError("not ready"),
                ),
            ):
                with self.assertRaisesRegex(DaemonError, "not ready"):
                    _serve(args)

            stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
