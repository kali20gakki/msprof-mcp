from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

from msprof_mcp.tools.msprof_analyze_cmd import msprof_analyze_advisor


def test_msprof_analyze_advisor_rejects_missing_directory(tmp_path):
    missing_dir = tmp_path / "missing"

    payload = json.loads(msprof_analyze_advisor(str(missing_dir), "all"))

    assert payload["error"] == "DIRECTORY_NOT_FOUND"
    assert payload["execution_info"]["status"] == "failed"


def test_msprof_analyze_advisor_executes_expected_command(monkeypatch, tmp_path):
    profiler_dir = tmp_path / "profiler"
    profiler_dir.mkdir()

    def fake_run(cmd, capture_output, text, check, timeout):
        assert cmd == [
            "msprof-analyze",
            "advisor",
            "schedule",
            "-d",
            str(profiler_dir),
            "--stdout",
        ]
        assert capture_output is True
        assert text is True
        assert check is True
        assert timeout > 0
        return SimpleNamespace(returncode=0, stdout="analysis ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    payload = json.loads(msprof_analyze_advisor(str(profiler_dir), "schedule"))

    assert payload["execution_info"]["status"] == "success"
    assert payload["execution_info"]["mode"] == "schedule"
    assert payload["stdout"] == "analysis ok"


def test_msprof_analyze_advisor_reports_missing_command(monkeypatch, tmp_path):
    profiler_dir = tmp_path / "profiler"
    profiler_dir.mkdir()

    def fake_run(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", fake_run)

    payload = json.loads(msprof_analyze_advisor(str(profiler_dir), "all"))

    assert payload["error"] == "COMMAND_NOT_FOUND"
    assert payload["execution_info"]["status"] == "failed"
