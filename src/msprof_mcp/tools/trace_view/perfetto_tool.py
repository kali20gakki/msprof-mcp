"""SQL query tool for executing arbitrary queries on traces."""

import json
import logging
import re
from typing import Optional, Dict, Tuple, List, Any
from .connection_manager import BaseTool, ToolError
from .query_helpers import (
    validate_sql_query,
    format_query_result_row,
    approximate_statement_count,
    detect_last_statement_type,
)

logger = logging.getLogger(__name__)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(identifier: str) -> str:
    if not _IDENTIFIER_RE.match(identifier):
        raise ToolError("INVALID_IDENTIFIER", f"Invalid SQL identifier: {identifier}")
    return f'"{identifier}"'


def _sqlite_value(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, str, bytes)):
        return value
    if isinstance(value, bool):
        return int(value)
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)

class SliceInfoTool(BaseTool):
    """Tool for retrieving information about slices with a given name."""

    def get_slice_info(self, trace_path: str, slice_name: str, process_name: Optional[str] = None) -> str:
        """Filter and summarize all occurrences of a slice by exact name.

        Returns a unified JSON envelope with:
        - sliceName
        - totalCount
        - durationSummary: { minMs, avgMs, maxMs }
        - timeBounds: { earliestTsMs, latestTsMs, spanMs }
        - examples: Top N longest slices (default 50) with context
        """

        def _to_ms(value_ns: Optional[int | float]) -> Optional[float]:
            if value_ns is None:
                return None
            try:
                return float(value_ns) / 1e6
            except Exception:
                return None

        def _get_slice_info_operation(tp):
            """Internal operation to get slice info and build result payload."""
            # Basic sanitization for embedding into SQL string
            safe_name = slice_name.replace("'", "''")

            # 1) Summary and time bounds (global across processes), case-insensitive name match
            summary_query = (
                "SELECT "
                "  COUNT(*) AS total_count, "
                "  MIN(dur) AS min_dur_ns, "
                "  AVG(dur) AS avg_dur_ns, "
                "  MAX(dur) AS max_dur_ns, "
                "  MIN(ts) AS earliest_ts_ns, "
                "  MAX(ts) AS latest_ts_ns "
                f"FROM slice WHERE UPPER(name) = UPPER('{safe_name}')"
            )

            total_count = 0
            min_ms = None
            avg_ms = None
            max_ms = None
            earliest_ms = None
            latest_ms = None
            span_ms = None

            try:
                for row in tp.query(summary_query):
                    total_count = int(getattr(row, "total_count", 0) or 0)
                    min_ms = _to_ms(getattr(row, "min_dur_ns", None))
                    avg_ms = _to_ms(getattr(row, "avg_dur_ns", None))
                    max_ms = _to_ms(getattr(row, "max_dur_ns", None))
                    earliest_ms = _to_ms(getattr(row, "earliest_ts_ns", None))
                    latest_ms = _to_ms(getattr(row, "latest_ts_ns", None))
                    if earliest_ms is not None and latest_ms is not None:
                        span_ms = float(latest_ms) - float(earliest_ms)
                    break
            except Exception as e:
                logger.warning(f"Summary query failed: {e}")

            # 2) Examples: top-N longest with context
            max_examples = 50
            examples_query = (
                "WITH candidates AS (\n"
                "  SELECT s.id, s.ts, s.dur, s.depth, s.category, s.track_id\n"
                "  FROM slice s\n"
                f"  WHERE UPPER(s.name) = UPPER('{safe_name}')\n"
                ")\n"
                "SELECT\n"
                "  c.id AS slice_id,\n"
                "  CAST(c.ts / 1e6 AS INT) AS ts_ms,\n"
                "  CAST((c.ts + c.dur) / 1e6 AS INT) AS end_ts_ms,\n"
                "  CAST(c.dur / 1e6 AS REAL) AS dur_ms,\n"
                "  c.depth,\n"
                "  c.category,\n"
                "  tr.name AS track_name,\n"
                "  th.name AS thread_name,\n"
                "  th.tid,\n"
                "  th.is_main_thread,\n"
                "  p.name AS process_name,\n"
                "  p.pid\n"
                "FROM candidates c\n"
                "JOIN track tr ON c.track_id = tr.id\n"
                "LEFT JOIN thread_track ttr ON c.track_id = ttr.id\n"
                "LEFT JOIN thread th ON ttr.utid = th.utid\n"
                "LEFT JOIN process_track pt ON c.track_id = pt.id\n"
                "LEFT JOIN process p ON COALESCE(th.upid, pt.upid) = p.upid\n"
            )

            examples_query += (
                "ORDER BY c.dur DESC\n"
                f"LIMIT {max_examples};"
            )

            # 3) Similar names (wildcard contains), case-insensitive
            other_slices: List[str] = []
            other_slices_query = (
                "SELECT name, COUNT(*) AS cnt\n"
                "FROM slice\n"
                f"WHERE UPPER(name) LIKE UPPER('%{safe_name}%')\n"
                "GROUP BY name\n"
                "ORDER BY cnt DESC\n"
                "LIMIT 20;"
            )


            examples: List[Dict[str, Any]] = []
            try:
                for row in tp.query(examples_query):
                    examples.append(
                        {
                            "sliceId": getattr(row, "slice_id", None),
                            "tsMs": getattr(row, "ts_ms", None),
                            "endTsMs": getattr(row, "end_ts_ms", None),
                            "durMs": float(getattr(row, "dur_ms", 0.0) or 0.0),
                            "depth": getattr(row, "depth", None),
                            "category": getattr(row, "category", None),
                            "trackName": getattr(row, "track_name", None),
                            "thread_name": getattr(row, "thread_name", None),
                            "tid": getattr(row, "tid", None),
                            "is_main_thread": getattr(row, "is_main_thread", None),
                            "process_name": getattr(row, "process_name", None),
                            "pid": getattr(row, "pid", None),
                        }
                    )
            except Exception as e:
                logger.warning(f"Examples query failed: {e}")

            # Collect other slices withsimilar names
            try:
                for row in tp.query(other_slices_query):
                    name_val = getattr(row, "name", None)
                    if isinstance(name_val, str):
                        other_slices.append(name_val)
            except Exception:
                pass

            return {
                "sliceName": slice_name,
                "totalCount": total_count,
                "durationSummary": {
                    "minMs": min_ms,
                    "avgMs": avg_ms,
                    "maxMs": max_ms,
                },
                "timeBounds": {
                    "earliestTsMs": int(earliest_ms) if isinstance(earliest_ms, (int, float)) else None,
                    "latestTsMs": int(latest_ms) if isinstance(latest_ms, (int, float)) else None,
                    "spanMs": span_ms,
                },
                "examples": examples,
                "otherSlices": other_slices,
            }

        return self.run_formatted(trace_path, process_name, _get_slice_info_operation)

