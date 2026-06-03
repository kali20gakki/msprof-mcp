"""
Tool for creating the persistent dispatch view on profiler SQLite databases.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


class ProfilerViewTools:
    """Create the supported persistent profiler view."""

    _DISPATCH_VIEW_NAME = "dispatch_view"
    _DISPATCH_REQUIRED_TABLES = (
        "TASK",
        "CANN_API",
        "CONNECTION_IDS",
        "PYTORCH_API",
        "STRING_IDS",
    )

    def create_dispatch_view(
        self,
        db_path: str,
        replace_existing: bool = False,
    ) -> str:
        db_file, validation_error = self._validate_db_file(db_path)
        if validation_error:
            return validation_error

        try:
            with sqlite3.connect(db_file) as conn:
                missing_tables = self._missing_tables(conn, self._DISPATCH_REQUIRED_TABLES)
                if missing_tables:
                    return self._missing_tables_error(missing_tables, "dispatch view")

                cursor = conn.cursor()
                view_exists = self._view_exists(conn, self._DISPATCH_VIEW_NAME)
                if view_exists and not replace_existing:
                    row_count = self._count_rows(conn, self._DISPATCH_VIEW_NAME)
                    return self._json_response(
                        {
                            "status": "exists",
                            "artifact_type": "view",
                            "view_name": self._DISPATCH_VIEW_NAME,
                            "db_path": str(db_file.resolve()),
                            "row_count": row_count,
                            "message": "View already exists. Set replace_existing=true to recreate it.",
                        }
                    )

                if view_exists:
                    cursor.execute(f"DROP VIEW IF EXISTS {self._DISPATCH_VIEW_NAME}")

                cursor.execute(self._build_dispatch_view_sql())
                conn.commit()
                row_count = self._count_rows(conn, self._DISPATCH_VIEW_NAME)

            return self._json_response(
                {
                    "status": "success",
                    "artifact_type": "view",
                    "view_name": self._DISPATCH_VIEW_NAME,
                    "db_path": str(db_file.resolve()),
                    "replace_existing": bool(replace_existing),
                    "row_count": row_count,
                    "message": (
                        "Created a dispatch view that links TASK, CANN_API, CONNECTION_IDS, "
                        "PYTORCH_API, and STRING_IDS."
                    ),
                }
            )
        except sqlite3.Error as exc:
            logger.error("Failed to create dispatch view: %s", exc, exc_info=True)
            return self._error("SQL_EXECUTION_FAILED", str(exc))
        except Exception as exc:
            logger.error("Unexpected create_dispatch_view failure: %s", exc, exc_info=True)
            return self._error("UNEXPECTED_ERROR", str(exc))

    @classmethod
    def _build_dispatch_view_sql(cls) -> str:
        return f"""CREATE VIEW {cls._DISPATCH_VIEW_NAME} AS
SELECT
        t.globalTaskId AS global_task_id,
        t_str.value AS task_type,
        ROUND(t.startNs) AS task_start_ns,
        ROUND(t.endNs) AS task_end_ns,
        ROUND(t.endNs - t.startNs) AS task_duration_ns,

        c_str.value AS cann_api_name,
        ROUND(c.startNs) AS cann_start_ns,
        ROUND(c.endNs) AS cann_end_ns,
        ROUND(c.endNs - c.startNs) AS cann_duration_ns,

        p_str.value AS pytorch_api_name,
        ROUND(p.startNs) AS pytorch_start_ns,
        ROUND(p.endNs) AS pytorch_end_ns,
        ROUND(p.endNs - p.startNs) AS pytorch_duration_ns

    FROM TASK t
    LEFT JOIN CANN_API c ON t.connectionId = c.connectionId
    LEFT JOIN CONNECTION_IDS conn ON conn.connectionId = t.connectionId
    LEFT JOIN PYTORCH_API p ON p.connectionId = conn.id
    LEFT JOIN STRING_IDS c_str ON c.name = c_str.id
    LEFT JOIN STRING_IDS p_str ON p.name = p_str.id
    LEFT JOIN STRING_IDS t_str ON t.taskType = t_str.id"""

    @staticmethod
    def _validate_db_file(db_path: str) -> tuple[Path | None, str | None]:
        if not db_path or not str(db_path).strip():
            return None, ProfilerViewTools._error("INVALID_DB_PATH", "db_path is required.")

        db_file = Path(db_path).expanduser()
        if not db_file.exists():
            return None, ProfilerViewTools._error(
                "DB_FILE_NOT_FOUND",
                f"Database file does not exist: {db_file}",
            )
        if not db_file.is_file():
            return None, ProfilerViewTools._error(
                "INVALID_DB_PATH",
                f"Path is not a file: {db_file}",
            )
        return db_file, None

    @staticmethod
    def _missing_tables(conn: sqlite3.Connection, required_tables: tuple[str, ...]) -> list[str]:
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        return [table for table in required_tables if table not in existing]

    @classmethod
    def _missing_tables_error(cls, missing_tables: list[str], artifact_name: str) -> str:
        return cls._error(
            "MISSING_REQUIRED_TABLES",
            f"Cannot create {artifact_name}. Missing required tables: {', '.join(missing_tables)}",
        )

    @staticmethod
    def _view_exists(conn: sqlite3.Connection, view_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'view' AND lower(name) = lower(?)",
            (view_name,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _count_rows(conn: sqlite3.Connection, artifact_name: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {artifact_name}").fetchone()[0])

    @staticmethod
    def _json_response(payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _error(code: str, message: str) -> str:
        return json.dumps(
            {
                "error": code,
                "message": message,
            },
            ensure_ascii=False,
            indent=2,
        )


_profiler_view_tools = ProfilerViewTools()


def create_dispatch_view(
    db_path: str,
    replace_existing: bool = False,
) -> str:
    """
    Create a persistent dispatch SQL view on an Ascend profiler SQLite database.

    USE THIS WHEN:
    - You want to inspect the dispatch chain from PyTorch API to CANN API to NPU TASK.
    - You need a reusable view for comparing PyTorch API, CANN API, and TASK durations.

    WHAT IT DOES:
    - Creates a persistent SQLite view named `dispatch_view`.
    - Links TASK to CANN_API by TASK.connectionId.
    - Links TASK to PYTORCH_API through CONNECTION_IDS.
    - Decodes API names and task type through STRING_IDS.

    PARAMETERS:
    - db_path: Absolute path to the profiler SQLite database file.
    - replace_existing: If `true`, drop and recreate the `dispatch_view` view when it already
      exists. If `false`, the tool returns an `exists` status instead of overwriting it.

    RETURNS:
    - A JSON string.
    - On success, includes fields such as `status`, `view_name`, `db_path`, and `message`.
    - On failure, returns a JSON object with `error` and `message`.
    """
    return _profiler_view_tools.create_dispatch_view(
        db_path=db_path,
        replace_existing=replace_existing,
    )

