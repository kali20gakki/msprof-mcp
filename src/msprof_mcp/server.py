
"""
FastMCP server entry point.
"""

import logging
from mcp.server.fastmcp import FastMCP
from .tools.msprof_analyze_cmd import msprof_analyze_advisor
from .tools.trace_view.trace_view_analyze import TraceViewAnalyzeTool
from .tools.csv_analyze import KernelDetailsAnalyzer, OpStatisticAnalyzer, GenericCsvAnalyzer
from .tools.json_analyze import ProfilerInfoAnalyzer, CommunicationMatrixAnalyzer
# Import other tools here as needed in the future

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

    return mcp


def main():
    mcp = create_server()
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
