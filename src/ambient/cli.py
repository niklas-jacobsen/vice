"""ambient run | ambient palette "text" | ambient once "text"

There is no window. A decision either does nothing, writes context to
~/.ambient/context.json for other tools to pick up (ATTACH), or does that and also posts
a notification (SURFACE, with --notify).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

from . import tracing
from .calibrate import load_calibration
from .config import ROOT, load_config
from .jev import JudgeError
from .listeners import clipboard_listener, file_drop_listener, make_event, palette_listener, palette_send
from .pipeline import Pipeline
from .runtime import build_judge, build_retriever
from .types import Action, Chunk, PipelineResult

CONTEXT_FILE = Path.home() / ".ambient" / "context.json"


def load_notes(path: Path) -> list[Chunk]:
    """JSONL with id, text, ts (epoch seconds), and optionally tokens."""
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    out = []
    for line in path.read_text().splitlines():
        d = json.loads(line)
        out.append(Chunk(d["id"], d["text"], float(d["ts"]), d.get("tokens") or len(enc.encode(d["text"]))))
    return out


def as_reply(res: PipelineResult) -> dict:
    return {"action": res.decision.action.value, "reason": res.decision.reason,
            "gate": {"status": res.gate_status, "p": res.gate_p},
            "context": [{"id": c.id, "text": c.text, "written": time.strftime("%Y-%m-%d", time.gmtime(c.ts))} for c in res.decision.context],
            "ms": {k: round(v, 1) for k, v in res.timings_ms.items()}}


def sink(res: PipelineResult, notify: bool) -> dict:
    reply = as_reply(res)
    print(json.dumps({"event": res.event.source, **reply}), flush=True)
    if res.decision.action != Action.SUPPRESS:
        CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONTEXT_FILE.write_text(json.dumps(reply, indent=2))
    if notify and res.decision.action == Action.SURFACE and sys.platform == "darwin":
        body = res.decision.context[0].text
        subprocess.run(["osascript", "-e", "on run argv", "-e", 'display notification (item 1 of argv) with title "Ambient memory"',
                        "-e", "end run", body], check=False)
    return reply


async def make_pipeline(notes: Path) -> tuple[Pipeline, object]:
    cfg = load_config()
    cal = load_calibration(model=cfg.model)
    if not cal.gate:
        print("warning: no calibration found; using TypeSafe's default 0.7 / 0.3 thresholds", file=sys.stderr)
    judge = build_judge(cfg)
    rt = build_retriever(cal.apply(cfg), load_notes(notes))
    try:
        await judge.warm()
    except JudgeError as e:
        raise SystemExit(f"Cannot reach TypeSafe: {e}")
    return Pipeline(cfg, judge, rt, cal), judge


async def keep_warm(judge, every_s: float) -> None:
    """Hold the connection open between sparse events; a cold handshake would blow the gate budget."""
    while True:
        await asyncio.sleep(every_s)
        try:
            await judge.warm()
        except JudgeError:
            pass  # the next real request will surface the problem


async def run(args) -> None:
    tracing.configure()
    pipe, judge = await make_pipeline(args.notes)
    queue: asyncio.Queue = asyncio.Queue()

    async def handle(event) -> dict:
        return sink(await pipe.handle(event), args.notify)

    async def worker() -> None:
        while True:
            await handle(await queue.get())

    tasks = [worker(), palette_listener(handle), keep_warm(judge, pipe.cfg.keepalive_s * 0.5)]
    if not args.no_clipboard:
        tasks.append(clipboard_listener(queue))
    if args.drop:
        tasks.append(file_drop_listener(queue, args.drop))
    print(f"ambient: listening (model {pipe.cfg.model}, {len(pipe.retriever.chunks)} notes)", file=sys.stderr)
    await asyncio.gather(*tasks)


async def once(args) -> None:
    pipe, judge = await make_pipeline(args.notes)
    sink(await pipe.handle(make_event(args.source, args.text)), False)
    await judge.aclose()


def main() -> None:
    default_notes = ROOT / "data" / "golden" / "chunks.jsonl"
    ap = argparse.ArgumentParser(prog="ambient")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="start the listeners")
    r.add_argument("--notes", type=Path, default=default_notes)
    r.add_argument("--drop", type=Path, default=ROOT / "drop", help="folder to watch for dropped files")
    r.add_argument("--no-clipboard", action="store_true")
    r.add_argument("--notify", action="store_true", help="post a macOS notification on SURFACE")
    p = sub.add_parser("palette", help="send a command to a running instance")
    p.add_argument("text")
    o = sub.add_parser("once", help="run one event through the pipeline and exit")
    o.add_argument("text")
    o.add_argument("--source", default="palette", choices=["clipboard", "file_drop", "palette"])
    o.add_argument("--notes", type=Path, default=default_notes)
    args = ap.parse_args()
    try:
        if args.cmd == "run":
            asyncio.run(run(args))
        elif args.cmd == "once":
            asyncio.run(once(args))
        else:
            print(json.dumps(asyncio.run(palette_send(args.text)), indent=2))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
