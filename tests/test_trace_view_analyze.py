from __future__ import annotations

import json

from msprof_mcp.tools.trace_view.trace_view_analyze import TraceViewAnalyzeTool


class RecordingSliceFinder:
    def __init__(self, return_value: str):
        self.return_value = return_value
        self.calls = []

    def find_slices(self, *args):
        self.calls.append(args)
        return self.return_value


class RecordingSqlQueryTool:
    def __init__(self, return_value: str):
        self.return_value = return_value
        self.calls = []

    def execute_sql_query(self, *args):
        self.calls.append(args)
        return self.return_value


def make_tool(slice_finder_tool, sql_query_tool) -> TraceViewAnalyzeTool:
    tool = object.__new__(TraceViewAnalyzeTool)
    tool.slice_finder_tool = slice_finder_tool
    tool.sql_query_tool = sql_query_tool
    return tool


def test_find_slices_forwards_arguments():
    slice_finder = RecordingSliceFinder("slice-result")
    sql_tool = RecordingSqlQueryTool("{}")
    tool = make_tool(slice_finder, sql_tool)

    result = tool.find_slices(
        "/tmp/trace.json",
        "MatMul",
        process_name="python",
        match_mode="exact",
        limit=20,
        main_thread_only=True,
        time_range={"start_ms": 1, "end_ms": 2},
    )

    assert result == "slice-result"
    assert slice_finder.calls == [
        (
            "/tmp/trace.json",
            "MatMul",
            "python",
            "exact",
            20,
            True,
            {"start_ms": 1, "end_ms": 2},
        )
    ]


def test_execute_sql_query_forwards_arguments():
    slice_finder = RecordingSliceFinder("unused")
    sql_tool = RecordingSqlQueryTool("sql-result")
    tool = make_tool(slice_finder, sql_tool)

    result = tool.execute_sql_query(
        "/tmp/trace.json",
        "SELECT 1",
        process_name="python",
    )

    assert result == "sql-result"
    assert sql_tool.calls == [
        (
            "/tmp/trace.json",
            "SELECT 1",
            "python",
        )
    ]


def test_analyze_overlap_aggregates_rows_from_sql_result():
    sql_tool = RecordingSqlQueryTool(
        json.dumps(
            {
                "success": True,
                "result": {
                    "rows": [
                        {"name": "Computing", "duration_ms": 4.0},
                        {"name": "Communication", "duration_ms": 1.0},
                        {"name": "Free", "duration_ms": 1.0},
                    ]
                },
            }
        )
    )
    tool = make_tool(RecordingSliceFinder("unused"), sql_tool)

    result = json.loads(tool.analyze_overlap("/tmp/trace.json"))

    assert result["process"] == "Overlap Analysis"
    assert result["total_duration_ms"] == 6.0
    assert result["breakdown"] == [
        {"name": "Computing", "duration_ms": 4.0, "percentage": "66.67%"},
        {"name": "Communication", "duration_ms": 1.0, "percentage": "16.67%"},
        {"name": "Free", "duration_ms": 1.0, "percentage": "16.67%"},
    ]
    assert len(sql_tool.calls) == 1
    assert sql_tool.calls[0][0] == "/tmp/trace.json"


def test_analyze_overlap_passthroughs_error_envelope():
    error_payload = json.dumps(
        {
            "success": False,
            "error": {"code": "CONNECTION_FAILED", "message": "boom"},
        }
    )
    tool = make_tool(
        RecordingSliceFinder("unused"),
        RecordingSqlQueryTool(error_payload),
    )

    assert tool.analyze_overlap("/tmp/trace.json") == error_payload
