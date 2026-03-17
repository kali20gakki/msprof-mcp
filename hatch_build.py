from __future__ import annotations

import json
import os
import platform
import re
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from packaging.tags import platform_tags


RESOURCE_DIR = Path(__file__).parent / "src" / "msprof_mcp" / "resources" / "perfetto"
METADATA_PATH = RESOURCE_DIR / "trace_processor_shell.metadata.json"
CANONICAL_RESOURCE_NAMES = {
    "win32": "trace_processor_shell.exe",
    "linux": "trace_processor_shell",
    "darwin": "trace_processor_shell",
}
GLIBC_VERSION_PATTERN = re.compile(rb"GLIBC_(\d+)\.(\d+)(?:\.(\d+))?")
LINUX_WHEEL_ARCH_TAGS = {
    "aarch64": "aarch64",
    "armv7l": "armv7l",
    "x86_64": "x86_64",
}


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        del version

        if self.target_name != "wheel":
            return

        package_resource_name = CANONICAL_RESOURCE_NAMES.get(sys.platform)
        if package_resource_name is None:
            raise RuntimeError(
                f"Unsupported platform for bundled trace_processor_shell: {sys.platform}"
            )

        entries = load_metadata_entries()
        selected_entry = select_metadata_entry(entries)
        resource_path = select_resource_path(selected_entry)
        if not resource_path.is_file():
            raise RuntimeError(
                "Bundled trace_processor_shell is missing at "
                f"{resource_path}. Run `python scripts/download_trace_processor_shell.py --all` "
                "before building the wheel."
            )

        platform_tag = determine_platform_tag(selected_entry, resource_path)

        build_data["pure_python"] = False
        build_data["tag"] = f"py3-none-{platform_tag}"
        build_data.setdefault("force_include", {})[str(resource_path)] = (
            f"msprof_mcp/resources/perfetto/{package_resource_name}"
        )


def select_resource_path(entry: dict | None = None) -> Path:
    if entry is not None:
        return RESOURCE_DIR / resource_name_from_entry(entry)

    package_resource_name = CANONICAL_RESOURCE_NAMES.get(sys.platform)
    if package_resource_name is None:
        raise RuntimeError(
            f"Unsupported platform for bundled trace_processor_shell: {sys.platform}"
        )
    return RESOURCE_DIR / package_resource_name


def determine_platform_tag(entry: dict | None, resource_path: Path) -> str:
    if sys.platform == "linux":
        glibc_min_version = glibc_min_version_from_entry(entry)
        if glibc_min_version is None:
            glibc_min_version = detect_glibc_min_version(resource_path)
        if glibc_min_version is not None:
            validate_linux_glibc_compatibility(glibc_min_version)
            arch_tag = linux_wheel_arch_tag()
            if arch_tag is not None:
                major, minor, _ = glibc_min_version
                return f"manylinux_{major}_{minor}_{arch_tag}"

    try:
        return next(platform_tags())
    except StopIteration as exc:
        raise RuntimeError("Could not determine a platform tag for the wheel.") from exc


def load_metadata_entries() -> list[dict]:
    if not METADATA_PATH.is_file():
        return []

    try:
        raw_metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Failed to parse trace_processor_shell metadata at {METADATA_PATH}: {exc}"
        ) from exc

    if isinstance(raw_metadata, dict):
        artifacts = raw_metadata.get("artifacts")
        if isinstance(artifacts, list):
            return [entry for entry in artifacts if isinstance(entry, dict)]
        return [raw_metadata]

    if isinstance(raw_metadata, list):
        return [entry for entry in raw_metadata if isinstance(entry, dict)]

    return []


def select_metadata_entry(entries: list[dict]) -> dict | None:
    current_platform = sys.platform.lower()
    current_machine = normalize_machine(platform.machine())

    for entry in entries:
        if entry.get("platform") != current_platform:
            continue

        machines = entry.get("machine", [])
        if isinstance(machines, str):
            machines = [machines]

        normalized_machines = {
            normalize_machine(machine)
            for machine in machines
            if isinstance(machine, str)
        }
        if not normalized_machines or current_machine in normalized_machines:
            return entry

    return None


