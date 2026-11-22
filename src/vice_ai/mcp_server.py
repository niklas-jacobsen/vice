"""MCP server: one `recall` tool for assistants that speak the Model Context Protocol
(Claude Code, Claude Desktop and other stdio clients).

Output is kept minimal so a lookup costs the assistant as little context as possible: one
line per block, `[date] text`, or a short fixed sentence when there is nothing to return.
Source paths, ids and scores stay in the decision log.

The server speaks MCP over stdio, so the assistant starts it itself; see docs/integrations.md.
It writes nothing to stdout except protocol messages.
"""
from __future__ import annotations

import sys

from . import settings as settings_mod
from .app import App
from .ask import make_event
from .outputs import format_reply

# The assistant asked and receives the answer itself; other outputs would only duplicate it.
RECALL_OUTPUTS = ("context_file",)

RECALL_DOC = """Look up information from the user's own sources (projects, people, dates, decisions, preferences).
Pass the user's question as they wrote it; do not add keywords or rephrase.
One call is enough: vice already searches broadly and keeps only current, relevant information.
"No relevant information." is final; do not retry or rephrase."""


def build_server():
    try:
        from mcp.server.mcpserver import MCPServer  # mcp 2.x
    except ImportError:
        from mcp.server.fastmcp import FastMCP as MCPServer  # mcp 1.x name for the same class

    server = MCPServer("vice")
    state: dict = {}

    async def app() -> App:
        if "app" not in state:
            a = App(settings_mod.load())
            await a.start()
            state["app"] = a
        return state["app"]

    @server.tool(description=RECALL_DOC)
    async def recall(query: str) -> str:
        a = await app()
        await a.resync()
        res = await a.pipeline.handle(make_event("mcp", query))
        return format_reply(await a.dispatcher.emit(res, only=RECALL_OUTPUTS))

    return server


def main() -> None:
    try:
        import mcp  # noqa: F401
    except ImportError:
        print("The MCP server needs the `mcp` package: pip install 'vice-ai[mcp]'", file=sys.stderr)
        raise SystemExit(1)
    build_server().run()
