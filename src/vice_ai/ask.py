"""The service socket: the background service answers `vice ask` and `vice hook` over a
local Unix socket, so the caller gets an answer without loading the index and embedding
model itself. One JSON line in (`{"trigger": ..., "text": ...}`), one JSON reply out.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
import time
from pathlib import Path
from typing import Awaitable, Callable

from . import paths
from .types import AmbientEvent

_ids = itertools.count()
SOCKET_TRIGGERS = ("ask", "hook")


def make_event(trigger: str, text: str, **meta) -> AmbientEvent:
    return AmbientEvent(f"{trigger}-{next(_ids)}", trigger, text, time.time(), meta)


async def serve(handle: Callable[[AmbientEvent], Awaitable[dict]], path: Path | None = None) -> None:
    path = path or paths.socket_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)

    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            msg = json.loads((await reader.readline()).decode("utf-8", "replace") or "{}")
            trigger = msg.get("trigger") if msg.get("trigger") in SOCKET_TRIGGERS else "ask"
            if text := str(msg.get("text") or "").strip():
                reply = await handle(make_event(trigger, text))
                writer.write((json.dumps(reply) + "\n").encode())
                await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_unix_server(on_client, path=str(path))
    os.chmod(path, 0o600)  # only this user may query
    async with server:
        await server.serve_forever()


async def send(text: str, path: Path | None = None, trigger: str = "ask") -> dict:
    reader, writer = await asyncio.open_unix_connection(str(path or paths.socket_file()))
    writer.write((json.dumps({"trigger": trigger, "text": text}) + "\n").encode())
    await writer.drain()
    reply = json.loads(await reader.readline())
    writer.close()
    return reply