def resource_name_from_entry(entry: dict) -> str:
    resource_name = entry.get("resource_name")
    if isinstance(resource_name, str) and resource_name:
        return resource_name

    local_path = entry.get("local_path")
    if isinstance(local_path, str) and local_path:
        return Path(local_path.replace("\\", "/")).name

    file_name = entry.get("file_name")
    if isinstance(file_name, str) and file_name:
        return file_name

    package_resource_name = CANONICAL_RESOURCE_NAMES.get(sys.platform)
    if package_resource_name is None:
        raise RuntimeError(
            f"Unsupported platform for bundled trace_processor_shell: {sys.platform}"
        )
    return package_resource_name


def glibc_min_version_from_entry(entry: dict | None) -> tuple[int, int, int] | None:
    if not isinstance(entry, dict):
        return None

    version = entry.get("glibc_min_version")
    if not isinstance(version, str) or not version:
        return None

    return parse_version_tuple(version)


def detect_glibc_min_version(path: Path) -> tuple[int, int, int] | None:
    versions = {
        tuple(int(part or 0) for part in match.groups())
        for match in GLIBC_VERSION_PATTERN.finditer(path.read_bytes())
    }
    if not versions:
        return None

    return max(versions)


def parse_version_tuple(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) > 3 or not parts:
        raise RuntimeError(f"Unsupported glibc version string: {version}")

    try:
        numbers = [int(part) for part in parts]
    except ValueError as exc:
        raise RuntimeError(f"Unsupported glibc version string: {version}") from exc

    while len(numbers) < 3:
        numbers.append(0)
    return numbers[0], numbers[1], numbers[2]


def format_version_tuple(version: tuple[int, int, int]) -> str:
    major, minor, patch = version
    if patch:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}"


def current_linux_libc() -> tuple[str | None, tuple[int, int, int] | None]:
    confstr_name = getattr(os, "confstr_names", {}).get("CS_GNU_LIBC_VERSION")
    if confstr_name is not None:
        try:
            value = os.confstr(confstr_name)
        except (OSError, ValueError):
            value = None
        if isinstance(value, str) and value:
            prefix, _, version = value.partition(" ")
            if prefix == "glibc" and version:
                return "glibc", parse_version_tuple(version)

    libc_name, libc_version = platform.libc_ver()
    if libc_name and libc_version:
        return libc_name, parse_version_tuple(libc_version)
    return None, None


def validate_linux_glibc_compatibility(required_version: tuple[int, int, int]) -> None:
    if sys.platform != "linux":
        return

    libc_name, current_version = current_linux_libc()
    required_display = format_version_tuple(required_version)
    if libc_name != "glibc" or current_version is None:
        detected = libc_name or "unknown libc"
        raise RuntimeError(
            "Bundled Linux trace_processor_shell requires glibc >= "
            f"{required_display}, but this build host reports {detected}. "
            "Build the wheel on a glibc-based Linux host that meets this requirement, "
            "or replace the bundled trace_processor_shell with a more compatible binary "
            "before building."
        )

    if current_version < required_version:
        raise RuntimeError(
            "Bundled Linux trace_processor_shell requires glibc >= "
            f"{required_display}, but this build host reports glibc "
            f"{format_version_tuple(current_version)}. Build on a newer Linux host, "
            "or replace the bundled trace_processor_shell with a more compatible binary "
            "before building."
        )


def linux_wheel_arch_tag() -> str | None:
    current_machine = normalize_machine(platform.machine())
    return LINUX_WHEEL_ARCH_TAGS.get(current_machine)


def normalize_machine(machine: str) -> str:
    normalized = machine.lower()
    aliases = {
        "amd64": "x86_64",
        "arm64": "aarch64",
        "x64": "x86_64",
    }
    return aliases.get(normalized, normalized)