class SqlQueryTool(BaseTool):
    """Tool for executing arbitrary SQL queries on Perfetto traces."""

    def execute_sql_query(self, trace_path: str, sql_query: str, process_name: Optional[str] = None) -> str:
        """Execute a validated PerfettoSQL script and return a unified JSON envelope."""
        # Permissive validation with guardrails (size / statement count)
        if not validate_sql_query(sql_query):
            envelope = self._make_envelope(
                trace_path=trace_path,
                process_name=process_name,
                success=False,
                error=self._error(
                    "INVALID_QUERY",
                    "SQL script rejected by guardrails",
                    sql_query,
                ),
                result={"query": sql_query},
            )
            return json.dumps(envelope, indent=2)

        def _execute_sql_operation(tp):
            """Internal operation to execute SQL query and build result payload."""
            # Execute the script as-is (no automatic LIMIT)
            qr_it = tp.query(sql_query)

            # Collect results
            rows = []
            columns = None

            for row in qr_it:
                if columns is None:
                    columns = list(row.__dict__.keys())
                row_dict = format_query_result_row(row, columns)
                rows.append(row_dict)

            # Compute metadata
            try:
                stmt_count = approximate_statement_count(sql_query)
            except Exception:
                stmt_count = None
            try:
                last_stmt = detect_last_statement_type(sql_query)
            except Exception:
                last_stmt = None

            returns_rows = bool(columns)

            # Result payload only; envelope is added by run_formatted
            payload = {
                "query": sql_query,
                "columns": columns if columns else [],
                "rows": rows,
                "rowCount": len(rows),
                "scriptStatementCount": stmt_count,
                "lastStatementType": last_stmt,
                "returnsRows": returns_rows,
            }
            return payload

        # Use the unified formatter with connection management
        return self.run_formatted(trace_path, process_name, _execute_sql_operation)


