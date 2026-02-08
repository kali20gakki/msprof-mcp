"""Query helper utilities for SQL processing."""

import os
import logging

logger = logging.getLogger(__name__)


# Guardrail defaults (can be overridden via environment variables)
DEFAULT_MAX_SCRIPT_BYTES = int(os.getenv("PERFETTO_MCP_MAX_SCRIPT_BYTES", "1000000"))
DEFAULT_MAX_STATEMENTS = int(os.getenv("PERFETTO_MCP_MAX_STATEMENTS", "200"))


def add_limit_to_query(sql_query: str, limit: int = 50) -> str:
    """Add LIMIT clause to SQL query if it doesn't already have one.
    
    Args:
        sql_query: The SQL query string
        limit: Maximum number of rows to return (default: 50)
        
    Returns:
        str: Query with LIMIT clause added
    """
    query_upper = sql_query.upper()
    if 'LIMIT' not in query_upper:
        # Remove trailing semicolon if present
        if sql_query.rstrip().endswith(';'):
            sql_query = sql_query.rstrip()[:-1]
        sql_query = f"{sql_query} LIMIT {limit}"
    
    return sql_query


def _split_statements(sql_script: str) -> list[str]:
    """Best-effort split of a SQL script into statements by semicolons.

    Handles single quotes, double quotes, line comments (--) and block comments (/* */)
    to avoid splitting on semicolons inside those regions.
    """
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    length = len(sql_script)
    while i < length:
        ch = sql_script[i]
        nxt = sql_script[i + 1] if i + 1 < length else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            current.append(ch)
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                current.append(ch)
                current.append(nxt)
                i += 2
                continue
            current.append(ch)
            i += 1
            continue

        # Enter comments
        if ch == "-" and nxt == "-" and not in_single and not in_double:
            in_line_comment = True
            current.append(ch)
            current.append(nxt)
            i += 2
            continue
        if ch == "/" and nxt == "*" and not in_single and not in_double:
            in_block_comment = True
            current.append(ch)
            current.append(nxt)
            i += 2
            continue

        # Toggle quotes
        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            i += 1
            continue

        if ch == ";" and not in_single and not in_double:
            # End of statement
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    # Trailing statement without semicolon
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)

    return statements


def approximate_statement_count(sql_script: str) -> int:
    """Return a best-effort count of statements in the script."""
    if not sql_script:
        return 0
    return len(_split_statements(sql_script))


def detect_last_statement_type(sql_script: str) -> str | None:
    """Detect the first keyword of the last non-empty statement (uppercased).

    Returns None if no statements are found.
    """
    statements = _split_statements(sql_script)
    if not statements:
        return None
    last = statements[-1].lstrip()
    # Extract first token (letters, underscore, dot allowed for PERFETTO keywords)
    token = []
    for ch in last:
        if ch.isalpha() or ch == "_" or ch == ".":
            token.append(ch)
        else:
            break
    if not token:
        return None
    return "".join(token).upper()


def is_valid_perfetto_sql(sql_script: str, *, max_bytes: int = DEFAULT_MAX_SCRIPT_BYTES, max_statements: int | None = DEFAULT_MAX_STATEMENTS) -> tuple[bool, str | None]:
    """Permissive validation for PerfettoSQL scripts.

    Returns (ok, reason). "reason" is None when ok is True.
    """
    if not sql_script or not sql_script.strip():
        return False, "SQL script is empty"

    try:
        size_bytes = len(sql_script.encode("utf-8", errors="ignore"))
    except Exception:
        size_bytes = len(sql_script)

    if max_bytes is not None and size_bytes > max_bytes:
        return False, f"SQL script exceeds max size of {max_bytes} bytes"

    if max_statements is not None:
        try:
            count = approximate_statement_count(sql_script)
        except Exception:
            # If splitting fails, be safe and accept (TraceProcessor will error if needed)
            count = 1
        if count > max_statements:
            return False, f"SQL script has {count} statements which exceeds max of {max_statements}"

    return True, None


def validate_sql_query(sql_query: str) -> bool:
    """Deprecated. Kept for backward-compatibility. Uses permissive script checks now."""
    ok, _ = is_valid_perfetto_sql(sql_query)
    if not ok:
        logger.warning("SQL script rejected by guardrails")
    return ok


def format_query_result_row(row, columns: list) -> dict:
    """Format a query result row into a dictionary.
    
    Args:
        row: Query result row object
        columns: List of column names
        
    Returns:
        dict: Row data as dictionary
    """
    row_dict = {}
    for col in columns:
        value = getattr(row, col)
        # Convert any non-JSON-serializable types to strings
        if value is not None and not isinstance(value, (str, int, float, bool)):
            value = str(value)
        row_dict[col] = value
    
    return row_dict