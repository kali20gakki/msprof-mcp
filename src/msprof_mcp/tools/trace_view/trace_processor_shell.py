"""Helpers for locating the bundled Perfetto trace_processor_shell."""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import stat
import sys
from importlib import resources
from pathlib import Path


logger = logging.getLogger(__name__)

TRACE_PROCESSOR_SHELL_ENV = "MSPROF_MCP_TRACE_PROCESSOR_SHELL"
RESOURCE_PACKAGE = "msprof_mcp.resources.perfetto"
METADATA_RESOURCE_NAME = "trace_processor_shell.metadata.json"
CANONICAL_RESOURCE_NAMES = {
    "darwin": "trace_processor_shell",
    "linux": "trace_processor_shell",
    "win32": "trace_processor_shell.exe",
}
GLIBC_VERSION_PATTERN = re.compile(rb"GLIBC_(\d+)\.(\d+)(?:\.(\d+))?")


class TraceProcessorShellCompatibilityError(RuntimeError):
    """Raised when a trace_processor_shell binary cannot run on this host."""


def resolve_trace_processor_shell_path() -> str | None:
    """Return a local trace_processor_shell path, preferring bundled assets."""
    override = os.getenv(TRACE_PROCESSOR_SHELL_ENV)
    if override:
        override_path = Path(override).expanduser()
        return _validate_shell_path(
            override_path,
            source=f"environment variable {TRACE_PROCESSOR_SHELL_ENV}",
        )

    metadata_entry = _select_metadata_entry(_load_metadata_entries())
    canonical_resource_name = _canonical_resource_name()
    bundled_path = _resolve_resource_path(canonical_resource_name)
    if bundled_path is not None:
        return _validate_shell_path(
            bundled_path,
            source=f"bundled resource {canonical_resource_name}",
            metadata_entry=metadata_entry,
        )

    if metadata_entry is not None:
        resource_name = _resource_name_from_entry(metadata_entry)
        bundled_path = _resolve_resource_path(resource_name)
        if bundled_path is not None:
            return _validate_shell_path(
                bundled_path,
                source=f"bundled resource {resource_name}",
                metadata_entry=metadata_entry,
            )

        logger.warning(
            "Bundled %s metadata entry resolved to missing resource %s under %s.",
            canonical_resource_name,
            resource_name,
            RESOURCE_PACKAGE,
        )

    logger.warning(
        "Bundled %s was not found under %s; falling back to Perfetto auto-download.",
        canonical_resource_name,
        RESOURCE_PACKAGE,
    )
    return None


def _canonical_resource_name() -> str:
    return CANONICAL_RESOURCE_NAMES.get(
        sys.platform,
        "trace_processor_shell.exe" if sys.platform == "win32" else "trace_processor_shell",
    )


def _resolve_resource_path(resource_name: str) -> Path | None:
    resource = resources.files(RESOURCE_PACKAGE).joinpath(resource_name)
    if not resource.is_file():
        return None

    return Path(os.fspath(resource))


def _load_metadata_entries() -> list[dict]:
    metadata_resource = resources.files(RESOURCE_PACKAGE).joinpath(METADATA_RESOURCE_NAME)
    if not metadata_resource.is_file():
        return []

    try:
        raw_metadata = json.loads(metadata_resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read %s: %s", METADATA_RESOURCE_NAME, exc)
        return []

    if isinstance(raw_metadata, dict):
        artifacts = raw_metadata.get("artifacts")
        if isinstance(artifacts, list):
            return [entry for entry in artifacts if isinstance(entry, dict)]
        return [raw_metadata]

    if isinstance(raw_metadata, list):
        return [entry for entry in raw_metadata if isinstance(entry, dict)]

    return []


def _select_metadata_entry(entries: list[dict]) -> dict | None:
    current_platform = sys.platform.lower()
    current_machine = _normalize_machine(platform.machine())

    for entry in entries:
        if entry.get("platform") != current_platform:
            continue

        machines = entry.get("machine", [])
        if isinstance(machines, str):
            machines = [machines]

        normalized_machines = {
            _normalize_machine(machine)
            for machine in machines
            if isinstance(machine, str)
        }
        if not normalized_machines or current_machine in normalized_machines:
            return entry

    return None


def _resource_name_from_entry(entry: dict) -> str:
    resource_name = entry.get("resource_name")
    if isinstance(resource_name, str) and resource_name:
        return resource_name

    local_path = entry.get("local_path")
    if isinstance(local_path, str) and local_path:
        return Path(local_path.replace("\\", "/")).name

    file_name = entry.get("file_name")
    if isinstance(file_name, str) and file_name:
        return file_name

    return _canonical_resource_name()


def _normalize_machine(machine: str) -> str:
    normalized = machine.lower()
    aliases = {
        "amd64": "x86_64",
        "arm64": "aarch64",
        "x64": "x86_64",
    }
    return aliases.get(normalized, normalized)


def _validate_shell_path(
    path: Path,
    *,
    source: str,
    metadata_entry: dict | None = None,
) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"{source} points to a missing file: {path}")

    _ensure_executable(path)
    _ensure_linux_glibc_compatibility(path, source=source, metadata_entry=metadata_entry)
    return str(path)


