from __future__ import annotations

import json
import sqlite3

from msprof_mcp.tools.db_query import execute_sql, execute_sql_to_csv


def build_db(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany(
            "INSERT INTO items (name) VALUES (?)",
            [("alpha",), ("beta",)],
        )
        conn.commit()


def test_execute_sql_returns_preview_rows(tmp_path):
    db_path = tmp_path / "sample.db"
    build_db(db_path)

    payload = json.loads(
        execute_sql(
            str(db_path),
            "SELECT id, name FROM items ORDER BY id",
        )
    )

    assert payload["row_count"] == 2
    assert payload["columns"] == ["id", "name"]
    assert payload["rows"] == [
        {"id": 1, "name": "alpha"},
        {"id": 2, "name": "beta"},
    ]


def test_execute_sql_blocks_write_queries(tmp_path):
    db_path = tmp_path / "sample.db"
    build_db(db_path)

    payload = json.loads(execute_sql(str(db_path), "DELETE FROM items"))

    assert payload["error"] == "WRITE_OPERATION_BLOCKED"


def test_execute_sql_to_csv_exports_rows(tmp_path):
    db_path = tmp_path / "sample.db"
    build_db(db_path)
    output_csv = tmp_path / "exports" / "items.csv"

    payload = json.loads(
        execute_sql_to_csv(
            str(db_path),
            "SELECT id, name FROM items ORDER BY id",
            str(output_csv),
        )
    )

    assert payload["csv_export"]["status"] == "success"
    assert output_csv.exists()
    assert output_csv.read_text(encoding="utf-8").splitlines() == [
        "id,name",
        "1,alpha",
        "2,beta",
    ]
