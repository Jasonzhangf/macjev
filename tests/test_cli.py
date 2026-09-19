from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macjev.cli import _serve
from macjev.errors import BackendError, DaemonError


class CliServeTests(unittest.TestCase):
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
