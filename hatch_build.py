from __future__ import annotations

import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from packaging.tags import platform_tags


RESOURCE_DIR = Path(__file__).parent / "src" / "msprof_mcp" / "resources" / "perfetto"
RESOURCE_NAMES = {
    "win32": "trace_processor_shell.exe",
    "linux": "trace_processor_shell",
    "darwin": "trace_processor_shell",
}


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        del version

        if self.target_name != "wheel":
            return

        resource_name = RESOURCE_NAMES.get(sys.platform)
        if resource_name is None:
            raise RuntimeError(
                f"Unsupported platform for bundled trace_processor_shell: {sys.platform}"
            )

        resource_path = RESOURCE_DIR / resource_name
        if not resource_path.is_file():
            raise RuntimeError(
                "Bundled trace_processor_shell is missing at "
                f"{resource_path}. Download it before building the wheel."
            )

        try:
            platform_tag = next(platform_tags())
        except StopIteration as exc:
            raise RuntimeError("Could not determine a platform tag for the wheel.") from exc

        build_data["pure_python"] = False
        build_data["tag"] = f"py3-none-{platform_tag}"
        build_data.setdefault("force_include", {})[str(resource_path)] = (
            f"msprof_mcp/resources/perfetto/{resource_name}"
        )
