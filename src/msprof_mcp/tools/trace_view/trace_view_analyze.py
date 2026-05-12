import sys
import os
import csv
import json

MAX_FLOW_DATA_RESULT_COUNT = 100

FLOW_DATA_FIELD_DESCRIPTIONS = {
    "result": "Flow-linked operator records. Each item represents one CPU operator instance and its linked NPU operators.",
    "cpu_op_name": "Name of the CPU-side operator.",
    "cpu_op_start_time": "Start timestamp of the CPU-side operator in the trace's native time unit, typically nanoseconds.",
    "cpu_op_duration": "Execution duration of the CPU-side operator in the trace's native time unit, typically nanoseconds.",
    "npu_ops": "NPU-side operators linked to the CPU operator instance.",
    "npu_op_start_time": "Start timestamp of the NPU-side operator in the trace's native time unit, typically nanoseconds.",
    "npu_op_duration": "Execution duration of the NPU-side operator in the trace's native time unit, typically nanoseconds.",
    "npu_op_name": "Name of the NPU-side operator or hardware kernel.",
    "cpu_op_to_npu_op_duration": "Time difference between the CPU operator end timestamp and the NPU operator end timestamp. Null when no linked CPU operator is available.",
    "Model Id": "Model identifier reported by the profiler for the NPU-side operator.",
    "Physic Stream Id": "Physical stream identifier reported by the profiler for the NPU-side operator.",
    "Batch Id": "Identifier used to distinguish batches under the same Model Id and Physic Stream Id.",
    "dynamic_npu_fields": "Additional fields inside npu_ops come from NPU operator trace arguments and may vary across profiler versions.",
}

if __name__ == "__main__":
    # Add project root to sys.path to allow imports when running as a script
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
    from tools.trace_view.perfetto_tool import FlowDataTool, SliceInfoTool, SliceFinderTool, SqlQueryTool
    from tools.trace_view.connection_manager import ConnectionManager
else:
    from .perfetto_tool import FlowDataTool, SliceInfoTool, SliceFinderTool, SqlQueryTool
    from .connection_manager import ConnectionManager


def export_result_to_csv(result, output_path):
    """Export get_flow_data result to a CSV file."""
    rows = []
    dynamic_fields = set()

    for cpu_op_info in result:
        if not isinstance(cpu_op_info, dict):
            continue

        cpu_op_name = cpu_op_info.get("cpu_op_name")
        cpu_op_start_time = cpu_op_info.get("cpu_op_start_time")
        cpu_op_duration = cpu_op_info.get("cpu_op_duration")
        npu_ops = cpu_op_info.get("npu_ops", [])
        if not isinstance(npu_ops, list):
            continue

        for npu_op_info in npu_ops:
            if not isinstance(npu_op_info, dict):
                continue

            kernel_name = npu_op_info.get("npu_op_name", npu_op_info.get("name"))
            if isinstance(kernel_name, str) and "Dequeue" in kernel_name:
                continue

            row = {
                "cpu_op_name": cpu_op_name,
                "cpu_op_start_time": _normalize_csv_timestamp(cpu_op_start_time),
                "cpu_op_duration": cpu_op_duration,
                "npu_op_start_time": _normalize_csv_timestamp(
                    npu_op_info.get("npu_op_start_time", npu_op_info.get("ts"))
                ),
                "npu_op_duration": npu_op_info.get("npu_op_duration", npu_op_info.get("dur")),
                "npu_op_name": kernel_name,
            }
            for key, value in npu_op_info.items():
                if key in {
                    "npu_op_start_time",
                    "npu_op_duration",
                    "npu_op_name",
                    "ts",
                    "dur",
                    "name",
                }:
                    continue
                row[key] = _normalize_csv_value(key, value)
                dynamic_fields.add(key)
            rows.append(row)

    output_dir = os.path.dirname(os.path.abspath(output_path))

    fieldnames = [
                     "cpu_op_name",
                     "cpu_op_start_time",
                     "cpu_op_duration",
                     "npu_op_start_time",
                     "npu_op_duration",
                     "npu_op_name",
                 ] + sorted(dynamic_fields)
    with open(output_path, "w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return {
        "output_path": output_path,
        "row_count": len(rows),
        "column_count": len(fieldnames),
    }


def _build_flow_data_response(result):
    return {
        "field_descriptions": FLOW_DATA_FIELD_DESCRIPTIONS,
        "result": result,
    }


def _normalize_csv_timestamp(value):
    if isinstance(value, str):
        return value.lstrip("'")
    return value


def _output_path_exists(output_path):
    output_dir = os.path.dirname(os.path.abspath(output_path))
    return not output_dir or os.path.isdir(output_dir)


def _normalize_csv_value(key, value):
    if _is_id_field(key):
        return _normalize_csv_integer(value)
    return value


def _is_id_field(key):
    if not isinstance(key, str):
        return False

    normalized_key = key.strip().replace("-", "_").replace(" ", "_").lower()
    if normalized_key == "id" or normalized_key.endswith("_id"):
        return True

    return key.endswith("Id") or key.endswith("ID")


