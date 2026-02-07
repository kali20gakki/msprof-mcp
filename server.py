
"""
FastMCP server entry point.
"""

from mcp.server.fastmcp import FastMCP
from tools.msprof_analyze_cmd import msprof_analyze_advisor
# Import other tools here as needed in the future

# Create an MCP server
mcp = FastMCP("msprof_mcp")

# Register tools
mcp.tool()(msprof_analyze_advisor)

# Run with streamable HTTP transport
if __name__ == "__main__":
    mcp.run(transport="stdio")
