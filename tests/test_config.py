from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from macjev.config import load_config, write_default_config
from macjev.errors import ConfigError


class ConfigTests(unittest.TestCase):
    def test_default_config_is_complete_and_loadable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.toml"
            model_path = Path(temporary) / "model"
            model_path.mkdir()
            write_default_config(path, model_path=model_path)

            config = load_config(path)

            self.assertEqual(config.server.host, "127.0.0.1")
            self.assertEqual(config.server.port, 8091)
            self.assertEqual(config.backend.type, "diffgemma")
            self.assertEqual(config.backend.model, "diffgemma-26b-a4b-it-q4")
            self.assertEqual(config.daemon.model_path, model_path.resolve())
            self.assertTrue(config.daemon.managed)

    def test_missing_config_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "missing.toml"
            with self.assertRaisesRegex(ConfigError, "does not exist"):
                load_config(path)

    def test_rejects_unknown_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.toml"
            path.write_text(
                """
[server]
host = "127.0.0.1"
port = 8091

[backend]
type = "other"
base_url = "http://127.0.0.1:8080"
model = "model"

[daemon]
managed = false

[paths]
run_dir = "run"
log_dir = "log"
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "backend.type"):
                load_config(path)

    def test_rejects_managed_https_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model"
            model.mkdir()
            path = root / "config.toml"
            path.write_text(
                f"""
[server]
host = "127.0.0.1"
port = 8091

[backend]
type = "diffgemma"
base_url = "https://127.0.0.1:8080"
model = "test"

[daemon]
managed = true
model_path = "{model}"

[paths]
run_dir = "run"
log_dir = "log"
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "http://"):
                load_config(path)

    def test_non_utf8_config_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.toml"
            path.write_bytes(b"\xff\xfe\x00")
            with self.assertRaisesRegex(ConfigError, "cannot read configuration"):
                load_config(path)

    def test_does_not_overwrite_existing_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.toml"
            path.write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "already exists"):
                write_default_config(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "existing")


if __name__ == "__main__":
    unittest.main()
