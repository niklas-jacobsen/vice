"""MCP server: lets an assistant that speaks the Model Context Protocol (Claude Desktop,
Claude Code, and others) pull from vice.

Output is kept minimal so lookups cost the assistant as little context as possible: one
line per note, `[date] text`, or a short fixed sentence when there is
nothing to return. Source paths, ids and scores stay in the decision log.

  recall(query)               tool: the notes vice judges relevant and current
  vice://latest-context       resource: the context vice last produced from the user's
                              clipboard, a dropped file, a question, or a recall

The context is a resource rather than a tool so it costs nothing until a client reads it.
The server speaks MCP over stdio, so the assistant starts it itself; see docs/integrations.md.
It writes nothing to stdout except protocol messages.
"""
from __future__ import annotations

import json
import sys

from . import paths, settings as settings_mod
from .app import App
from .listeners import make_event

RECALL_OUTPUTS = ("context_file",)

NO_CONTEXT = "No relevant information."
UNAVAILABLE = "vice could not check the notes right now (the judging service did not answer)."
NOTHING_YET = "Nothing surfaced yet."

# Reasons where vice did not get to look, as opposed to looking and finding nothing.
_UNAVAILABLE_REASONS = {"gate_unavailable", "fanout_unavailable"}

RECALL_DOC = """Look up information from the user's own notes (projects, people, dates, decisions, preferences).
Pass the user's question as they wrote it; do not add keywords or rephrase.
One call is enough: vice already searches broadly and drops outdated versions of a fact.
"No relevant information." is final; do not retry or rephrase."""


def _one_line(text: str) -> str:
    return " ".join(text.split())


def format_notes(context: list[dict]) -> str:
    """One line per note: `[date] text`."""
    return "\n".join(f"[{c['written']}] {_one_line(c['text'])}" for c in context)


def format_recall(reply: dict) -> str:
    if reply["context"]:
        return format_notes(reply["context"])
    return UNAVAILABLE if reply["reason"] in _UNAVAILABLE_REASONS else NO_CONTEXT


def format_latest(reply: dict | None) -> str:
    if not reply or not reply.get("context"):
        return NOTHING_YET
    return f"From {reply['event']['source']} at {reply['at']}:\n" + format_notes(reply["context"])


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
        # Log it and keep context.json current, but don't notify or run hooks: the
        # assistant asked, and it is the one receiving the answer.
        return format_recall(await a.dispatcher.emit(res, only=RECALL_OUTPUTS))

    @server.resource("vice://latest-context", name="latest-context", mime_type="text/plain",
                     description="Information vice last surfaced from the user's activity.")
    def latest_context() -> str:
        p = paths.context_file()
        return format_latest(json.loads(p.read_text()) if p.exists() else None)

    return server


def main() -> None:
    try:
        import mcp  # noqa: F401
    except ImportError:
        print("The MCP server needs the `mcp` package: pip install 'vice-ai[mcp]'", file=sys.stderr)
        raise SystemExit(1)
    build_server().run()
