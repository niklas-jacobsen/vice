"""Where a decision goes. Each output is independent: one failing never blocks another,
and none of them can change the decision.

  context_file   write the latest context as JSON (default ~/.vice/context.json)
  notification   macOS notification
  command        run a program of your choice with the decision JSON on stdin
  webhook        POST the decision JSON to a URL

Every handled event is also appended to ~/.vice/decisions.jsonl, whatever the outputs are.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import paths
from .settings import Output
from .types import Action, PipelineResult


def as_reply(res: PipelineResult) -> dict:
    return {
        "action": res.decision.action.value,
        "reason": res.decision.reason,
        "event": {"source": res.event.source, "text": res.event.text},
        "gate": {"status": res.gate_status, "p": res.gate_p},
        "context": [{"id": c.id, "text": c.text, "source": c.source,
                     "written": time.strftime("%Y-%m-%d", time.gmtime(c.ts))} for c in res.decision.context],
        "ms": {k: round(v, 1) for k, v in res.timings_ms.items()},
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _context_file(reply: dict, opts: dict) -> None:
    path = paths.expand(opts.get("path") or paths.context_file())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(reply, indent=2, ensure_ascii=False))
    tmp.chmod(0o600)
    tmp.replace(path)


def _notification(reply: dict, opts: dict) -> None:
    if sys.platform != "darwin":
        return
    first = reply["context"][0]
    more = len(reply["context"]) - 1
    body = first["text"][:240] + (f"  (+{more} more)" if more else "")
    # Text is passed as an argument, never interpolated into the script.
    subprocess.run(["osascript", "-e", "on run argv", "-e",
                    "display notification (item 1 of argv) with title \"vice\" subtitle (item 2 of argv)",
                    "-e", "end run", body, first.get("source") or ""], check=False, timeout=5, capture_output=True)


def _command(reply: dict, opts: dict) -> None:
    subprocess.run(list(opts["run"]), input=json.dumps(reply).encode(), check=True,
                   timeout=float(opts.get("timeout_s", 10)), capture_output=True)


def _webhook(reply: dict, opts: dict) -> None:
    req = urllib.request.Request(opts["url"], data=json.dumps(reply).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "vice"}, method="POST")
    with urllib.request.urlopen(req, timeout=float(opts.get("timeout_s", 5))) as r:  # noqa: S310 - URL is user-configured
        r.read()


HANDLERS = {"context_file": _context_file, "notification": _notification, "command": _command, "webhook": _webhook}


class Dispatcher:
    def __init__(self, outputs: tuple[Output, ...], log_path: Path | None = None, echo: bool = False):
        self.outputs, self.echo = outputs, echo
        self.log_path = log_path or paths.decisions_file()

    def _log(self, reply: dict, errors: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps({**reply, **({"output_errors": errors} if errors else {})}, ensure_ascii=False) + "\n")
        self.log_path.chmod(0o600)

    async def emit(self, res: PipelineResult, only: tuple[str, ...] | None = None) -> dict:
        """`only` limits which output types may fire (the log is always written)."""
        reply = as_reply(res)
        errors: dict[str, str] = {}
        if res.decision.action != Action.SUPPRESS:
            for out in self.outputs:
                if res.decision.action.value not in out.on or (only is not None and out.type not in only):
                    continue
                try:
                    await asyncio.to_thread(HANDLERS[out.type], reply, out.options)
                except Exception as e:  # noqa: BLE001 - an output must never take the service down
                    errors[out.type] = f"{type(e).__name__}: {e}"
        self._log(reply, errors)
        if self.echo:
            print(json.dumps(reply, ensure_ascii=False), flush=True)
        for name, err in errors.items():
            print(f"vice: output {name} failed: {err}", file=sys.stderr, flush=True)
        return reply
