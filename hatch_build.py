from __future__ import annotations

import json
import platform
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

        resource_path = select_resource_path()
        if not resource_path.is_file():
            raise RuntimeError(
                "Bundled trace_processor_shell is missing at "
                f"{resource_path}. Run `python scripts/download_trace_processor_shell.py --all` "
                "before building the wheel."
            )

        try:
            platform_tag = next(platform_tags())
        except StopIteration as exc:
            raise RuntimeError("Could not determine a platform tag for the wheel.") from exc

        build_data["pure_python"] = False
        build_data["tag"] = f"py3-none-{platform_tag}"
        build_data.setdefault("force_include", {})[str(resource_path)] = (
            f"msprof_mcp/resources/perfetto/{package_resource_name}"
        )


def select_resource_path() -> Path:
    entries = load_metadata_entries()
    entry = select_metadata_entry(entries)
    if entry is not None:
        return RESOURCE_DIR / resource_name_from_entry(entry)

    package_resource_name = CANONICAL_RESOURCE_NAMES.get(sys.platform)
    if package_resource_name is None:
        raise RuntimeError(
            f"Unsupported platform for bundled trace_processor_shell: {sys.platform}"
        )
    return RESOURCE_DIR / package_resource_name


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


def normalize_machine(machine: str) -> str:
    normalized = machine.lower()
    aliases = {
        "amd64": "x86_64",
        "arm64": "aarch64",
        "x64": "x86_64",
    }
    return aliases.get(normalized, normalized)
