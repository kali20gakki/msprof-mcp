from __future__ import annotations

import ast
import hashlib
import json
import platform
import re
import sys
import tempfile
import urllib.request
from pathlib import Path


MANIFEST_URL = "https://get.perfetto.dev/trace_processor"
RESOURCE_DIR = Path(__file__).resolve().parents[1] / "src" / "msprof_mcp" / "resources" / "perfetto"
METADATA_PATH = RESOURCE_DIR / "trace_processor_shell.metadata.json"


def main() -> int:
    manifest = load_manifest()
    entry = select_manifest_entry(manifest)

    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    destination = RESOURCE_DIR / entry["file_name"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / entry["file_name"]
        download_file(entry["url"], tmp_path)
        verify_download(tmp_path, entry)
        tmp_path.replace(destination)

    write_metadata(entry, destination)

    print(f"Downloaded {destination}")
    print(f"sha256={entry['sha256']}")
    print(f"size={entry['file_size']}")
    return 0


def load_manifest() -> list[dict]:
    with urllib.request.urlopen(MANIFEST_URL) as response:
        text = response.read().decode("utf-8")

    match = re.search(
        r"TRACE_PROCESSOR_SHELL_MANIFEST = (\[.*?\])\n\n",
        text,
        flags=re.DOTALL,
    )
    if not match:
        raise RuntimeError("Could not find TRACE_PROCESSOR_SHELL_MANIFEST in Perfetto bootstrap script.")

    return ast.literal_eval(match.group(1))


def select_manifest_entry(manifest: list[dict]) -> dict:
    current_platform = sys.platform.lower()
    current_machine = normalize_machine(platform.machine())

    for entry in manifest:
        entry_platform = entry.get("platform")
        entry_machines = entry.get("machine", [])
        machines = {normalize_machine(machine) for machine in entry_machines}
        if entry_platform == current_platform and current_machine in machines:
            return entry

    raise RuntimeError(
        "No trace_processor_shell artifact found for "
        f"platform={current_platform}, machine={current_machine}."
    )


def normalize_machine(machine: str) -> str:
    normalized = machine.lower()
    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "arm64": "aarch64",
    }
    return aliases.get(normalized, normalized)


def download_file(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url) as response, destination.open("wb") as output:
        output.write(response.read())


def verify_download(path: Path, entry: dict) -> None:
    actual_size = path.stat().st_size
    if actual_size != entry["file_size"]:
        raise RuntimeError(
            f"Unexpected file size for {path.name}: expected {entry['file_size']}, got {actual_size}"
        )

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry["sha256"]:
        raise RuntimeError(
            f"Unexpected sha256 for {path.name}: expected {entry['sha256']}, got {digest}"
        )


def write_metadata(entry: dict, destination: Path) -> None:
    metadata = {
        "platform": entry["platform"],
        "machine": entry["machine"],
        "arch": entry["arch"],
        "file_name": entry["file_name"],
        "file_size": entry["file_size"],
        "sha256": entry["sha256"],
        "source_url": entry["url"],
        "local_path": str(destination.relative_to(Path(__file__).resolve().parents[1])),
    }

    METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
