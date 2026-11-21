"""Triggers. Each one puts AmbientEvents on a shared asyncio queue.

  clipboard   polls the macOS pasteboard change counter (no accessibility permission needed)
  file drop   watches a folder; a new text file becomes an event of its name and opening lines
  palette     a local Unix socket; `vice ask "..."` sends one line and prints the decision
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
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml", ".log", ".eml", ".ics", ".py", ".js", ".ts"}
# Password managers mark secrets with these pasteboard types (nspasteboard.org convention).
CONCEALED_TYPES = {"org.nspasteboard.ConcealedType", "org.nspasteboard.TransientType", "com.agilebits.onepassword"}


def make_event(source: str, text: str, **meta) -> AmbientEvent:
    return AmbientEvent(f"{source}-{next(_ids)}", source, text, time.time(), meta)


async def clipboard_listener(queue: asyncio.Queue, interval_s: float = 0.3) -> None:
    from AppKit import NSPasteboard, NSPasteboardTypeString

    pb = NSPasteboard.generalPasteboard()
    last = pb.changeCount()  # ignore whatever was on the clipboard before start-up
    while True:
        await asyncio.sleep(interval_s)
        count = pb.changeCount()
        if count == last:
            continue
        last = count
        if CONCEALED_TYPES & set(pb.types() or []):
            continue  # never read content a password manager marked as secret
        text = pb.stringForType_(NSPasteboardTypeString)
        if text:
            await queue.put(make_event("clipboard", str(text)))


def read_dropped_file(path: Path, max_chars: int = 1200) -> str | None:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return f"Dropped file: {path.name}"  # binary formats: the name is all we read
    try:
        with path.open("r", encoding="utf-8", errors="strict") as f:
            head = f.read(max_chars)
    except (UnicodeDecodeError, OSError):
        return f"Dropped file: {path.name}"
    return f"Dropped file: {path.name}\n---\n{head.strip()}"


async def file_drop_listener(queue: asyncio.Queue, folder: Path) -> None:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    folder.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()

    class Handler(FileSystemEventHandler):
        def _emit(self, p: str) -> None:
            path = Path(p)
            if path.name.startswith(".") or not path.is_file():
                return
            time.sleep(0.05)  # let the writer finish
            text = read_dropped_file(path)
            if text:
                loop.call_soon_threadsafe(queue.put_nowait, make_event("file_drop", text, path=str(path)))

        def on_created(self, event):
            if not event.is_directory:
                self._emit(event.src_path)

        def on_moved(self, event):
            if not event.is_directory:
                self._emit(event.dest_path)

    obs = Observer()
    obs.schedule(Handler(), str(folder), recursive=False)
    obs.start()
    try:
        await asyncio.Event().wait()
    finally:
        obs.stop()
        obs.join(timeout=2)


def socket_path() -> Path:
    return paths.socket_file()


async def palette_listener(handle: Callable[[AmbientEvent], Awaitable[dict]], path: Path | None = None) -> None:
    """Unlike the other sources, the palette answers its caller, so it takes the handler directly."""
    path = path or socket_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)

    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = (await reader.readline()).decode("utf-8", "replace").strip()
            if line:
                reply = await handle(make_event("palette", line))
                writer.write((json.dumps(reply) + "\n").encode())
                await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_unix_server(on_client, path=str(path))
    os.chmod(path, 0o600)  # only this user may send commands
    async with server:
        await server.serve_forever()


async def palette_send(text: str, path: Path | None = None) -> dict:
    reader, writer = await asyncio.open_unix_connection(str(path or socket_path()))
    writer.write((text.replace("\n", " ") + "\n").encode())
    await writer.drain()
    reply = json.loads(await reader.readline())
    writer.close()
    return reply