def _ensure_executable(path: Path) -> None:
    if os.name == "nt":
        return

    mode = path.stat().st_mode
    execute_bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    if mode & stat.S_IXUSR:
        return

    path.chmod(mode | execute_bits)


def _ensure_linux_glibc_compatibility(
    path: Path,
    *,
    source: str,
    metadata_entry: dict | None,
) -> None:
    if sys.platform != "linux":
        return

    required_version = _glibc_min_version_from_entry(metadata_entry)
    if required_version is None:
        required_version = _detect_glibc_min_version(path)
    if required_version is None:
        return

    libc_name, current_version = _current_linux_libc()
    required_display = _format_version_tuple(required_version)
    if libc_name != "glibc" or current_version is None:
        detected = libc_name or "unknown libc"
        raise TraceProcessorShellCompatibilityError(
            f"{source} requires glibc >= {required_display}, but this system reports "
            f"{detected}. Set {TRACE_PROCESSOR_SHELL_ENV} to a compatible "
            "trace_processor_shell binary, or run on a glibc-based distro that "
            f"meets glibc >= {required_display}."
        )

    if current_version < required_version:
        raise TraceProcessorShellCompatibilityError(
            f"{source} requires glibc >= {required_display}, but this system reports "
            f"glibc {_format_version_tuple(current_version)}. Set "
            f"{TRACE_PROCESSOR_SHELL_ENV} to a compatible trace_processor_shell binary, "
            f"or run on a distro with glibc >= {required_display}."
        )


def _glibc_min_version_from_entry(entry: dict | None) -> tuple[int, int, int] | None:
    if not isinstance(entry, dict):
        return None

    version = entry.get("glibc_min_version")
    if not isinstance(version, str) or not version:
        return None

    return _parse_version_tuple(version)


def _detect_glibc_min_version(path: Path) -> tuple[int, int, int] | None:
    versions = {
        tuple(int(part or 0) for part in match.groups())
        for match in GLIBC_VERSION_PATTERN.finditer(path.read_bytes())
    }
    if not versions:
        return None

    return max(versions)


def _current_linux_libc() -> tuple[str | None, tuple[int, int, int] | None]:
    try:
        value = os.confstr("CS_GNU_LIBC_VERSION")
    except (AttributeError, OSError, ValueError):
        value = None
    if isinstance(value, str) and value:
        prefix, _, version = value.partition(" ")
        if prefix == "glibc" and version:
            return "glibc", _parse_version_tuple(version)

    libc_name, libc_version = platform.libc_ver()
    if libc_name and libc_version:
        return libc_name, _parse_version_tuple(libc_version)
    return None, None


def _parse_version_tuple(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) > 3 or not parts:
        raise TraceProcessorShellCompatibilityError(
            f"Unsupported glibc version string: {version}"
        )

    try:
        numbers = [int(part) for part in parts]
    except ValueError as exc:
        raise TraceProcessorShellCompatibilityError(
            f"Unsupported glibc version string: {version}"
        ) from exc

    while len(numbers) < 3:
        numbers.append(0)
    return numbers[0], numbers[1], numbers[2]


def _format_version_tuple(version: tuple[int, int, int]) -> str:
    major, minor, patch = version
    if patch:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}"