def _normalize_csv_integer(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized_value = value.strip().lstrip("'")
        if not normalized_value:
            return value
        try:
            return int(normalized_value)
        except ValueError:
            return value
    return value


class TraceViewAnalyzeTool:
    """Tool for analyzing trace data (specifically `trace_view.json`)."""

    def __init__(self):
        connection_manager = ConnectionManager()
        self.flow_data_tool = FlowDataTool(connection_manager)
        self.slice_finder_tool = SliceFinderTool(connection_manager)
        self.sql_query_tool = SqlQueryTool(connection_manager)

    def get_flow_data(
            self,
            trace_path: str,
            start_time: int | float,
            end_time: int | float,
            category: str = "cpu_op",
            result_output_path: str | None = None,
    ) -> str:
        """
        Return flow-linked operator details for slices in the given time range.

        `start_time` and `end_time` are slice timestamps in the trace's native unit, which is
        typically nanoseconds for Perfetto traces.
        `category` must be `cpu_op` or `npu_op`. Both modes return a list
        of cpu op instances with their linked `npu_ops`; `cpu_op` searches cpu ops in
        the time range, and `npu_op` searches hardware ops in the time range.
        When `npu_op` finds no linked cpu op, all npu ops in the range are
        returned with `cpu_op_name`, `cpu_op_start_time`, and `cpu_op_duration` set to
        `unknow`.
        If `result_output_path` is provided, the result is exported to CSV and a file summary is returned.
        The JSON response includes `field_descriptions` to explain the fields in `result`.
        """
        result = self.flow_data_tool.get_flow_data(trace_path, start_time, end_time, category)
        hardware_info_count = sum(
            len(cpu_op_info.get("npu_ops", []))
            for cpu_op_info in result
            if isinstance(cpu_op_info, dict)
        )

        if result_output_path:
            if not _output_path_exists(result_output_path):
                return json.dumps(
                    {
                        "error": "FILE_PATH_NOT_FOUND",
                        "message": "The file path does not exist.",
                        "field_descriptions": FLOW_DATA_FIELD_DESCRIPTIONS,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            return json.dumps(
                {
                    "field_descriptions": FLOW_DATA_FIELD_DESCRIPTIONS,
                    "csv_export": export_result_to_csv(result, result_output_path),
                },
                ensure_ascii=False,
                indent=2,
            )

        if hardware_info_count > MAX_FLOW_DATA_RESULT_COUNT:
            message = (
                f"Result contains {hardware_info_count} hardware records, exceeding the "
                f"threshold of {MAX_FLOW_DATA_RESULT_COUNT}. Please call get_flow_data again "
                "with result_output_path to export the result to a file."
            )
            return json.dumps(
                {
                    "error": "RESULT_TOO_LARGE",
                    "message": message,
                    "field_descriptions": FLOW_DATA_FIELD_DESCRIPTIONS,
                },
                ensure_ascii=False,
                indent=2,
            )

        return json.dumps(_build_flow_data_response(result), ensure_ascii=False, indent=2)

    def find_slices(
            self,
            trace_path: str,
            pattern: str,
            process_name: str | None = None,
            match_mode: str = "contains",
            limit: int = 100,
            main_thread_only: bool = False,
            time_range: dict | None = None,
    ) -> str:
        """
        Discover slices by name in a `trace_view.json` file (Chrome Trace Event format).

        SCOPE:
        - Strictly for `trace_view.json` timeline files (generated by Ascend Profiler/MSProf).
        - Used to search for specific operators (e.g., 'MatMul'), Python functions, or other trace events.

        WHY USE THIS:
        - Explore unknown slice names and hot paths fast (no manual SQL).
        - See frequency and duration stats (min/avg/max and p50/p90/p99 when available) per slice name.
        - Get linkable examples (id, ts, dur, track_id) to jump in UI or correlate with other tools.
        - Filter by process, main thread, and time range to narrow investigations.

        PARAMETERS:
        - pattern: String to match against slice names.
        - match_mode: 'contains' (default), 'exact', or 'glob'.
        - process_name: Optional filter; supports '*' wildcard.
        - main_thread_only: Limit to process main threads.
        - time_range: {'start_ms': X, 'end_ms': Y}.
        - limit: Max example slices to return (default 100).

        OUTPUT:
        - aggregates: Per-slice-name counts and duration stats (min/avg/max, p50/p90/p99 when available).
        - examples: Top slices by duration with thread/process context and track id for linking.
        - notes: Capability or fallback notices.
        """
        return self.slice_finder_tool.find_slices(
            trace_path,
            pattern,
            process_name,
            match_mode,
            limit,
            main_thread_only,
            time_range,
        )

    def execute_sql_query(self, trace_path: str, sql_query: str, process_name: str | None = None) -> str:
        """
        Execute PerfettoSQL scripts on a `trace_view.json` file.

        SCOPE:
        - Strictly for `trace_view.json` timeline files (Chrome Trace Event format).
        - Allows advanced custom analysis not covered by other methods.

        USE THIS WHEN: Other tools don't provide what you need, you need complex filtering/joins,
        or you want to correlate data across multiple tables. This is your power tool for custom
        analysis - use it when pre-built tools are too limiting.

        CAPABILITIES: Full SQL access to all trace tables including:
        - slice: All trace slices with timing
        - thread/process: Thread and process metadata
        - counter: Performance counters over time
        - sched_slice: CPU scheduling information
        - flow: Flow events connecting slices

        SECURITY: Accepts full PerfettoSQL/SQLite scripts. No automatic LIMIT is applied; large
        queries may return many rows. The script is executed verbatim by TraceProcessor.

        COMMON PATTERNS:
        - Duration analysis: "SELECT name, dur/1e6 as ms FROM slice WHERE dur > 10e6"
        - Aggregation: "SELECT name, COUNT(*), AVG(dur)/1e6 FROM slice GROUP BY name"
        - Time filtering: "SELECT * FROM slice WHERE ts BETWEEN 1e9 AND 2e9"
        - Process filtering: "SELECT * FROM thread WHERE upid IN (SELECT upid FROM process WHERE name LIKE '%python%')"

        POWER USER TIP: Use `INCLUDE PERFETTO MODULE ...` statements to load standard library
        modules. You can also use `CREATE PERFETTO TABLE`/
        `VIEW`/`FUNCTION`/`MACRO`/`INDEX` where supported by TraceProcessor.

        References:
        - PerfettoSQL Syntax: https://perfetto.dev/docs/analysis/perfetto-sql-syntax
        - Standard Library (Prelude): https://perfetto.dev/docs/analysis/stdlib-docs#package-prelude
        """
        return self.sql_query_tool.execute_sql_query(trace_path, sql_query, process_name)

    def analyze_overlap(self, trace_path: str) -> str:
        """
        Analyze the 'Overlap Analysis' process to provide a global performance overview.

        USE THIS WHEN: You are analyzing a `trace_view.json` file for the first time.
        This is the primary method to obtain global performance information, specifically
        the proportion of time spent on Computing, Communication, and Scheduling.

        CAPABILITIES: Calculates detailed statistics for the 'Overlap Analysis' process, including:
        - Computing: Time spent on actual computation.
        - Communication: Total communication time.
        - Communication(Not Overlapped): Communication time exposed (not overlapped with computation).
        - Free: Scheduling wait time or idle time.

        OUTPUT:
        Returns a JSON string with the total duration (ms) and percentage breakdown for each state.
        This helps identify if the workload is Compute-bound, Communication-bound, or has Scheduling overhead.
        """
        query = """
        SELECT
            s.name,
            CAST(SUM(s.dur) AS FLOAT) / 1e6 AS duration_ms
        FROM slice s
        JOIN track t ON s.track_id = t.id
        LEFT JOIN process_track pt ON t.id = pt.id
        LEFT JOIN process p1 ON pt.upid = p1.upid
        LEFT JOIN thread_track tt ON t.id = tt.id
        LEFT JOIN thread th ON tt.utid = th.utid
        LEFT JOIN process p2 ON th.upid = p2.upid
        WHERE
            (p1.name = 'Overlap Analysis' OR p2.name = 'Overlap Analysis')
            AND s.name IN ('Computing', 'Communication', 'Communication(Not Overlapped)', 'Free')
        GROUP BY s.name
        """

        # Execute query
        import json
        result_json = self.sql_query_tool.execute_sql_query(trace_path, query)
        result_data = json.loads(result_json)

        if not result_data.get("success", False):
            return result_json

        rows = result_data.get("result", {}).get("rows", [])

        # Calculate totals and percentages
        total_duration = sum(row.get("duration_ms", 0) for row in rows)

        analysis_result = {
            "process": "Overlap Analysis",
            "total_duration_ms": total_duration,
            "breakdown": []
        }

        for row in rows:
            name = row.get("name")
            duration = row.get("duration_ms", 0)
            percentage = (duration / total_duration * 100) if total_duration > 0 else 0
            analysis_result["breakdown"].append({
                "name": name,
                "duration_ms": duration,
                "percentage": f"{percentage:.2f}%"
            })

        return json.dumps(analysis_result, indent=2)


if __name__ == "__main__":
    tool = TraceViewAnalyzeTool()
    trace_path = "/Users/weizhang/Downloads/kv_cache_type_page_seqlen_1024_bs_1_profile_count_0/g340-cd51-4900-7a3f-dc8e-d804-1072_348921_20251105072538961_ascend_pt/ASCEND_PROFILER_OUTPUT/trace_view.json"
    trace_path = r"C:\Project\ProfilingData\profile_count_0\kv_cache_type_page_seqlen_1024_bs_1_profile_count_0\g340-cd51-4900-7a3f-dc8e-d804-1072_348890_20251105072538951_ascend_pt\ASCEND_PROFILER_OUTPUT\trace_view.json"
    print("--- Overlap Analysis ---")
    res = tool.analyze_overlap(trace_path)
    print(res)
    print("--- Get Flow Data ---")
    result = tool.get_flow_data(
        trace_path=trace_path,
        start_time=1776308640772845320,
        end_time=1776318640772845320,
        category="npu_op",
        result_output_path=r"D:\tmp\flow_data.csv"
    )
    print(result)
