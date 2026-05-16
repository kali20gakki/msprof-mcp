#!/usr/bin/env python3
"""Validate the installed msprof-mcp wheel's analyze_overlap behavior.

This script is designed for post-install verification after installing a wheel:

    pip install dist/msprof_mcp-<version>-<platform>.whl
    python scripts/verify_installed_analyze_overlap.py

By default it:
1. Removes the local repository source tree from sys.path so imports come from
   the installed wheel instead of ./src.
2. Creates a synthetic trace_view.json in a temporary directory.
3. Calls TraceViewAnalyzeTool.analyze_overlap() from the installed package.
4. Verifies the returned JSON exactly matches the expected overlap breakdown.

You can also pass a real trace_view.json for an additional smoke test:

    python scripts/verify_installed_analyze_overlap.py \
      --trace-path /path/to/trace_view.json
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path


EXPECTED_BREAKDOWN = {
    "Computing": {"duration_ms": 4.0, "percentage": "66.67%"},
    "Communication": {"duration_ms": 1.0, "percentage": "16.67%"},
    "Communication(Not Overlapped)": {"duration_ms": 0.5, "percentage": "8.33%"},
    "Free": {"duration_ms": 0.5, "percentage": "8.33%"},
}
EXPECTED_TOTAL_MS = sum(item["duration_ms"] for item in EXPECTED_BREAKDOWN.values())


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the installed msprof-mcp wheel's analyze_overlap tool.",
    )
    parser.add_argument(
        "--trace-path",
        type=Path,
        help="Optional real trace_view.json path for an extra smoke test.",
    )
    parser.add_argument(
        "--allow-local-source",
        action="store_true",
        help="Allow importing msprof_mcp from this repository instead of an installed wheel.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the generated synthetic trace file for debugging.",
    )
    return parser.parse_args()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _is_same_or_child(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _strip_local_source_from_sys_path() -> None:
    repo_root = _repo_root()
    blocked_paths = {
        repo_root.resolve(),
        (repo_root / "src").resolve(),
        (repo_root / "scripts").resolve(),
    }

    cleaned = []
    cwd = Path.cwd().resolve()
    for entry in sys.path:
        if entry == "":
            if cwd in blocked_paths:
                continue
            cleaned.append(entry)
            continue

        try:
            resolved = Path(entry).resolve()
        except OSError:
            cleaned.append(entry)
            continue

        if resolved in blocked_paths:
            continue
        cleaned.append(entry)

    sys.path[:] = cleaned


def _load_installed_tool(allow_local_source: bool):
    if not allow_local_source:
        _strip_local_source_from_sys_path()

    try:
        import msprof_mcp
        from msprof_mcp.tools.trace_view.trace_processor_shell import (
            resolve_trace_processor_shell_path,
        )
        from msprof_mcp.tools.trace_view.trace_view_analyze import TraceViewAnalyzeTool
    except Exception as exc:
        raise SystemExit(
            "Failed to import msprof_mcp from the current Python environment. "
            "Install the wheel first, for example:\n"
            "  pip install dist/msprof_mcp-<version>-<platform>.whl\n"
            f"Underlying error: {exc}"
        ) from exc

    module_path = Path(msprof_mcp.__file__).resolve()
    repo_root = _repo_root()
    if not allow_local_source and _is_same_or_child(module_path, repo_root):
        raise SystemExit(
            "Imported msprof_mcp from the local repository instead of an installed wheel:\n"
            f"  {module_path}\n"
            "Use a clean virtual environment with the wheel installed, or pass "
            "--allow-local-source if you intentionally want to test the source tree."
        )

    dist_version = "unknown"
    for dist_name in ("msprof-mcp", "msprof_mcp"):
        try:
            dist_version = importlib.metadata.version(dist_name)
            break
        except importlib.metadata.PackageNotFoundError:
            continue

    return TraceViewAnalyzeTool, resolve_trace_processor_shell_path, module_path, dist_version


def _build_synthetic_trace() -> dict:
    # Chrome Trace Event format, with one target process named "Overlap Analysis"
    # and a second distractor process whose slices must not be counted.
    return {
        "traceEvents": [
            {
                "name": "process_name",
                "cat": "__metadata",
                "ph": "M",
                "pid": 100,
                "args": {"name": "Overlap Analysis"},
            },
            {
                "name": "thread_name",
                "cat": "__metadata",
                "ph": "M",
                "pid": 100,
                "tid": 200,
                "args": {"name": "MainThread"},
            },
            {
                "name": "Computing",
                "ph": "X",
                "pid": 100,
                "tid": 200,
                "ts": 0,
                "dur": 4000,
            },
            {
                "name": "Communication",
                "ph": "X",
                "pid": 100,
                "tid": 200,
                "ts": 4000,
                "dur": 1000,
            },
            {
                "name": "Communication(Not Overlapped)",
                "ph": "X",
                "pid": 100,
                "tid": 200,
                "ts": 5000,
                "dur": 500,
            },
            {
                "name": "Free",
                "ph": "X",
                "pid": 100,
                "tid": 200,
                "ts": 5500,
                "dur": 500,
            },
            {
                "name": "process_name",
                "cat": "__metadata",
                "ph": "M",
                "pid": 101,
                "args": {"name": "Distractor Process"},
            },
            {
                "name": "thread_name",
                "cat": "__metadata",
                "ph": "M",
                "pid": 101,
                "tid": 201,
                "args": {"name": "MainThread"},
            },
            {
                "name": "Computing",
                "ph": "X",
                "pid": 101,
                "tid": 201,
                "ts": 0,
                "dur": 9000,
            },
            {
                "name": "Communication",
                "ph": "X",
                "pid": 101,
                "tid": 201,
                "ts": 9000,
                "dur": 9000,
            },
        ]
    }


def _write_synthetic_trace(target_dir: Path) -> Path:
    trace_path = target_dir / "synthetic_trace_view.json"
    trace_path.write_text(
        json.dumps(_build_synthetic_trace(), indent=2),
        encoding="utf-8",
    )
    return trace_path


def _run_analyze_overlap(tool, trace_path: Path) -> dict:
    raw = tool.analyze_overlap(str(trace_path))
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            "analyze_overlap did not return valid JSON.\n"
            f"Raw output:\n{raw}"
        ) from exc

    if isinstance(parsed, dict) and "success" in parsed:
        raise AssertionError(
            "analyze_overlap returned an error envelope instead of the expected result.\n"
            f"{json.dumps(parsed, indent=2, ensure_ascii=False)}"
        )

    return parsed


def _assert_close(actual: float, expected: float, *, label: str, tol: float = 1e-6) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tol):
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def _validate_synthetic_result(result: dict) -> None:
    if result.get("process") != "Overlap Analysis":
        raise AssertionError(
            f"Unexpected process name: {result.get('process')!r}"
        )

    total_duration = float(result.get("total_duration_ms", 0.0))
    _assert_close(
        total_duration,
        EXPECTED_TOTAL_MS,
        label="total_duration_ms",
    )

    breakdown = result.get("breakdown")
    if not isinstance(breakdown, list):
        raise AssertionError("Result field 'breakdown' must be a list.")

    by_name = {}
    for item in breakdown:
        if not isinstance(item, dict):
            raise AssertionError(f"Breakdown item must be an object, got: {item!r}")
        name = item.get("name")
        if not isinstance(name, str):
            raise AssertionError(f"Breakdown item missing string 'name': {item!r}")
        by_name[name] = item

    if set(by_name) != set(EXPECTED_BREAKDOWN):
        raise AssertionError(
            "Breakdown names mismatch.\n"
            f"Expected: {sorted(EXPECTED_BREAKDOWN)}\n"
            f"Actual:   {sorted(by_name)}"
        )

    for name, expected in EXPECTED_BREAKDOWN.items():
        item = by_name[name]
        actual_duration = float(item.get("duration_ms", 0.0))
        _assert_close(
            actual_duration,
            expected["duration_ms"],
            label=f"{name}.duration_ms",
        )

        actual_percentage = item.get("percentage")
        if actual_percentage != expected["percentage"]:
            raise AssertionError(
                f"{name}.percentage: expected {expected['percentage']}, got {actual_percentage}"
            )

    percentage_sum = 0.0
    for item in breakdown:
        percentage_text = item.get("percentage", "")
        if not isinstance(percentage_text, str) or not percentage_text.endswith("%"):
            raise AssertionError(f"Invalid percentage format: {percentage_text!r}")
        percentage_sum += float(percentage_text[:-1])

    if not math.isclose(percentage_sum, 100.0, rel_tol=0.0, abs_tol=0.02):
        raise AssertionError(
            f"Breakdown percentages should sum to about 100, got {percentage_sum}"
        )


def _validate_real_trace_result(result: dict) -> None:
    if result.get("process") != "Overlap Analysis":
        raise AssertionError(
            f"Unexpected process name for real trace result: {result.get('process')!r}"
        )

    total_duration = result.get("total_duration_ms")
    if not isinstance(total_duration, (int, float)):
        raise AssertionError("Real trace result must include numeric total_duration_ms.")
    if total_duration < 0:
        raise AssertionError("Real trace total_duration_ms must be non-negative.")

    breakdown = result.get("breakdown")
    if not isinstance(breakdown, list):
        raise AssertionError("Real trace result field 'breakdown' must be a list.")

    for item in breakdown:
        if not isinstance(item, dict):
            raise AssertionError(f"Real trace breakdown item must be an object: {item!r}")
        for key in ("name", "duration_ms", "percentage"):
            if key not in item:
                raise AssertionError(f"Real trace breakdown item missing key {key!r}: {item!r}")
        if not isinstance(item["name"], str) or not item["name"]:
            raise AssertionError(f"Invalid breakdown name: {item!r}")
        if not isinstance(item["duration_ms"], (int, float)) or item["duration_ms"] < 0:
            raise AssertionError(f"Invalid breakdown duration: {item!r}")
        if not isinstance(item["percentage"], str) or not item["percentage"].endswith("%"):
            raise AssertionError(f"Invalid breakdown percentage: {item!r}")


def main() -> int:
    args = _parse_args()

    (
        TraceViewAnalyzeTool,
        resolve_trace_processor_shell_path,
        module_path,
        dist_version,
    ) = _load_installed_tool(args.allow_local_source)

    print(f"[info] Imported msprof_mcp from: {module_path}")
    print(f"[info] Installed distribution version: {dist_version}")

    shell_path = resolve_trace_processor_shell_path()
    print(f"[info] Resolved trace_processor_shell: {shell_path}")

    synthetic_dir = Path(tempfile.mkdtemp(prefix="msprof_mcp_verify_"))
    synthetic_trace_path = _write_synthetic_trace(synthetic_dir)
    print(f"[info] Generated synthetic trace: {synthetic_trace_path}")

    tool = TraceViewAnalyzeTool()
    try:
        synthetic_result = _run_analyze_overlap(tool, synthetic_trace_path)
        _validate_synthetic_result(synthetic_result)
        print("[pass] Synthetic trace verification passed.")
        print(json.dumps(synthetic_result, indent=2, ensure_ascii=False))

        if args.trace_path is not None:
            real_trace_path = args.trace_path.expanduser().resolve()
            if not real_trace_path.is_file():
                raise AssertionError(f"Real trace file not found: {real_trace_path}")

            real_result = _run_analyze_overlap(tool, real_trace_path)
            _validate_real_trace_result(real_result)
            print(f"[pass] Real trace smoke test passed: {real_trace_path}")
            print(json.dumps(real_result, indent=2, ensure_ascii=False))

    finally:
        try:
            tool.sql_query_tool.connection_manager.close_current()
        except Exception:
            pass

        if args.keep_temp:
            print(f"[info] Keeping synthetic trace directory: {synthetic_dir}")
        else:
            shutil.rmtree(synthetic_dir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