class FlowDataTool(BaseTool):
    """Tool for resolving flow-linked hardware operators for source slices."""

    @staticmethod
    def _normalize_arg_key(arg_key: str) -> str:
        return arg_key[5:] if arg_key.startswith("args.") else arg_key

    @staticmethod
    def _extract_arg_value(row: Any) -> Any:
        for field_name in ("display_value", "string_value", "int_value", "real_value"):
            value = getattr(row, field_name, None)
            if value is not None:
                return value
        return None

    def _load_args_by_set_id(
            self,
            tp: Any,
            arg_set_ids: set[int],
    ) -> Dict[int, Dict[str, Any]]:
        if not arg_set_ids:
            return {}

        args_query = (
                "SELECT * FROM args WHERE arg_set_id IN ("
                + ", ".join(str(arg_set_id) for arg_set_id in sorted(arg_set_ids))
                + ") ORDER BY arg_set_id, flat_key, key"
        )

        args_by_set_id: Dict[int, Dict[str, Any]] = {}
        for row in tp.query(args_query):
            arg_set_id = getattr(row, "arg_set_id", None)
            if not isinstance(arg_set_id, int):
                continue

            arg_key = getattr(row, "flat_key", None) or getattr(row, "key", None)
            if not isinstance(arg_key, str) or not arg_key:
                continue

            arg_value = self._extract_arg_value(row)
            if arg_value is None:
                continue

            if arg_set_id not in args_by_set_id:
                args_by_set_id[arg_set_id] = {}
            args_by_set_id[arg_set_id][self._normalize_arg_key(arg_key)] = arg_value

        return args_by_set_id

    @staticmethod
    def _flow_link_select_columns() -> str:
        return """
 	                 cpu.id AS source_slice_id,
 	                 cpu.name AS source_op,
 	                 cpu.ts AS source_ts,
 	                 cpu.dur AS source_dur,
 	                 hw.name AS source_kernel_name,
 	                 hw.id AS linked_slice_id,
 	                 hw.ts AS linked_ts,
 	                 hw.dur AS linked_dur,
 	                 hw.name AS linked_name,
 	                 hw.arg_set_id AS linked_arg_set_id
 	         """

    @classmethod
    def _ascend_hardware_join_clause(cls, slice_alias: str) -> str:
        return f"""
 	             JOIN track {slice_alias}_track ON {slice_alias}.track_id = {slice_alias}_track.id
 	             LEFT JOIN process_track {slice_alias}_pt ON {slice_alias}.track_id = {slice_alias}_pt.id
 	             LEFT JOIN process {slice_alias}_proc ON {slice_alias}_pt.upid = {slice_alias}_proc.upid
 	             LEFT JOIN thread_track {slice_alias}_tt ON {slice_alias}.track_id = {slice_alias}_tt.id
 	             LEFT JOIN thread {slice_alias}_thread ON {slice_alias}_tt.utid = {slice_alias}_thread.utid
 	             LEFT JOIN process {slice_alias}_thread_proc ON {slice_alias}_thread.upid = {slice_alias}_thread_proc.upid
 	         """

    @classmethod
    def _ascend_hardware_where_clause(cls, slice_alias: str) -> str:
        return (
            f"UPPER(COALESCE({slice_alias}_proc.name, {slice_alias}_thread_proc.name, '')) "
            "= 'ASCEND HARDWARE'"
        )

    @classmethod
    def _cpu_op_link_query(cls) -> str:
        select_columns = cls._flow_link_select_columns()
        return f"""
 	             SELECT
 	                 {select_columns}
 	             FROM ranged_slices cpu
 	             JOIN flow f ON f.slice_out = cpu.id
 	             JOIN ranged_slices hw ON hw.id = f.slice_in
 	             WHERE cpu.category = 'cpu_op'
 	               AND COALESCE(hw.category, '') <> 'cpu_op'

 	             UNION

 	             SELECT
 	                 {select_columns}
 	             FROM ranged_slices cpu
 	             JOIN flow f ON f.slice_in = cpu.id
 	             JOIN ranged_slices hw ON hw.id = f.slice_out
 	             WHERE cpu.category = 'cpu_op'
 	               AND COALESCE(hw.category, '') <> 'cpu_op'
 	         """

    @classmethod
    def _npu_op_link_query(cls) -> str:
        select_columns = cls._flow_link_select_columns()
        hardware_joins = cls._ascend_hardware_join_clause("hw")
        hardware_where = cls._ascend_hardware_where_clause("hw")
        return f"""
 	             SELECT
 	                 {select_columns}
 	             FROM ranged_slices hw
 	             {hardware_joins}
 	             JOIN flow f ON f.slice_out = hw.id
 	             JOIN slice cpu ON cpu.id = f.slice_in
 	             WHERE hw.category IS NULL
 	               AND {hardware_where}
 	               AND cpu.category = 'cpu_op'

 	             UNION

 	             SELECT
 	                 {select_columns}
 	             FROM ranged_slices hw
 	             {hardware_joins}
 	             JOIN flow f ON f.slice_in = hw.id
 	             JOIN slice cpu ON cpu.id = f.slice_out
 	             WHERE hw.category IS NULL
 	               AND {hardware_where}
 	               AND cpu.category = 'cpu_op'
 	         """

    @classmethod
    def _npu_op_fallback_query(cls) -> str:
        hardware_joins = cls._ascend_hardware_join_clause("hw")
        hardware_where = cls._ascend_hardware_where_clause("hw")
        return """
 	             SELECT
 	                 hw.id AS npu_slice_id,
 	                 hw.ts AS npu_ts,
 	                 hw.dur AS npu_dur,
 	                 hw.name AS npu_name,
 	                 hw.arg_set_id AS npu_arg_set_id
 	             FROM ranged_slices hw
 	         """ + hardware_joins + f"""
 	             WHERE hw.category IS NULL
 	               AND {hardware_where}
 	               AND hw.name IS NOT NULL
 	               AND hw.name != ''
 	             ORDER BY hw.ts, hw.id
 	         """

    @classmethod
    def _build_flow_query(
            cls,
            category: str,
            start_time: int,
            end_time: int,
    ) -> str:
        link_query = (
            cls._cpu_op_link_query()
            if category == "cpu_op"
            else cls._npu_op_link_query()
        )
        return f"""
 	         WITH ranged_slices AS (
 	             SELECT
 	                 s.*
 	             FROM slice s
 	             WHERE s.ts BETWEEN {start_time} AND {end_time}
 	         ),
 	         linked_slices AS (
 	             {link_query}
 	         )
 	         SELECT
 	             *
 	         FROM linked_slices
 	         WHERE source_op IS NOT NULL AND source_op != ''
 	           AND linked_name IS NOT NULL AND linked_name != ''
 	         ORDER BY source_op, linked_name
 	         """

    @staticmethod
    def _compute_cpu_op_to_npu_op_duration(
            cpu_op_start_time: Any,
            cpu_op_duration: Any,
            npu_op_start_time: Any,
            npu_op_duration: Any,
    ) -> Any:
        try:
            cpu_op_end_time = int(cpu_op_start_time) + int(cpu_op_duration)
            npu_op_end_time = int(npu_op_start_time) + int(npu_op_duration)
        except (TypeError, ValueError):
            return None
        return npu_op_end_time - cpu_op_end_time

    @staticmethod
    def _time_sort_key(cpu_op_info: Dict[str, Any]) -> tuple[int, int]:
        cpu_op_start_time = cpu_op_info.get("cpu_op_start_time")
        try:
            return (0, int(cpu_op_start_time))
        except (TypeError, ValueError):
            pass

        npu_ops = cpu_op_info.get("npu_ops", [])
        if npu_ops and isinstance(npu_ops[0], dict):
            npu_op_start_time = npu_ops[0].get("npu_op_start_time")
            try:
                return (1, int(npu_op_start_time))
            except (TypeError, ValueError):
                pass

        return (2, 0)

    @staticmethod
    def _validate_flow_data_params(
            start_time: int | float,
            end_time: int | float,
            category: str,
    ) -> tuple[int, int, str]:
        try:
            start_time_int = int(start_time)
            end_time_int = int(end_time)
        except (TypeError, ValueError) as exc:
            raise ToolError("INVALID_PARAMETERS", "start_time and end_time must be numeric") from exc

        if end_time_int < start_time_int:
            raise ToolError("INVALID_PARAMETERS", "end_time must be greater than or equal to start_time")

        if isinstance(category, str):
            category = category.strip()
        if category not in {"cpu_op", "npu_op"}:
            raise ToolError("INVALID_PARAMETERS", "category must be 'cpu_op' or 'npu_op'")

        return start_time_int, end_time_int, category

    def _build_npu_op_fallback_query(self, start_time: int, end_time: int) -> str:
        return f"""
 	         WITH ranged_slices AS (
 	             SELECT
 	                 s.*
 	             FROM slice s
 	             WHERE s.ts BETWEEN {start_time} AND {end_time}
 	         )
 	         {self._npu_op_fallback_query()}
 	         """

    @staticmethod
    def _is_valid_linked_row(row: Any) -> bool:
        return (
                isinstance(getattr(row, "source_slice_id", None), int)
                and isinstance(getattr(row, "source_op", None), str)
                and isinstance(getattr(row, "linked_slice_id", None), int)
        )

    @staticmethod
    def _is_dequeue_linked_row(row: Any) -> bool:
        source_kernel_name = getattr(row, "source_kernel_name", None)
        linked_name = getattr(row, "linked_name", None)
        source_is_dequeue = isinstance(source_kernel_name, str) and "Dequeue" in source_kernel_name
        linked_is_dequeue = isinstance(linked_name, str) and "Dequeue" in linked_name
        return source_is_dequeue or linked_is_dequeue

    def _collect_linked_rows(self, tp: Any, query: str) -> tuple[List[Any], set[int]]:
        seen_pairs: set[tuple[int, int]] = set()
        linked_rows: List[Any] = []
        linked_arg_set_ids: set[int] = set()

        for row in tp.query(query):
            if not self._is_valid_linked_row(row) or self._is_dequeue_linked_row(row):
                continue

            dedup_key = (getattr(row, "source_slice_id"), getattr(row, "linked_slice_id"))
            if dedup_key in seen_pairs:
                continue
            seen_pairs.add(dedup_key)
            linked_rows.append(row)

            linked_arg_set_id = getattr(row, "linked_arg_set_id", None)
            if isinstance(linked_arg_set_id, int):
                linked_arg_set_ids.add(linked_arg_set_id)

        return linked_rows, linked_arg_set_ids

    def _build_linked_npu_info(
            self,
            row: Any,
            linked_args: Dict[int, Dict[str, Any]],
    ) -> Dict[str, Any]:
        linked_arg_set_id = getattr(row, "linked_arg_set_id", None)
        flattened_args = (
            linked_args.get(linked_arg_set_id, {}).copy()
            if isinstance(linked_arg_set_id, int)
            else {}
        )
        cpu_op_start_time = getattr(row, "source_ts", None)
        cpu_op_duration = getattr(row, "source_dur", None)
        npu_op_start_time = getattr(row, "linked_ts", None)
        npu_op_duration = getattr(row, "linked_dur", None)
        linked_info: Dict[str, Any] = {
            "npu_op_start_time": npu_op_start_time,
            "npu_op_duration": npu_op_duration,
            "npu_op_name": getattr(row, "linked_name", None),
            "cpu_op_to_npu_op_duration": self._compute_cpu_op_to_npu_op_duration(
                cpu_op_start_time,
                cpu_op_duration,
                npu_op_start_time,
                npu_op_duration,
            ),
        }
        linked_info.update(flattened_args)
        return linked_info

    @staticmethod
    def _get_or_create_cpu_op_instance(
            cpu_op_instances: Dict[int, Dict[str, Any]],
            row: Any,
    ) -> Dict[str, Any]:
        source_slice_id = getattr(row, "source_slice_id")
        if source_slice_id not in cpu_op_instances:
            cpu_op_instances[source_slice_id] = {
                "cpu_op_name": getattr(row, "source_op", None),
                "cpu_op_start_time": getattr(row, "source_ts", None),
                "cpu_op_duration": getattr(row, "source_dur", None),
                "npu_ops": [],
            }
        return cpu_op_instances[source_slice_id]

    def _build_cpu_op_instances(
            self,
            linked_rows: List[Any],
            linked_args: Dict[int, Dict[str, Any]],
    ) -> Dict[int, Dict[str, Any]]:
        cpu_op_instances: Dict[int, Dict[str, Any]] = {}
        for row in linked_rows:
            if not self._is_valid_linked_row(row):
                continue
            cpu_op_info = self._get_or_create_cpu_op_instance(cpu_op_instances, row)
            cpu_op_info["npu_ops"].append(self._build_linked_npu_info(row, linked_args))
        return cpu_op_instances

    @staticmethod
    def _is_valid_fallback_row(row: Any) -> bool:
        npu_slice_id = getattr(row, "npu_slice_id", None)
        npu_name = getattr(row, "npu_name", None)
        return isinstance(npu_slice_id, int) and isinstance(npu_name, str) and "Dequeue" not in npu_name

    def _collect_fallback_rows(self, tp: Any, query: str) -> tuple[List[Any], set[int]]:
        fallback_rows: List[Any] = []
        fallback_arg_set_ids: set[int] = set()
        seen_npu_ids: set[int] = set()

        for row in tp.query(query):
            npu_slice_id = getattr(row, "npu_slice_id", None)
            if not self._is_valid_fallback_row(row) or npu_slice_id in seen_npu_ids:
                continue
            seen_npu_ids.add(npu_slice_id)
            fallback_rows.append(row)

            npu_arg_set_id = getattr(row, "npu_arg_set_id", None)
            if isinstance(npu_arg_set_id, int):
                fallback_arg_set_ids.add(npu_arg_set_id)

        return fallback_rows, fallback_arg_set_ids

    @staticmethod
    def _flatten_fallback_args(row: Any, fallback_args: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
        npu_arg_set_id = getattr(row, "npu_arg_set_id", None)
        if isinstance(npu_arg_set_id, int):
            return fallback_args.get(npu_arg_set_id, {}).copy()
        return {}

    def _build_fallback_result(
            self,
            fallback_rows: List[Any],
            fallback_args: Dict[int, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        fallback_result: List[Dict[str, Any]] = []
        for row in fallback_rows:
            npu_op_info: Dict[str, Any] = {
                "npu_op_start_time": getattr(row, "npu_ts", None),
                "npu_op_duration": getattr(row, "npu_dur", None),
                "npu_op_name": getattr(row, "npu_name", None),
                "cpu_op_to_npu_op_duration": None,
            }
            npu_op_info.update(self._flatten_fallback_args(row, fallback_args))
            fallback_result.append({
                "cpu_op_name": "unknown",
                "cpu_op_start_time": "unknown",
                "cpu_op_duration": "unknown",
                "npu_ops": [npu_op_info],
            })

        fallback_result.sort(key=self._time_sort_key)
        return fallback_result

    def _execute_flow_data_query(
            self,
            tp: Any,
            query: str,
            npu_op_fallback_query: str,
            category: str,
    ) -> List[Dict[str, Any]]:
        linked_rows, linked_arg_set_ids = self._collect_linked_rows(tp, query)
        linked_args = self._load_args_by_set_id(tp, linked_arg_set_ids)
        cpu_op_instances = self._build_cpu_op_instances(linked_rows, linked_args)

        if cpu_op_instances or category == "cpu_op":
            result = list(cpu_op_instances.values())
            result.sort(key=self._time_sort_key)
            return result

        fallback_rows, fallback_arg_set_ids = self._collect_fallback_rows(tp, npu_op_fallback_query)
        fallback_args = self._load_args_by_set_id(tp, fallback_arg_set_ids)
        return self._build_fallback_result(fallback_rows, fallback_args)

    def get_flow_data(
            self,
            trace_path: str,
            start_time: int | float,
            end_time: int | float,
            category: str = "cpu_op",
    ) -> List[Dict[str, Any]]:
        """Return flow-linked operator details within the given time range."""
        start_time_int, end_time_int, category = self._validate_flow_data_params(
            start_time,
            end_time,
            category,
        )
        query = self._build_flow_query(category, start_time_int, end_time_int)
        npu_op_fallback_query = self._build_npu_op_fallback_query(start_time_int, end_time_int)

        def _operation(tp) -> List[Dict[str, Any]]:
            return self._execute_flow_data_query(tp, query, npu_op_fallback_query, category)

        return self.execute_with_connection(trace_path, _operation)

class SliceFinderTool(BaseTool):
    """Tool for discovering slices matching a pattern with optional filters."""

    def find_slices(
        self,
        trace_path: str,
        pattern: str,
        process_name: Optional[str] = None,
        match_mode: str = "contains",
        limit: int = 50,
        main_thread_only: bool = False,
        time_range: Optional[Dict[str, float | int]] = None,
    ) -> str:
        """Find slices by name using flexible matching and return aggregates + examples.

        Args:
            trace_path: Path to the trace file.
            pattern: Slice name pattern to match. Required and non-empty.
            process_name: Optional process name filter. Supports wildcards ('*' or '%').
            match_mode: One of {'contains', 'exact', 'glob'}. Defaults to 'contains'.
            limit: Max number of example slices to return (1..50). Defaults to 50.
            main_thread_only: If true, only include slices from process main threads.
            time_range: Optional dict with {'start_ms': X, 'end_ms': Y} bounds.

        Returns:
            JSON envelope string with result payload:
            {
              "matchMode": str,
              "filters": {...},
              "timeRangeMs": {...} | null,
              "aggregates": [
                {"name", "count", "minMs", "avgMs", "maxMs", "p50Ms", "p90Ms", "p99Ms", "linkable"}
              ],
              "examples": [
                {"sliceId", "tsMs", "endTsMs", "durMs", "thread_name", "tid", "is_main_thread", "process_name", "pid", "trackName", "category", "depth"}
              ],
              "notes": [str]
            }
        """

        # Validate inputs early and build operation for connection execution
        def _validate_and_normalize() -> Tuple[str, str, int, Optional[Tuple[int, int]], List[str]]:
            notes: List[str] = []

            if not isinstance(pattern, str) or not pattern.strip():
                raise ToolError("INVALID_PARAMETERS", "'pattern' must be a non-empty string")

            safe_pattern = pattern.strip().replace("'", "''")

            supported_modes = {"contains", "exact", "glob"}
            if match_mode not in supported_modes:
                raise ToolError(
                    "INVALID_PARAMETERS",
                    f"Unsupported match_mode '{match_mode}'. Supported: contains|exact|glob",
                )

            # Clamp limit to a safe range
            try:
                limit_int = int(limit)
            except Exception:
                raise ToolError("INVALID_PARAMETERS", "'limit' must be an integer")
            if limit_int < 1:
                limit_int = 1
            if limit_int > 500:
                limit_int = 500

            time_bounds_ns: Optional[Tuple[int, int]] = None
            if time_range is not None:
                if not isinstance(time_range, dict):
                    raise ToolError("INVALID_PARAMETERS", "'time_range' must be a dict with start_ms/end_ms")
                start_ms = time_range.get("start_ms")
                end_ms = time_range.get("end_ms")
                if start_ms is None or end_ms is None:
                    raise ToolError("INVALID_PARAMETERS", "time_range requires both start_ms and end_ms")
                try:
                    start_ns = int(float(start_ms) * 1e6)
                    end_ns = int(float(end_ms) * 1e6)
                except Exception:
                    raise ToolError("INVALID_PARAMETERS", "time_range values must be numeric")
                if end_ns < start_ns:
                    raise ToolError("INVALID_PARAMETERS", "time_range end_ms must be >= start_ms")
                time_bounds_ns = (start_ns, end_ns)

            if match_mode == "glob":
                notes.append("GLOB match is case-sensitive per SQLite semantics")
            
            # Special handling for wildcard pattern
            if safe_pattern == "*":
                if match_mode != "contains":
                     notes.append("Pattern '*' is treated as match-all in 'contains' mode; other modes might behave strictly.")

            return safe_pattern, match_mode, limit_int, time_bounds_ns, notes

        safe_pattern, normalized_mode, limit_int, time_bounds_ns, initial_notes = _validate_and_normalize()

        def _build_where_clauses() -> List[str]:
            clauses: List[str] = []

            # If pattern is '*', skip name filtering to match everything
            if safe_pattern != "*":
                if normalized_mode == "contains":
                    clauses.append(f"UPPER(s.name) LIKE UPPER('%{safe_pattern}%')")
                elif normalized_mode == "exact":
                    clauses.append(f"UPPER(s.name) = UPPER('{safe_pattern}')")
                elif normalized_mode == "glob":
                    clauses.append(f"s.name GLOB '{safe_pattern}'")

            if process_name:
                proc = str(process_name).strip().replace("'", "''")
                # LIKE with wildcard support: treat '*' as '%'
                if "*" in proc:
                    proc_like = proc.replace("*", "%")
                else:
                    # If no wildcard provided, do contains match for ergonomics
                    proc_like = f"%{proc}%"
                clauses.append(f"UPPER(p.name) LIKE UPPER('{proc_like}')")

            if main_thread_only:
                clauses.append("th.is_main_thread = 1")

            if time_bounds_ns is not None:
                start_ns, end_ns = time_bounds_ns
                clauses.append(f"s.ts BETWEEN {start_ns} AND {end_ns}")

            return clauses

        def _to_ms(value_ns: Optional[int | float]) -> Optional[float]:
            if value_ns is None:
                return None
            try:
                return float(value_ns) / 1e6
            except Exception:
                return None

        def _operation(tp) -> Dict[str, Any]:
            where_clauses = _build_where_clauses()
            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            # Common slice rows with joins to resolve thread/process context
            base_cte = (
                "WITH slice_rows AS (\n"
                "  SELECT s.id, s.ts, s.dur, s.depth, s.category, s.track_id, s.name AS slice_name,\n"
                "         tr.name AS track_name,\n"
                "         th.name AS thread_name, th.tid, th.is_main_thread,\n"
                "         p.name AS process_name, p.pid\n"
                "  FROM slice s\n"
                "  JOIN track tr ON s.track_id = tr.id\n"
                "  LEFT JOIN thread_track ttr ON s.track_id = ttr.id\n"
                "  LEFT JOIN thread th ON ttr.utid = th.utid\n"
                "  LEFT JOIN process_track pt ON s.track_id = pt.id\n"
                "  LEFT JOIN process p ON COALESCE(th.upid, pt.upid) = p.upid\n"
                f"  {where_sql}\n"
                ")\n"
            )

            aggregates: List[Dict[str, Any]] = []
            examples: List[Dict[str, Any]] = []
            notes: List[str] = list(initial_notes)

            # Attempt to compute percentiles if available, using the CTE to avoid alias issues
            agg_with_percentiles = (
                base_cte
                + "SELECT\n"
                + "  slice_name AS name,\n"
                + "  COUNT(*) AS total_count,\n"
                + "  MIN(dur) AS min_dur_ns,\n"
                + "  AVG(dur) AS avg_dur_ns,\n"
                + "  MAX(dur) AS max_dur_ns,\n"
                + "  quantile(dur, 0.5) AS p50_ns,\n"
                + "  quantile(dur, 0.9) AS p90_ns,\n"
                + "  quantile(dur, 0.99) AS p99_ns\n"
                + "FROM slice_rows\n"
                + "GROUP BY slice_name\n"
                + "ORDER BY total_count DESC\n"
            )

            agg_fallback = (
                base_cte
                + "SELECT\n"
                + "  slice_name AS name,\n"
                + "  COUNT(*) AS total_count,\n"
                + "  MIN(dur) AS min_dur_ns,\n"
                + "  AVG(dur) AS avg_dur_ns,\n"
                + "  MAX(dur) AS max_dur_ns\n"
                + "FROM slice_rows\n"
                + "GROUP BY slice_name\n"
                + "ORDER BY total_count DESC\n"
            )

            def _collect_aggs(row) -> Dict[str, Any]:
                name_val = getattr(row, "name", None)
                count_val = int(getattr(row, "total_count", 0) or 0)
                min_ms = _to_ms(getattr(row, "min_dur_ns", None))
                avg_ms = _to_ms(getattr(row, "avg_dur_ns", None))
                max_ms = _to_ms(getattr(row, "max_dur_ns", None))
                p50_ms = _to_ms(getattr(row, "p50_ns", None)) if hasattr(row, "p50_ns") else None
                p90_ms = _to_ms(getattr(row, "p90_ns", None)) if hasattr(row, "p90_ns") else None
                p99_ms = _to_ms(getattr(row, "p99_ns", None)) if hasattr(row, "p99_ns") else None
                return {
                    "name": name_val,
                    "count": count_val,
                    "minMs": min_ms,
                    "avgMs": avg_ms,
                    "maxMs": max_ms,
                    "p50Ms": p50_ms,
                    "p90Ms": p90_ms,
                    "p99Ms": p99_ms,
                    "linkable": True,
                }

            # Try percentiles, fall back gracefully if unavailable
            tried_percentiles = False
            try:
                tried_percentiles = True
                for row in tp.query(agg_with_percentiles):
                    aggregates.append(_collect_aggs(row))
            except Exception as e:
                # Detect missing quantile function
                msg = str(e).lower()
                if "no such function" in msg and "quantile" in msg:
                    notes.append("Percentile functions unavailable; p50/p90/p99 set to null")
                else:
                    notes.append(f"Percentiles not computed: {e}")
                # Fallback without percentiles
                try:
                    for row in tp.query(agg_fallback):
                        aggregates.append(_collect_aggs(row))
                except Exception as e2:
                    raise ToolError("QUERY_FAILED", f"Aggregate query failed: {e2}")

            # Examples: top-N by duration
            examples_query = (
                base_cte
                + "SELECT\n"
                + "  id AS slice_id,\n"
                + "  CAST(ts / 1e6 AS INT) AS ts_ms,\n"
                + "  CAST((ts + dur) / 1e6 AS INT) AS end_ts_ms,\n"
                + "  CAST(dur / 1e6 AS REAL) AS dur_ms,\n"
                + "  depth, category, track_id, track_name,\n"
                + "  thread_name, tid, is_main_thread, process_name, pid\n"
                + "FROM slice_rows\n"
                + "ORDER BY dur DESC\n"
                + f"LIMIT {limit_int};\n"
            )

            try:
                for row in tp.query(examples_query):
                    examples.append(
                        {
                            "sliceId": getattr(row, "slice_id", None),
                            "trackId": getattr(row, "track_id", None),
                            "tsMs": getattr(row, "ts_ms", None),
                            "endTsMs": getattr(row, "end_ts_ms", None),
                            "durMs": float(getattr(row, "dur_ms", 0.0) or 0.0),
                            "depth": getattr(row, "depth", None),
                            "category": getattr(row, "category", None),
                            "trackName": getattr(row, "track_name", None),
                            "thread_name": getattr(row, "thread_name", None),
                            "tid": getattr(row, "tid", None),
                            "is_main_thread": getattr(row, "is_main_thread", None),
                            "process_name": getattr(row, "process_name", None),
                            "pid": getattr(row, "pid", None),
                        }
                    )
            except Exception as e:
                raise ToolError("QUERY_FAILED", f"Example slice query failed: {e}")

            result: Dict[str, Any] = {
                "matchMode": normalized_mode,
                "filters": {
                    "processName": process_name,
                    "mainThreadOnly": main_thread_only,
                    "limit": limit_int,
                    "pattern": pattern,
                },
                "timeRangeMs": (
                    None
                    if time_bounds_ns is None
                    else {
                        "startMs": int((time_bounds_ns[0]) / 1e6),
                        "endMs": int((time_bounds_ns[1]) / 1e6),
                    }
                ),
                "aggregates": aggregates,
                "examples": examples,
                "notes": notes,
            }
            return result

        return self.run_formatted(trace_path, process_name, _operation)
