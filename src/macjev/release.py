"""Release metadata and installation helpers for MacJev."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from .errors import ConfigError

SKILLS_TARGET = Path("~/.agents/skills").expanduser()
MCP_CONFIG = Path("~/.codex/config.toml").expanduser()
MCP_NAME = "macjev"
BUILD_START = 0


def _read_pyproject(root: Path) -> dict[str, object]:
    path = root / "pyproject.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"invalid project metadata: {path}")
    return data


def find_project_root(start: str | Path | None = None) -> Path:
    """Find the MacJev source project from the current directory."""

    candidate = Path(start or Path.cwd()).expanduser().resolve()
    for root in (candidate, *candidate.parents):
        pyproject = root / "pyproject.toml"
        if not pyproject.is_file():
            continue
        data = _read_pyproject(root)
        project = data.get("project")
        if isinstance(project, dict) and project.get("name") == "macjev":
            return root
    raise ConfigError(
        "cannot find the MacJev project root; run release from a checkout "
        "containing pyproject.toml"
    )


def source_version(root: str | Path | None = None) -> str:
    """Return the version declared by the source project."""

    project_root = find_project_root(root)
    project = _read_pyproject(project_root).get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        raise ConfigError(f"missing project.version in {project_root / 'pyproject.toml'}")
    return project["version"]


def _display_version(base_version: str, build: int) -> str:
    base = base_version.partition("+")[0]
    parts = base.split(".")
    if len(parts) < 2 or not all(part.isdigit() for part in parts[:2]):
        raise ConfigError(f"cannot derive build version from project.version {base!r}")
    return f"{parts[0]}.{parts[1]}.{build:04d}"


def _build_from_version(version_value: str) -> int | None:
    _, separator, local = version_value.partition("+")
    if not separator:
        return None
    name, dot, value = local.partition(".")
    if name == "build" and dot and value.isdigit():
        return int(value)
    return None


def source_build(root: str | Path | None = None) -> int:
    """Return the monotonically increasing local build number."""

    project_root = find_project_root(root)
    tool = _read_pyproject(project_root).get("tool")
    macjev = tool.get("macjev") if isinstance(tool, dict) else None
    build = macjev.get("build") if isinstance(macjev, dict) else None
    if isinstance(build, bool) or not isinstance(build, int) or build < BUILD_START:
        raise ConfigError(
            f"missing or invalid tool.macjev.build in {project_root / 'pyproject.toml'}"
        )
    return build


def build_version(root: str | Path | None = None) -> str:
    """Return the user-visible four-digit build version."""

    try:
        project_root = find_project_root(root)
    except ConfigError:
        if root is not None:
            raise
        try:
            installed = version("macjev")
        except PackageNotFoundError as exc:
            raise ConfigError("cannot determine MacJev version from source or installation") from exc
        build = _build_from_version(installed)
        if build is None:
            raise ConfigError(
                f"installed MacJev version has no build segment: {installed}"
            )
        return _display_version(installed, build)
    return _display_version(source_version(project_root), source_build(project_root))


def project_version() -> str:
    """Return the source version, falling back to installed metadata."""

    try:
        return source_version()
    except ConfigError:
        try:
            return version("macjev")
        except PackageNotFoundError:
            return "0.0.0"


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    if env is not None:
        command_env.update(env)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=command_env,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ConfigError(f"command failed ({' '.join(command)}): {detail}")
    return completed


def require_clean_source(root: str | Path | None = None) -> dict[str, str]:
    """Require a clean Git checkout and return its source identity."""

    project_root = find_project_root(root)
    status = _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=project_root,
    ).stdout
    if status.strip():
        raise ConfigError("release requires a clean Git checkout")
    return {
        "commit": _run(["git", "rev-parse", "HEAD"], cwd=project_root).stdout.strip(),
        "tree": _run(["git", "rev-parse", "HEAD^{tree}"], cwd=project_root).stdout.strip(),
    }


def _require_release_mutation(root: Path) -> None:
    status = _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
    ).stdout.splitlines()
    if status != [" M pyproject.toml"]:
        raise ConfigError("release mutated unexpected files")


def _effective_build_source(
    root: Path,
    base_source: dict[str, str],
) -> dict[str, str]:
    """Record the exact tree built after the release metadata mutation."""

    _require_release_mutation(root)
    metadata_blob = _run(
        ["git", "hash-object", "pyproject.toml"],
        cwd=root,
    ).stdout.strip()
    with tempfile.TemporaryDirectory() as temporary:
        index = Path(temporary) / "index"
        env = {"GIT_INDEX_FILE": str(index)}
        _run(["git", "read-tree", "HEAD"], cwd=root, env=env)
        _run(
            [
                "git",
                "update-index",
                "--add",
                "--cacheinfo",
                f"100644,{metadata_blob},pyproject.toml",
            ],
            cwd=root,
            env=env,
        )
        build_tree = _run(["git", "write-tree"], cwd=root, env=env).stdout.strip()
    return {
        **base_source,
        "build_tree": build_tree,
        "metadata_blob": metadata_blob,
    }


def bump_version(
    part: str = "patch",
    *,
    root: str | Path | None = None,
    dry_run: bool = False,
) -> str:
    """Bump the project version through uv's single project metadata owner."""

    project_root = find_project_root(root)
    command = ["uv", "version", "--bump", part, "--short", "--no-sync"]
    if dry_run:
        command.append("--dry-run")
    completed = _run(command, cwd=project_root)
    return completed.stdout.strip()


