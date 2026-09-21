from __future__ import annotations

import json
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from macjev import release as release_module


def _write_project(root: Path, version: str = "0.1.0", build: int = 0) -> None:
    (root / "src" / "macjev").mkdir(parents=True)
    (root / "src" / "macjev" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f"""
[project]
name = "macjev"
version = "{version}"

[tool.macjev]
build = {build}
""",
        encoding="utf-8",
    )


class ReleaseTests(unittest.TestCase):
    def test_find_project_root_and_source_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(root)
            nested = root / "src" / "macjev"

            self.assertEqual(release_module.find_project_root(nested), root.resolve())
            self.assertEqual(release_module.source_version(nested), "0.1.0")
            self.assertEqual(release_module.build_version(nested), "0.1.0000")

    def test_bump_build_increments_only_local_build_number(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(root)

            self.assertEqual(release_module.bump_build(root), 1)
            self.assertEqual(release_module.source_version(root), "0.1.0")
            self.assertEqual(release_module.source_build(root), 1)
            self.assertEqual(release_module.build_version(root), "0.1.0001")

    def test_install_release_verifies_base_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / "macjev-0.1.2-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    "macjev-0.1.2.dist-info/METADATA",
                    "Metadata-Version: 2.4\nName: macjev\nVersion: 0.1.2+build.2\n",
                )
            with (
                mock.patch.object(
                    release_module,
                    "_macjev_command",
                    return_value="/bin/macjev",
                ),
                mock.patch.object(
                    release_module,
                    "_run",
                    side_effect=[
                        mock.Mock(stdout=""),
                        mock.Mock(stdout="macjev 0.1.0001\n"),
                    ],
                ),
            ):
                installed = release_module.install_release(
                    wheel,
                    "0.1.2+build.2",
                    display_version="0.1.0001",
                )

            self.assertEqual(installed, "0.1.0001")

    def test_install_release_rejects_wheel_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / "macjev-0.1.2-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    "macjev-0.1.2.dist-info/METADATA",
                    "Metadata-Version: 2.4\nName: macjev\nVersion: 0.1.2\n",
                )

            with mock.patch.object(release_module, "_run") as run:
                with self.assertRaisesRegex(
                    release_module.ConfigError,
                    "wheel package version mismatch",
                ):
                    release_module.install_release(
                        wheel,
                        "0.1.2+build.2",
                        display_version="0.1.0001",
                    )

            run.assert_not_called()

    def test_build_version_falls_back_to_installed_metadata(self) -> None:
        with (
            mock.patch.object(
                release_module,
                "find_project_root",
                side_effect=release_module.ConfigError("not a checkout"),
            ),
            mock.patch.object(
                release_module,
                "version",
                return_value="0.1.1+build.1",
            ),
        ):
            self.assertEqual(release_module.build_version(), "0.1.0001")

    def test_require_clean_source_rejects_dirty_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(root)
            with (
                mock.patch.object(
                    release_module,
                    "_run",
                    return_value=mock.Mock(stdout=" M pyproject.toml\n"),
                ),
            ):
                with self.assertRaisesRegex(
                    release_module.ConfigError,
                    "clean Git checkout",
                ):
                    release_module.require_clean_source(root)

    def test_require_release_mutation_rejects_extra_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(root)
            with mock.patch.object(
                release_module,
                "_run",
                return_value=mock.Mock(
                    stdout=" M pyproject.toml\n M src/macjev/cli.py\n"
                ),
            ):
                with self.assertRaisesRegex(
                    release_module.ConfigError,
                    "unexpected files",
                ):
                    release_module._require_release_mutation(root)

    def test_effective_build_source_records_metadata_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(root)
            base = {"commit": "base-commit", "tree": "base-tree"}
            outputs = {
                ("git", "status", "--porcelain=v1", "--untracked-files=all"): " M pyproject.toml\n",
                ("git", "hash-object", "pyproject.toml"): "metadata-blob\n",
                ("git", "read-tree", "HEAD"): "",
                (
                    "git",
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    "100644,metadata-blob,pyproject.toml",
                ): "",
                ("git", "write-tree"): "build-tree\n",
            }

            def run(command, **kwargs):
                return mock.Mock(stdout=outputs[tuple(command)])

            with mock.patch.object(release_module, "_run", side_effect=run):
                source = release_module._effective_build_source(root, base)

            self.assertEqual(
                source,
                {
                    "commit": "base-commit",
                    "tree": "base-tree",
                    "build_tree": "build-tree",
                    "metadata_blob": "metadata-blob",
                },
            )

    def test_set_project_version_uses_uv_in_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(root)
            with mock.patch.object(release_module, "_run") as run:
                run.return_value.stdout = "0.1.1+build.1\n"

                value = release_module.set_project_version(
                    "0.1.1+build.1",
                    root=root,
                )

            self.assertEqual(value, "0.1.1+build.1")
            run.assert_called_once_with(
                ["uv", "version", "0.1.1+build.1", "--short", "--no-sync"],
                cwd=root.resolve(),
            )

    def test_install_skills_uses_explicit_source_and_verifies_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            target = root / "target"
            skill = source / "example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")

            with mock.patch.object(release_module, "SKILLS_TARGET", target):
                installed = release_module.install_skills(source)

            self.assertEqual(installed, [target / "example"])
            self.assertEqual(
                (target / "example" / "SKILL.md").read_text(encoding="utf-8"),
                "skill\n",
            )
            self.assertEqual(
                (target / "example" / release_module.SKILL_MARKER).read_text(
                    encoding="utf-8"
                ),
                "name=example\n",
            )

    def test_install_skills_replaces_owned_target_without_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            target = root / "target"
            skill = source / "example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("new\n", encoding="utf-8")
            installed = target / "example"
            installed.mkdir(parents=True)
            (installed / release_module.SKILL_MARKER).write_text(
                "name=example\n",
                encoding="utf-8",
            )
            (installed / "SKILL.md").write_text("old\n", encoding="utf-8")

            with mock.patch.object(release_module, "SKILLS_TARGET", target):
                release_module.install_skills(source)

            self.assertEqual(
                (installed / "SKILL.md").read_text(encoding="utf-8"),
                "new\n",
            )
            self.assertEqual(
                [path.name for path in target.iterdir()],
                ["example"],
            )

    def test_install_skills_rejects_unowned_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            target = root / "target"
            skill = source / "example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("new\n", encoding="utf-8")
            installed = target / "example"
            installed.mkdir(parents=True)
            (installed / "SKILL.md").write_text("user\n", encoding="utf-8")

            with mock.patch.object(release_module, "SKILLS_TARGET", target):
                with self.assertRaisesRegex(
                    release_module.ConfigError,
                    "unowned Skill target",
                ):
                    release_module.install_skills(source)

            self.assertEqual(
                (installed / "SKILL.md").read_text(encoding="utf-8"),
                "user\n",
            )

    def test_verify_installed_entrypoints_checks_cli_and_mcp(self) -> None:
        output = "\n".join(
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "serverInfo": {
                                "name": "macjev",
                                "version": "0.1.0001",
                            }
                        },
                    }
                ),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {
                            "tools": [{"name": "macjev_daemon_status"}],
                        },
                    }
                ),
            ]
        ) + "\n"
        with (
            mock.patch.object(release_module, "_macjev_command", return_value="/bin/macjev"),
            mock.patch.object(release_module, "_mcp_command", return_value="/bin/macjev-mcp"),
            mock.patch.object(
                release_module,
                "_run",
                return_value=mock.Mock(stdout="macjev 0.1.0001\n"),
            ),
            mock.patch.object(
                release_module.subprocess,
                "run",
                return_value=mock.Mock(returncode=0, stdout=output, stderr=""),
            ),
        ):
            acceptance = release_module.verify_installed_entrypoints("0.1.0001")

        self.assertEqual(acceptance["version"], "0.1.0001")
        self.assertEqual(acceptance["tools"], ["macjev_daemon_status"])

    def test_verify_installed_entrypoints_rejects_cli_version_prefix(self) -> None:
        with (
            mock.patch.object(release_module, "_macjev_command", return_value="/bin/macjev"),
            mock.patch.object(
                release_module,
                "_run",
                return_value=mock.Mock(stdout="macjev 0.1.00010\n"),
            ),
        ):
            with self.assertRaisesRegex(
                release_module.ConfigError,
                "installed CLI version mismatch",
            ):
                release_module.verify_installed_entrypoints("0.1.0001")

    def test_bump_version_uses_uv_in_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(root)
            with mock.patch.object(release_module, "_run") as run:
                run.return_value.stdout = "0.1.1\n"

                value = release_module.bump_version("patch", root=root)

            self.assertEqual(value, "0.1.1")
            run.assert_called_once_with(
                ["uv", "version", "--bump", "patch", "--short", "--no-sync"],
                cwd=root.resolve(),
            )

    def test_build_release_uses_versioned_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(root)
            with mock.patch.object(release_module, "_run") as run:
                def create_output(*args, **kwargs):
                    output = Path(args[0][-1])
                    (output / "macjev-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
                    (output / "macjev-0.1.0.tar.gz").write_bytes(b"sdist")
                    return mock.Mock()

                run.side_effect = create_output
                artifacts = release_module.build_release(root)

            self.assertEqual(
                [path.name for path in artifacts],
                ["macjev-0.1.0-py3-none-any.whl", "macjev-0.1.0.tar.gz"],
            )

    def test_release_manifest_records_wheel_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / "macjev-0.1.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel")

            manifest_path = release_module.release_manifest(
                wheel,
                "0.1.0001",
                package_version="0.1.1+build.1",
                source={"commit": "abc", "tree": "def"},
                acceptance={"version": "0.1.0001"},
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(manifest["version"], "0.1.0001")
            self.assertEqual(manifest["package_version"], "0.1.1+build.1")
            self.assertEqual(manifest["source"], {"commit": "abc", "tree": "def"})
            self.assertEqual(manifest["acceptance"], {"version": "0.1.0001"})
            self.assertEqual(manifest["entrypoints"], ["macjev", "macjev-mcp"])
            self.assertEqual(
                manifest["sha256"],
                "ba59926159d2aa256eb8739b8da7e2b5"
                "74b960e1202c6d624cbe981cef996c91",
            )

    def test_install_mcp_is_idempotent_and_preserves_other_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.toml"
            config.write_text(
                '[model_providers.test]\nbase_url = "http://127.0.0.1:1"\n',
                encoding="utf-8",
            )

            release_module.install_mcp(config, command="/tmp/macjev-mcp")
            release_module.install_mcp(config, command="/tmp/macjev-mcp")

            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(parsed["mcp_servers"]["macjev"]["command"], "/tmp/macjev-mcp")
            self.assertEqual(
                parsed["model_providers"]["test"]["base_url"],
                "http://127.0.0.1:1",
            )

    def test_install_mcp_preserves_other_keys_in_macjev_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.toml"
            config.write_text(
                "\n".join(
                    [
                        "[mcp_servers.macjev]",
                        'command = "/old/macjev-mcp"',
                        'args = ["--debug"]',
                        "",
                        "[mcp_servers.macjev.env]",
                        'EXTRA = "kept"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            release_module.install_mcp(config, command="/new/macjev-mcp")

            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
            table = parsed["mcp_servers"]["macjev"]
            self.assertEqual(table["command"], "/new/macjev-mcp")
            self.assertEqual(table["args"], ["--debug"])
            self.assertEqual(table["env"]["EXTRA"], "kept")


if __name__ == "__main__":
    unittest.main()
