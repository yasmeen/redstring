"""Red String's named graph tools as an MCP server, so any MCP client (Claude Code, Claude Desktop,
FalkorDB-aware agents) can run the same P1 and Q0-Q5 the agents run. Agents never write raw Cypher.

    python -m redstring.mcp_server                 # stdio
    python -m redstring.mcp_server --http 8765     # streamable HTTP
"""
from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from . import registry

server = MCPServer(
    name="redstring",
    instructions=(
        "Red String's graph tools over FalkorDB. One shared `agency` graph holds businesses, audiences, techniques, "
        "references and fingerprints; each prospect or client has a private `client:<slug>` graph. "
        "Q1 lead_conflict, Q2 double_take/check_draft, Q3 open_territory, Q4 decision_trace, Q5 stale_drafts, "
        "Q0 derive_signatures, P1 project_fingerprint. Every write tool also writes a Decision."
    ),
)

for t in registry.TOOLS:
    server.add_tool(t.fn, name=t.name, description=f"{t.description} (Used by: {', '.join(t.agents)}.)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", type=int, help="serve streamable HTTP on this port instead of stdio")
    a = ap.parse_args()
    if a.http:
        server.run("streamable-http", port=a.http)
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