def bump_build(root: str | Path | None = None, *, dry_run: bool = False) -> int:
    """Increment the local release build number."""

    project_root = find_project_root(root)
    next_build = source_build(project_root) + 1
    if dry_run:
        return next_build
    path = project_root / "pyproject.toml"
    original = path.read_text(encoding="utf-8")
    marker = "[tool.macjev]\n"
    if marker not in original:
        raise ConfigError(f"missing [tool.macjev] in {path}")
    updated = original.replace(
        f"{marker}build = {source_build(project_root)}\n",
        f"{marker}build = {next_build}\n",
        1,
    )
    if updated == original:
        raise ConfigError(f"cannot update tool.macjev.build in {path}")
    temporary = path.with_suffix(".toml.tmp")
    temporary.write_text(updated, encoding="utf-8")
    os.replace(temporary, path)
    return next_build


def set_project_version(
    version_value: str,
    *,
    root: str | Path | None = None,
) -> str:
    """Set the complete PEP 440 package version through uv."""

    project_root = find_project_root(root)
    completed = _run(
        ["uv", "version", version_value, "--short", "--no-sync"],
        cwd=project_root,
    )
    return completed.stdout.strip()


def run_project_tests(root: str | Path | None = None) -> None:
    """Run the project-owned regression command before release."""

    project_root = find_project_root(root)
    manifest_path = project_root / ".appsdk" / "project.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        modules = manifest["modules"]
        regression = modules[0]["regression"]["command"]
        program = regression["program"]
        arguments = regression["args"]
    except (OSError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read release regression command: {manifest_path}") from exc
    if not isinstance(program, str) or not isinstance(arguments, list) or not all(
        isinstance(argument, str) for argument in arguments
    ):
        raise ConfigError(f"invalid release regression command: {manifest_path}")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    _run([program, *arguments], cwd=project_root, env=env)


def build_release(
    root: str | Path | None = None,
    *,
    version_value: str | None = None,
) -> list[Path]:
    """Build the wheel and source distribution into a versioned directory."""

    project_root = find_project_root(root)
    release_version = version_value or source_version(project_root)
    target = project_root / "release" / release_version
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    _run(["uv", "build", "--out-dir", str(target)], cwd=project_root)
    return sorted(path for path in target.iterdir() if path.suffix in {".whl", ".gz"})


def install_release(
    wheel: Path,
    expected_version: str,
    *,
    display_version: str | None = None,
) -> str:
    """Force-install one wheel and verify its installed package version."""

    with zipfile.ZipFile(wheel) as archive:
        metadata_names = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ConfigError(
                f"expected one wheel metadata file in {wheel}, "
                f"found {len(metadata_names)}"
            )
        metadata = archive.read(metadata_names[0]).decode("utf-8")
    wheel_version = None
    for line in metadata.splitlines():
        if line.startswith("Version: "):
            wheel_version = line.removeprefix("Version: ").strip()
            break
    if wheel_version != expected_version:
        raise ConfigError(
            f"wheel package version mismatch: expected {expected_version}, "
            f"found {wheel_version}"
        )

    _run(["uv", "tool", "install", "--force", str(wheel.resolve())], cwd=wheel.parent)
    cli = _macjev_command()
    installed = _run([cli, "--version"], cwd=Path.home()).stdout.strip()
    expected_display = display_version or build_version()
    if installed != f"macjev {expected_display}":
        raise ConfigError(
            f"global installation version mismatch: expected macjev {expected_display}, "
            f"found {installed}"
        )
    return installed.removeprefix("macjev ").strip()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def install_skills(source_root: str | Path | None = None) -> list[Path]:
    """Install MacJev's packaged runtime Skills into the global Skill root."""

    source = (
        Path(source_root)
        if source_root is not None
        else Path(__file__).resolve().parent / "skills"
    )
    if not source.is_dir():
        raise ConfigError(f"Skill source directory is missing: {source}")
    SKILLS_TARGET.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []
    for skill_source in sorted(source.iterdir()):
        if not skill_source.is_dir() or not (skill_source / "SKILL.md").is_file():
            continue
        target = SKILLS_TARGET / skill_source.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(skill_source, target)
        if _tree_digest(skill_source) != _tree_digest(target):
            raise ConfigError(f"installed Skill digest mismatch: {target}")
        installed.append(target)
    if not installed:
        raise ConfigError(f"no installable Skills found in {source}")
    return installed


def _toml_quote(value: str) -> str:
    return json.dumps(value)


def _mcp_command() -> str:
    found = shutil.which("macjev-mcp")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "macjev-mcp"
    return str(fallback) if fallback.exists() else "macjev-mcp"


def _macjev_command() -> str:
    found = shutil.which("macjev")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "macjev"
    return str(fallback) if fallback.exists() else "macjev"


def verify_installed_entrypoints(version_value: str) -> dict[str, object]:
    """Verify the installed CLI and MCP handshake after a release."""

    cli = _macjev_command()
    cli_result = _run([cli, "--version"], cwd=Path.home())
    if cli_result.stdout.strip() != f"macjev {version_value}":
        raise ConfigError(
            f"installed CLI version mismatch: expected {version_value}, "
            f"found {cli_result.stdout.strip()}"
        )

    mcp = _mcp_command()
    requests = "\n".join(
        [
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
            '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}',
        ]
    ) + "\n"
    completed = subprocess.run(
        [mcp],
        input=requests,
        cwd=Path.home(),
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ConfigError(f"installed MCP handshake failed: {detail}")
    try:
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        server_version = responses[0]["result"]["serverInfo"]["version"]
        tools = responses[1]["result"]["tools"]
        tool_names = [tool["name"] for tool in tools]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ConfigError("installed MCP handshake returned invalid output") from exc
    if server_version != version_value:
        raise ConfigError(
            f"installed MCP version mismatch: expected {version_value}, "
            f"found {server_version}"
        )
    return {
        "cli": str(cli),
        "mcp": str(mcp),
        "version": server_version,
        "tools": tool_names,
    }


def install_mcp(
    config_path: str | Path | None = None,
    *,
    command: str | None = None,
) -> Path:
    """Register the installed stdio MCP command in the Codex config."""

    target = Path(config_path or MCP_CONFIG).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    original = target.read_text(encoding="utf-8") if target.exists() else ""
    lines = original.splitlines()
    header = f"[mcp_servers.{MCP_NAME}]"
    replacement = [header, f"command = {_toml_quote(command or _mcp_command())}"]
    if header in lines:
        index = lines.index(header)
        end = index + 1
        while end < len(lines) and not lines[end].startswith("["):
            end += 1
        lines[index:end] = replacement
    else:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(replacement)
    rendered = "\n".join(lines) + "\n"
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"refusing to write invalid Codex config {target}: {exc}") from exc
    temporary = Path(
        tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)[1]
    )
    try:
        temporary.write_text(rendered, encoding="utf-8")
        if target.exists():
            os.chmod(temporary, target.stat().st_mode & 0o777)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def release_manifest(
    wheel: Path,
    version_value: str,
    *,
    package_version: str | None = None,
    source: dict[str, str] | None = None,
    acceptance: dict[str, object] | None = None,
) -> Path:
    """Write the release manifest next to the wheel."""

    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    manifest = wheel.parent / "manifest.json"
    payload: dict[str, object] = {
        "name": "macjev",
        "version": version_value,
        "wheel": wheel.name,
        "sha256": digest,
        "entrypoints": ["macjev", "macjev-mcp"],
    }
    if package_version is not None:
        payload["package_version"] = package_version
    if source is not None:
        payload["source"] = source
    if acceptance is not None:
        payload["acceptance"] = acceptance
    manifest.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def release(
    bump: str = "patch",
    *,
    root: str | Path | None = None,
    start_daemon: bool = False,
) -> dict[str, object]:
    """Bump, verify, build, and globally install one MacJev release."""

    project_root = find_project_root(root)
    source = require_clean_source(project_root)
    base_version = bump_version(bump, root=project_root).partition("+")[0]
    release_build = bump_build(project_root)
    package_version = f"{base_version}+build.{release_build}"
    set_project_version(package_version, root=project_root)
    release_version = build_version(project_root)
    _require_release_mutation(project_root)
    run_project_tests(project_root)
    source = _effective_build_source(project_root, source)
    artifacts = build_release(project_root, version_value=release_version)
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    if len(wheels) != 1:
        raise ConfigError(
            f"expected one wheel in {project_root / 'release' / release_version}, "
            f"found {len(wheels)}"
        )
    installed_version = install_release(
        wheels[0],
        package_version,
        display_version=release_version,
    )
    skills = install_skills(project_root / "src" / "macjev" / "skills")
    mcp_config = install_mcp()
    acceptance = verify_installed_entrypoints(release_version)
    manifest = release_manifest(
        wheels[0],
        release_version,
        package_version=package_version,
        source=source,
        acceptance=acceptance,
    )
    daemon: dict[str, object] | None = None
    if start_daemon:
        from .config import load_config
        from .supervisor import RuntimeSupervisor

        supervisor = RuntimeSupervisor(load_config())
        pid, started = supervisor.start()
        daemon = {"pid": pid, "started": started, "status": supervisor.status().as_dict()}
    return {
        "version": release_version,
        "package_version": package_version,
        "installed_version": installed_version,
        "source": source,
        "acceptance": acceptance,
        "artifacts": [str(path) for path in artifacts],
        "manifest": str(manifest),
        "skills": [str(path) for path in skills],
        "mcp_config": str(mcp_config),
        "daemon": daemon,
    }
