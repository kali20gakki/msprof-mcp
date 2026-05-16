from __future__ import annotations

import logging

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


class FakeLogger:
    def __init__(self):
        self.level = logging.NOTSET
        self.handlers = []
        self.propagate = True

    def setLevel(self, level: int):
        self.level = level

    def addHandler(self, handler):
        self.handlers.append(handler)


class FakeHandler:
    def __init__(self):
        self.formatter = None
        self._msprof_mcp_handler = False

    def setFormatter(self, formatter):
        self.formatter = formatter


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


def test_configure_logging_defaults_to_warning_and_quiets_mcp_logger(monkeypatch):
    fake_loggers: dict[str, FakeLogger] = {}
    original_get_logger = server.logging.getLogger

    def fake_get_logger(name: str | None = None):
        if name is None:
            return original_get_logger()

        logger = fake_loggers.get(name)
        if logger is None:
            logger = FakeLogger()
            fake_loggers[name] = logger
        return logger

    monkeypatch.delenv(server.LOG_LEVEL_ENV_VAR, raising=False)
    monkeypatch.setattr(server.logging, "StreamHandler", FakeHandler)
    monkeypatch.setattr(server.logging, "getLogger", fake_get_logger)

    configured_level = server.configure_logging()
    package_logger = fake_loggers[server.PACKAGE_LOGGER_NAME]

    assert configured_level == logging.WARNING
    assert package_logger.level == logging.WARNING
    assert package_logger.propagate is False
    assert len(package_logger.handlers) == 1
    assert package_logger.handlers[0].formatter._fmt == server.LOG_FORMAT
    assert fake_loggers["mcp.server.lowlevel.server"].level == logging.WARNING


def test_configure_logging_honors_env_level_but_keeps_mcp_logger_quiet(monkeypatch):
    fake_loggers: dict[str, FakeLogger] = {}
    original_get_logger = server.logging.getLogger

    def fake_get_logger(name: str | None = None):
        if name is None:
            return original_get_logger()

        logger = fake_loggers.get(name)
        if logger is None:
            logger = FakeLogger()
            fake_loggers[name] = logger
        return logger

    monkeypatch.setenv(server.LOG_LEVEL_ENV_VAR, "DEBUG")
    monkeypatch.setattr(server.logging, "StreamHandler", FakeHandler)
    monkeypatch.setattr(server.logging, "getLogger", fake_get_logger)

    configured_level = server.configure_logging()
    package_logger = fake_loggers[server.PACKAGE_LOGGER_NAME]

    assert configured_level == logging.DEBUG
    assert package_logger.level == logging.DEBUG
    assert len(package_logger.handlers) == 1
    assert fake_loggers["mcp.server.lowlevel.server"].level == logging.WARNING


def test_configure_logging_is_idempotent_for_package_handler(monkeypatch):
    fake_loggers: dict[str, FakeLogger] = {}
    original_get_logger = server.logging.getLogger

    def fake_get_logger(name: str | None = None):
        if name is None:
            return original_get_logger()

        logger = fake_loggers.get(name)
        if logger is None:
            logger = FakeLogger()
            fake_loggers[name] = logger
        return logger

    monkeypatch.delenv(server.LOG_LEVEL_ENV_VAR, raising=False)
    monkeypatch.setattr(server.logging, "StreamHandler", FakeHandler)
    monkeypatch.setattr(server.logging, "getLogger", fake_get_logger)

    server.configure_logging()
    server.configure_logging()

    assert len(fake_loggers[server.PACKAGE_LOGGER_NAME].handlers) == 1


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
    configured = []

    monkeypatch.setattr(server, "create_server", lambda: fake_mcp)
    monkeypatch.setattr(server, "configure_logging", lambda: configured.append(True))

    server.main()

    assert configured == [True]
    assert fake_mcp.run_transport == "stdio"
