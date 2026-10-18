"""Red String's named graph tools as an MCP server, so any MCP client (Claude Code, Claude Desktop,
FalkorDB-aware agents) can run the same P1 and Q0-Q5 the agents run. Agents never write raw Cypher.

    python -m redstring.mcp_server                 # stdio
    python -m redstring.mcp_server --http 8765     # streamable HTTP
"""
from __future__ import annotations

import argparse
import functools

from mcp.server.mcpserver import MCPServer

from . import registry


INSTRUCTIONS = (
    "Red String's graph tools over FalkorDB. One shared `agency` graph holds businesses, audiences, techniques, "
    "references and fingerprints; each prospect or client has a private `client:<slug>` graph. "
    "Q1 lead_conflict, Q2 double_take/check_draft, Q3 open_territory, Q4 decision_trace, Q5 stale_drafts, "
    "Q0 derive_signatures, P1 project_fingerprint. Every write tool also writes a Decision."
)


def _mcp_handler(tool: registry.Tool):
    @functools.wraps(tool.fn)
    def handler(**kwargs):
        return tool.call(kwargs, caller="mcp")

    return handler


def build_server(allow_writes: bool = False) -> MCPServer:
    server = MCPServer(name="redstring", instructions=INSTRUCTIONS)
    for tool in registry.TOOLS:
        if tool.writable and not allow_writes:
            continue
        server.add_tool(
            _mcp_handler(tool),
            name=tool.name,
            description=f"{tool.description} (Used by: {', '.join(tool.agents)}.)",
        )
    return server


server = build_server()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", type=int, help="serve streamable HTTP on this port instead of stdio")
    ap.add_argument("--allow-writes", action="store_true", help="expose write tools")
    a = ap.parse_args()
    active_server = build_server(a.allow_writes)
    if a.http:
        active_server.run("streamable-http", port=a.http)
    else:
        active_server.run("stdio")


if __name__ == "__main__":
    main()
