"""MCP server: the same tools, usable from Claude Desktop and Cursor.
One server process = one tenant (set by MCP_TENANT_ID), so isolation holds here too.
Read-only on purpose: no save_match here. Never print() in this file: stdout is the MCP channel."""
import os
import sys

from mcp.server.mcpserver import MCPServer   # MCP Python SDK v2 (v1 called this FastMCP)

import tools


def tenant_from_env() -> str:
    """Fail closed: no tenant configured means no server, never a silent default tenant."""
    tenant = os.getenv("MCP_TENANT_ID", "").strip()
    if not tenant:
        sys.exit("MCP_TENANT_ID is not set: refusing to start without a tenant")   # goes to stderr
    return tenant


TENANT_ID = tenant_from_env()
mcp = MCPServer("texas-contract-finder")


@mcp.tool()
def search_opportunities(keywords: str | None = None, days_ahead: int = 30, min_days_left: int = 3,
                         place_of_performance: str | None = None, source: str | None = None,
                         limit: int = 10) -> dict:
    """Find open federal (SAM.gov) and Texas (ESBD) opportunities matching this business's industry codes.
    Leave keywords empty for broad requests. place_of_performance is a 2-letter state like TX.
    source is 'sam' or 'esbd'. Deadlines are US Central."""
    return tools.run_tool("search_opportunities",
                          {"keywords": keywords, "days_ahead": days_ahead, "min_days_left": min_days_left,
                           "place_of_performance": place_of_performance, "source": source, "limit": limit},
                          TENANT_ID)


@mcp.tool()
def past_awards(naics: str | None = None) -> dict:
    """Who usually wins federal contracts in Texas for an industry code, and how big they are."""
    return tools.run_tool("past_awards", {"naics": naics}, TENANT_ID)


@mcp.tool()
def read_document(opp_id: str, question: str) -> dict:
    """Answer any question about what a federal opportunity's documents say: how and when to submit,
    scope, requirements, bonds, insurance. Returns excerpts with file names and page numbers."""
    return tools.run_tool("read_document", {"opp_id": opp_id, "question": question}, TENANT_ID)


@mcp.tool()
def check_fit(opp_id: str) -> dict:
    """Score how well this business fits one opportunity: score, verdict, reasons, blockers, citations."""
    return tools.run_tool("check_fit", {"opp_id": opp_id}, TENANT_ID)


if __name__ == "__main__":
    mcp.run()   # stdio transport by default: the client app starts this process and talks over stdin/stdout
