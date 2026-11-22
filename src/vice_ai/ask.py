"""The `vice ask` socket: the background service answers queries over a local Unix socket,
so a caller gets an answer without loading the index and embedding model itself.
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


def make_event(trigger: str, text: str, **meta) -> AmbientEvent:
    return AmbientEvent(f"{trigger}-{next(_ids)}", trigger, text, time.time(), meta)


async def serve(handle: Callable[[AmbientEvent], Awaitable[dict]], path: Path | None = None) -> None:
    path = path or paths.socket_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)

    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = (await reader.readline()).decode("utf-8", "replace").strip()
            if line:
                reply = await handle(make_event("ask", line))
                writer.write((json.dumps(reply) + "\n").encode())
                await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_unix_server(on_client, path=str(path))
    os.chmod(path, 0o600)  # only this user may query
    async with server:
        await server.serve_forever()


async def send(text: str, path: Path | None = None) -> dict:
    reader, writer = await asyncio.open_unix_connection(str(path or paths.socket_file()))
    writer.write((text.replace("\n", " ") + "\n").encode())
    await writer.drain()
    reply = json.loads(await reader.readline())
    writer.close()
    return reply
