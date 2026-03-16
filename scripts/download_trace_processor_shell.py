from __future__ import annotations

import argparse
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
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_PLATFORMS = ("darwin", "linux", "win32")
CANONICAL_PACKAGE_NAMES = {
    "darwin": "trace_processor_shell",
    "linux": "trace_processor_shell",
    "win32": "trace_processor_shell.exe",
}
METADATA_SCHEMA_VERSION = 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = load_manifest()
    entries = select_manifest_entries(
        manifest,
        include_all=args.all,
        platforms=args.platform,
    )

    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    if args.clean:
        cleanup_existing_artifacts()

    downloads: list[tuple[dict, Path]] = []
    for entry in entries:
        destination = download_entry(entry)
        downloads.append((entry, destination))

    write_metadata(downloads)

    for entry, destination in downloads:
        print(f"Downloaded {destination}")
        print(f"arch={entry['arch']}")
        print(f"sha256={entry['sha256']}")
        print(f"size={entry['file_size']}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download bundled Perfetto trace_processor_shell binaries."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Download all supported Windows/macOS/Linux artifacts.",
    )
    parser.add_argument(
        "--platform",
        action="append",
        choices=SUPPORTED_PLATFORMS,
        help="Download all artifacts for the given platform. May be repeated.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove previously downloaded trace_processor_shell artifacts before downloading.",
    )
    return parser.parse_args(argv)


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


def select_manifest_entries(
    manifest: list[dict],
    *,
    include_all: bool,
    platforms: list[str] | None,
) -> list[dict]:
    supported_entries = [
        entry
        for entry in manifest
        if isinstance(entry, dict) and entry.get("platform") in SUPPORTED_PLATFORMS
    ]

    if include_all:
        return sort_manifest_entries(supported_entries)

    if platforms:
        selected_platforms = set(platforms)
        entries = [
            entry for entry in supported_entries if entry.get("platform") in selected_platforms
        ]
        if not entries:
            raise RuntimeError(
                f"No trace_processor_shell artifacts found for platforms={sorted(selected_platforms)}."
            )
        return sort_manifest_entries(entries)

    return [select_current_manifest_entry(supported_entries)]


def sort_manifest_entries(entries: list[dict]) -> list[dict]:
    return sorted(
        entries,
        key=lambda entry: (
            str(entry.get("platform", "")),
            str(entry.get("arch", "")),
            json.dumps(entry.get("machine", []), sort_keys=True),
        ),
    )


def select_current_manifest_entry(manifest: list[dict]) -> dict:
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


def download_entry(entry: dict) -> Path:
    destination = RESOURCE_DIR / resource_name_for_entry(entry)
    if destination.is_file():
        try:
            verify_download(destination, entry)
            ensure_executable(destination)
            return destination
        except RuntimeError:
            destination.unlink()

    # Keep the temporary download on the same filesystem as the destination so
    # the final replace works on Windows GitHub runners (workspace is often on D:).
    with tempfile.TemporaryDirectory(dir=RESOURCE_DIR) as tmpdir:
        tmp_path = Path(tmpdir) / entry["file_name"]
        download_file(entry["url"], tmp_path)
        verify_download(tmp_path, entry)
        tmp_path.replace(destination)

    ensure_executable(destination)
    return destination


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


def resource_name_for_entry(entry: dict) -> str:
    file_name = entry["file_name"]
    suffix = Path(file_name).suffix
    stem = Path(file_name).stem
    return f"{stem}-{entry['arch']}{suffix}"


def ensure_executable(path: Path) -> None:
    if sys.platform == "win32":
        return

    mode = path.stat().st_mode
    path.chmod(mode | 0o755)


def cleanup_existing_artifacts() -> None:
    if not RESOURCE_DIR.exists():
        return

    for path in RESOURCE_DIR.glob("trace_processor_shell*"):
        if path.name == METADATA_PATH.name or not path.is_file():
            continue
        path.unlink()


def write_metadata(downloads: list[tuple[dict, Path]]) -> None:
    artifacts = []
    for entry, destination in downloads:
        artifacts.append(
            {
                "platform": entry["platform"],
                "machine": entry["machine"],
                "arch": entry["arch"],
                "file_name": entry["file_name"],
                "resource_name": destination.name,
                "package_file_name": CANONICAL_PACKAGE_NAMES[entry["platform"]],
                "file_size": entry["file_size"],
                "sha256": entry["sha256"],
                "source_url": entry["url"],
                "local_path": destination.relative_to(PROJECT_ROOT).as_posix(),
            }
        )

    metadata = {
        "schema_version": METADATA_SCHEMA_VERSION,
        "artifacts": artifacts,
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
