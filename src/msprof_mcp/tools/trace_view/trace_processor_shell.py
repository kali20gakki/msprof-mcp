"""Helpers for locating the bundled Perfetto trace_processor_shell."""

from __future__ import annotations

import logging
import os
import stat
import sys
from importlib import resources
from pathlib import Path


logger = logging.getLogger(__name__)

TRACE_PROCESSOR_SHELL_ENV = "MSPROF_MCP_TRACE_PROCESSOR_SHELL"
RESOURCE_PACKAGE = "msprof_mcp.resources.perfetto"


def resolve_trace_processor_shell_path() -> str | None:
    """Return a local trace_processor_shell path, preferring bundled assets."""
    override = os.getenv(TRACE_PROCESSOR_SHELL_ENV)
    if override:
        override_path = Path(override).expanduser()
        return _validate_shell_path(
            override_path,
            source=f"environment variable {TRACE_PROCESSOR_SHELL_ENV}",
        )

    resource_name = _resource_name_for_platform()
    resource = resources.files(RESOURCE_PACKAGE).joinpath(resource_name)

    if not resource.is_file():
        logger.warning(
            "Bundled %s was not found under %s; falling back to Perfetto auto-download.",
            resource_name,
            RESOURCE_PACKAGE,
        )
        return None

    bundled_path = Path(os.fspath(resource))
    _ensure_executable(bundled_path)
    return str(bundled_path)


def _resource_name_for_platform() -> str:
    return "trace_processor_shell.exe" if sys.platform == "win32" else "trace_processor_shell"


def _validate_shell_path(path: Path, *, source: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"{source} points to a missing file: {path}")

    _ensure_executable(path)
    return str(path)


def _ensure_executable(path: Path) -> None:
    if os.name == "nt":
        return

    mode = path.stat().st_mode
    execute_bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    if mode & stat.S_IXUSR:
        return

    path.chmod(mode | execute_bits)
