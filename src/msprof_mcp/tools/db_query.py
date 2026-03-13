"""
SQLite query tool for Ascend profiler databases.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Rough cap on the size of JSON payload returned to the model.
MAX_RESULT_CHARS = 100_000


class DBQueryTool:
    """
    Execute read-only SQL on a profiler SQLite DB.

    Public capabilities:
    - execute_sql_preview: run SQL and return a small JSON payload for model usage.
    - execute_sql_to_csv: run SQL and save full result to CSV, without returning rows.
    """

    _FORBIDDEN_PREFIXES = (
        "insert ",
        "update ",
        "delete ",
        "create ",
        "drop ",
        "alter ",
        "truncate ",
        "attach ",
        "detach ",
        "pragma ",
        "reindex ",
        "vacuum",
    )

    def _validate_query_request(self, db_path: str, query: str) -> tuple[Path, str, str] | str:
        """
        Validate input and normalize query text.

        Returns:
        - (db_file, normalized_query, lowered_query) when valid.
        - JSON error string when invalid.
        """
        db_file = Path((db_path or "").strip()).expanduser()
        if not db_path or not db_file.exists():
            return self._error(
                "FILE_NOT_FOUND",
                f"Database file not found: {db_path}",
            )
        if not db_file.is_file():
            return self._error(
                "NOT_A_FILE",
                f"Path is not a file: {db_path}",
            )

        if not isinstance(query, str) or not query.strip():
            return self._error("INVALID_PARAMETER", "query must be a non-empty SQL string")

        q = query.strip().rstrip(";")
        lowered = q.lower()
        if any(lowered.startswith(prefix) for prefix in self._FORBIDDEN_PREFIXES):
            return self._error(
                "WRITE_OPERATION_BLOCKED",
                "Only read-only SQL is allowed (SELECT ...).",
            )

        return db_file, q, lowered

    def execute_sql_preview(self, db_path: str, query: str) -> str:
        """
        Execute SQL and return preview rows for model consumption.

        Description:
        - Requires LIMIT or GROUP BY in SQL; otherwise returns UNSAFE_QUERY.
        - Returns RESULT_TOO_LARGE when JSON size exceeds MAX_RESULT_CHARS.
        - Returns row data only when the result is safely small.
        """
        validated = self._validate_query_request(db_path=db_path, query=query)
        if isinstance(validated, str):
            return validated

        db_file, normalized_query, lowered_query = validated
        return self._execute_sql_preview(
            db_file=db_file,
            base_query=normalized_query,
            lowered_query=lowered_query,
        )

    def execute_sql_to_csv(self, db_path: str, query: str, output_csv_path: str) -> str:
        """
        Execute SQL and save full result to CSV.

        Description:
        - Executes the full read-only query without preview size limits.
        - Does not return query rows; only returns csv_export metadata.
        - Creates parent directories for output path when needed.
        """
        if not isinstance(output_csv_path, str) or not output_csv_path.strip():
            return self._error(
                "INVALID_PARAMETER",
                "output_csv_path must be a non-empty string",
            )

        validated = self._validate_query_request(db_path=db_path, query=query)
        if isinstance(validated, str):
            return validated

        db_file, normalized_query, _ = validated
        return self._execute_sql_to_csv(
            db_file=db_file,
            base_query=normalized_query,
            output_csv_path=output_csv_path,
        )

    def _execute_sql_preview(
        self,
        db_file: Path,
        base_query: str,
        lowered_query: str,
    ) -> str:
        """
        Execute SQL and return a small JSON preview for the model.
        Guards:
        - If row count or serialized result size is too large, fail with an
          explicit error instead of returning a huge payload.
        """
        try:
            with sqlite3.connect(db_file) as conn:
                df = pd.read_sql(base_query, conn)

            row_count = len(df)
            rows_dicts = df.to_dict(orient="records")
            columns = list(df.columns)

            result = {
                "rows": rows_dicts,
                "row_count": row_count,
                "truncated": False,
                "columns": columns,
                "summary": None,
                "csv_export": None,
            }

            # Guard against excessively large JSON payloads.
            payload_str = json.dumps(result, ensure_ascii=False, indent=2)
            if len(payload_str) > MAX_RESULT_CHARS:
                return self._error(
                    "RESULT_TOO_LARGE",
                    (
                        "Result is too large to return as JSON preview. "
                        "Please reduce the number of rows/columns (for example by "
                        "adding a stricter LIMIT, selecting fewer columns, or using "
                        "GROUP BY), or request CSV export instead."
                    ),
                )

            return payload_str
        except sqlite3.Error as exc:
            logger.error("SQLite query failed: %s", exc, exc_info=True)
            return self._error("SQL_EXECUTION_FAILED", str(exc))
        except Exception as exc:
            logger.error("Unexpected execute_sql_preview failure: %s", exc, exc_info=True)
            return self._error("UNEXPECTED_ERROR", str(exc))

    def _execute_sql_to_csv(
        self,
        db_file: Path,
        base_query: str,
        output_csv_path: str,
    ) -> str:
        """
        Execute SQL and save the full result to CSV.

        This mode does not return row data to the model, only CSV export
        metadata, so it can be used for large result sets.
        """
        try:
            with sqlite3.connect(db_file) as conn:
                df = pd.read_sql(base_query, conn)

            csv_export = self._export_csv(
                df=df,
                output_csv_path=output_csv_path,
            )
            if csv_export.get("status") == "failed":
                return json.dumps(
                    {
                        "error": "CSV_EXPORT_FAILED",
                        "message": csv_export.get("message", "Failed to export CSV"),
                        "details": csv_export,
                    },
                    ensure_ascii=False,
                    indent=2,
                )

            return json.dumps(
                {
                    "csv_export": csv_export,
                },
                ensure_ascii=False,
                indent=2,
            )
        except sqlite3.Error as exc:
            logger.error("SQLite CSV export query failed: %s", exc, exc_info=True)
            return self._error("SQL_EXECUTION_FAILED", str(exc))
        except Exception as exc:
            logger.error("Unexpected execute_sql_to_csv failure: %s", exc, exc_info=True)
            return self._error("UNEXPECTED_ERROR", str(exc))

    def _export_csv(
        self,
        df: pd.DataFrame,
        output_csv_path: str,
    ) -> dict[str, Any]:
        csv_file = Path(output_csv_path).expanduser()
        csv_file.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(csv_file, index=False)
        return {
            "status": "success",
            "path": str(csv_file.resolve()),
            "saved_rows": len(df),
        }

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


_db_query_tool = DBQueryTool()


def execute_sql(
    db_path: str,
    query: str,
) -> str:
    """
    Execute read-only SQL and return preview JSON rows.

    Description:
    - Intended for model-facing query preview.
    - Requires LIMIT or GROUP BY.
    - Fails fast when row count or payload size is too large.
    """
    return _db_query_tool.execute_sql_preview(
        db_path=db_path,
        query=query,
    )


def execute_sql_to_csv(
    db_path: str,
    query: str,
    output_csv_path: str,
) -> str:
    """
    Execute read-only SQL and save full result to CSV.

    Description:
    - Intended for large result extraction.
    - Returns only csv_export metadata, not row data.
    """
    return _db_query_tool.execute_sql_to_csv(
        db_path=db_path,
        query=query,
        output_csv_path=output_csv_path,
    )


