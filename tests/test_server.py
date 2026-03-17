from __future__ import annotations

from msprof_mcp import server


class FakeMCP:
    def __init__(self, name: str):
        self.name = name
        self.registered = []
        self.run_transport = None

    def tool(self):
        def decorator(fn):
            self.registered.append(fn)
            return fn

        return decorator

    def run(self, *, transport: str):
        self.run_transport = transport


class DummyTraceViewAnalyzeTool:
    def find_slices(self, *args, **kwargs):
        return "find_slices"

    def execute_sql_query(self, *args, **kwargs):
        return "execute_sql_query"

    def analyze_overlap(self, *args, **kwargs):
        return "analyze_overlap"


class DummyKernelDetailsAnalyzer:
    def analyze_kernel_details(self, *args, **kwargs):
        return "analyze_kernel_details"

    def get_operator_details(self, *args, **kwargs):
        return "get_operator_details"


class DummyOpStatisticAnalyzer:
    def analyze_op_statistic(self, *args, **kwargs):
        return "analyze_op_statistic"

    def get_op_type_details(self, *args, **kwargs):
        return "get_op_type_details"


class DummyGenericCsvAnalyzer:
    def get_csv_info(self, *args, **kwargs):
        return "get_csv_info"

    def search_csv_by_field(self, *args, **kwargs):
        return "search_csv_by_field"


class DummyProfilerInfoAnalyzer:
    def get_profiler_config(self, *args, **kwargs):
        return "get_profiler_config"


class DummyCommunicationMatrixAnalyzer:
    def analyze_communication(self, *args, **kwargs):
        return "analyze_communication"


def fake_msprof_analyze_advisor(*args, **kwargs):
    return "msprof_analyze_advisor"


def fake_execute_sql(*args, **kwargs):
    return "execute_sql"


def fake_execute_sql_to_csv(*args, **kwargs):
    return "execute_sql_to_csv"


def test_create_server_registers_all_public_tools(monkeypatch):
    monkeypatch.setattr(server, "FastMCP", FakeMCP)
    monkeypatch.setattr(server, "TraceViewAnalyzeTool", DummyTraceViewAnalyzeTool)
    monkeypatch.setattr(server, "KernelDetailsAnalyzer", DummyKernelDetailsAnalyzer)
    monkeypatch.setattr(server, "OpStatisticAnalyzer", DummyOpStatisticAnalyzer)
    monkeypatch.setattr(server, "GenericCsvAnalyzer", DummyGenericCsvAnalyzer)
    monkeypatch.setattr(server, "ProfilerInfoAnalyzer", DummyProfilerInfoAnalyzer)
    monkeypatch.setattr(
        server,
        "CommunicationMatrixAnalyzer",
        DummyCommunicationMatrixAnalyzer,
    )
    monkeypatch.setattr(server, "msprof_analyze_advisor", fake_msprof_analyze_advisor)
    monkeypatch.setattr(server, "execute_sql", fake_execute_sql)
    monkeypatch.setattr(server, "execute_sql_to_csv", fake_execute_sql_to_csv)

    mcp = server.create_server()

    assert isinstance(mcp, FakeMCP)
    assert mcp.name == "msprof_mcp"
    assert [fn.__name__ for fn in mcp.registered] == [
        "fake_msprof_analyze_advisor",
        "find_slices",
        "execute_sql_query",
        "analyze_overlap",
        "analyze_kernel_details",
        "get_operator_details",
        "analyze_op_statistic",
        "get_op_type_details",
        "get_csv_info",
        "search_csv_by_field",
        "get_profiler_config",
        "analyze_communication",
        "fake_execute_sql",
        "fake_execute_sql_to_csv",
    ]


def test_main_runs_stdio_transport(monkeypatch):
    fake_mcp = FakeMCP("msprof_mcp")
    monkeypatch.setattr(server, "create_server", lambda: fake_mcp)

    server.main()

    assert fake_mcp.run_transport == "stdio"
