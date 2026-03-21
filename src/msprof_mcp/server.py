
"""
FastMCP server entry point.
"""

import logging
import os
from mcp.server.fastmcp import FastMCP
from .tools.msprof_analyze_cmd import msprof_analyze_advisor
from .tools.trace_view.trace_view_analyze import TraceViewAnalyzeTool
from .tools.csv_analyze import KernelDetailsAnalyzer, OpStatisticAnalyzer, GenericCsvAnalyzer
from .tools.json_analyze import ProfilerInfoAnalyzer, CommunicationMatrixAnalyzer
from .tools.db_query import execute_sql, execute_sql_to_csv
# Import other tools here as needed in the future

logger = logging.getLogger(__name__)
LOG_LEVEL_ENV_VAR = "MSPROF_MCP_LOG_LEVEL"
PACKAGE_LOGGER_NAME = "msprof_mcp"
DEFAULT_LOG_LEVEL = logging.WARNING
QUIET_LOGGER_NAMES = ("mcp.server.lowlevel.server",)
LOG_FORMAT = "%(levelname)s:%(name)s:%(message)s"


def _resolve_log_level(level_name: str | None) -> int:
    if not level_name:
        return DEFAULT_LOG_LEVEL

    candidate = getattr(logging, level_name.upper(), None)
    return candidate if isinstance(candidate, int) else DEFAULT_LOG_LEVEL


def configure_logging() -> int:
    """Configure package logging for stdio usage without emitting noisy INFO request logs."""
    level = _resolve_log_level(os.getenv(LOG_LEVEL_ENV_VAR))
    package_logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    package_logger.setLevel(level)
    package_logger.propagate = False

    if not any(getattr(handler, "_msprof_mcp_handler", False) for handler in package_logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        handler._msprof_mcp_handler = True
        package_logger.addHandler(handler)

    # Keep noisy MCP request lifecycle logs out of stdio clients unless code is changed explicitly.
    for logger_name in QUIET_LOGGER_NAMES:
        logging.getLogger(logger_name).setLevel(max(level, logging.WARNING))

    return level


def create_server() -> FastMCP:
    # Create an MCP server
    mcp = FastMCP("msprof_mcp")

    # Register tools
    mcp.tool()(msprof_analyze_advisor)

    # Initialize trace view analysis tool and register its methods
    trace_view_tool = TraceViewAnalyzeTool()
    mcp.tool()(trace_view_tool.find_slices)
    mcp.tool()(trace_view_tool.execute_sql_query)
    mcp.tool()(trace_view_tool.analyze_overlap)

    # Initialize CSV analysis tools and register their methods
    csv_analyzer = KernelDetailsAnalyzer()
    mcp.tool()(csv_analyzer.analyze_kernel_details)
    mcp.tool()(csv_analyzer.get_operator_details)

    op_stat_analyzer = OpStatisticAnalyzer()
    mcp.tool()(op_stat_analyzer.analyze_op_statistic)
    mcp.tool()(op_stat_analyzer.get_op_type_details)

    generic_csv_analyzer = GenericCsvAnalyzer()
    mcp.tool()(generic_csv_analyzer.get_csv_info)
    mcp.tool()(generic_csv_analyzer.search_csv_by_field)
    
    profiler_info_analyzer = ProfilerInfoAnalyzer()
    mcp.tool()(profiler_info_analyzer.get_profiler_config)

    comm_matrix_analyzer = CommunicationMatrixAnalyzer()
    mcp.tool()(comm_matrix_analyzer.analyze_communication)

    mcp.tool()(execute_sql)
    mcp.tool()(execute_sql_to_csv)

    return mcp


def main():
    configure_logging()
    mcp = create_server()
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
