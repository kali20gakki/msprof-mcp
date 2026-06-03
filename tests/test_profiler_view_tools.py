from __future__ import annotations

import json
import sqlite3

from msprof_mcp.tools.profiler_view_tools import create_dispatch_view


def test_create_dispatch_view_links_task_cann_and_pytorch_api(tmp_path):
    db_path = tmp_path / "profiler.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE TASK (globalTaskId INTEGER, connectionId INTEGER, streamId INTEGER, startNs REAL, endNs REAL, taskType INTEGER);
        CREATE TABLE CANN_API (connectionId INTEGER, startNs REAL, endNs REAL, name INTEGER);
        CREATE TABLE CONNECTION_IDS (connectionId INTEGER, id INTEGER);
        CREATE TABLE PYTORCH_API (connectionId INTEGER, startNs REAL, endNs REAL, name INTEGER);
        CREATE TABLE STRING_IDS (id INTEGER, value TEXT);

        INSERT INTO STRING_IDS VALUES
            (1, 'aclrtLaunchKernel'),
            (2, 'torch.mm'),
            (3, 'AI_CORE');
        INSERT INTO TASK VALUES (42, 10, 7, 100, 160, 3);
        INSERT INTO CANN_API VALUES (10, 90, 170, 1);
        INSERT INTO CONNECTION_IDS VALUES (10, 20);
        INSERT INTO PYTORCH_API VALUES (20, 80, 180, 2);
        """
    )
    conn.commit()
    conn.close()

    result = json.loads(create_dispatch_view(str(db_path)))

    assert result["status"] == "success"
    assert result["view_name"] == "dispatch_view"

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT * FROM dispatch_view").fetchall()
    conn.close()

    assert rows == [
        (
            42,
            "AI_CORE",
            100.0,
            160.0,
            60.0,
            "aclrtLaunchKernel",
            90.0,
            170.0,
            80.0,
            "torch.mm",
            80.0,
            180.0,
            100.0,
        )
    ]


def test_create_dispatch_view_returns_exists_without_replacing(tmp_path):
    db_path = tmp_path / "profiler.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE TASK (globalTaskId INTEGER, connectionId INTEGER, streamId INTEGER, startNs REAL, endNs REAL, taskType INTEGER);
        CREATE TABLE CANN_API (connectionId INTEGER, startNs REAL, endNs REAL, name INTEGER);
        CREATE TABLE CONNECTION_IDS (connectionId INTEGER, id INTEGER);
        CREATE TABLE PYTORCH_API (connectionId INTEGER, startNs REAL, endNs REAL, name INTEGER);
        CREATE TABLE STRING_IDS (id INTEGER, value TEXT);

        CREATE VIEW dispatch_view AS SELECT 1 AS global_task_id, 'x' AS task_type, 1 AS task_start_ns,
            1 AS task_end_ns, 0 AS task_duration_ns, 'x' AS cann_api_name, 1 AS cann_start_ns,
            1 AS cann_end_ns, 0 AS cann_duration_ns, 'x' AS pytorch_api_name, 1 AS pytorch_start_ns,
            1 AS pytorch_end_ns, 0 AS pytorch_duration_ns;
        """
    )
    conn.commit()
    conn.close()

    result = json.loads(create_dispatch_view(str(db_path)))

    assert result["status"] == "exists"
    assert result["view_name"] == "dispatch_view"
    assert result["row_count"] == 1
