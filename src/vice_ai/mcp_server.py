"""MCP server: lets an assistant that speaks the Model Context Protocol (Claude Desktop,
Claude Code, and others) pull from vice.

Two tools:
  recall(query)      run a query through the same pipeline as any other event and return
                     the notes vice judges relevant and current
  latest_context()   the context vice most recently decided was worth having, from the
                     clipboard, a dropped file, or a command

The server speaks MCP over stdio, so the assistant starts it itself; see docs/integrations.md.
It writes nothing to stdout except protocol messages.
"""
from __future__ import annotations

import json
import sys

from . import paths, settings as settings_mod
from .app import App
from .listeners import make_event
from .outputs import as_reply


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

    @server.tool()
    async def recall(query: str) -> str:
        """Look up the user's own notes for facts relevant to `query` (projects, people,
        dates, decisions, preferences). Returns only notes judged relevant, with older
        versions of a fact removed in favour of the newest. Returns an empty list when
        nothing relevant is on file; do not guess in that case."""
        a = await app()
        await a.resync()
        res = await a.pipeline.handle(make_event("palette", query))
        reply = as_reply(res)
        return json.dumps({"notes": reply["context"], "matched": reply["action"] != "suppress", "reason": reply["reason"]},
                          ensure_ascii=False)

    @server.tool()
    async def latest_context() -> str:
        """The most recent context vice surfaced from the user's ambient activity
        (something they copied, dropped, or asked). May be stale; check `at`."""
        p = paths.context_file()
        if not p.exists():
            return json.dumps({"context": [], "note": "nothing has been surfaced yet"})
        d = json.loads(p.read_text())
        return json.dumps({"at": d.get("at"), "trigger": d.get("event"), "context": d.get("context", [])}, ensure_ascii=False)

    return server


def main() -> None:
    try:
        import mcp  # noqa: F401
    except ImportError:
        print("The MCP server needs the `mcp` package: pip install 'vice-ai[mcp]'", file=sys.stderr)
        raise SystemExit(1)
    build_server().run()
