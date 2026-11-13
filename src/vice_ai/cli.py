"""vice command line.

    vice setup        first-time configuration (key, notes, sources)
    vice sync         index your notes now
    vice ask "..."    ask a question against your notes
    vice run          run in the foreground
    vice start|stop   run in the background (macOS)
    vice status       what is configured and whether it is running
    vice logs         follow the background service's log
    vice mcp          MCP server for assistants such as Claude Desktop
    vice key set|delete
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

from . import __version__, keys, paths, service, settings as settings_mod
from .settings import SettingsError

PRIVACY = """\
Before you start, what vice sends where:

  * Your notes are indexed on this machine. Embeddings never leave it.
  * When an event passes the local checks, its text and the ~20 most similar note
    excerpts are sent to TypeSafe's API (api.typesafe.ai) to be judged.
  * Text that looks like a password, key, token or card number is removed first,
    and clipboard entries a password manager marks as secret are never read.
  * Clipboard watching is OFF unless you turn it on.
"""


def _ask(prompt: str, default: str = "") -> str:
    try:
        ans = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    except EOFError:
        ans = ""
    return ans or default


def _yes(prompt: str, default: bool) -> bool:
    ans = _ask(f"{prompt} ({'Y/n' if default else 'y/N'})").lower()
    return default if not ans else ans.startswith("y")


def _note_type(path: Path) -> str:
    if path.is_file() and path.suffix == ".jsonl":
        return "jsonl"
    return "obsidian" if (path / ".obsidian").is_dir() else "markdown"


def cmd_setup(args) -> int:
    paths.ensure_home()
    interactive = not args.yes
    print(PRIVACY)

    if args.no_key:
        pass
    elif keys.source() and not args.replace_key:
        print(f"TypeSafe API key: found in {keys.source()}.")
    elif interactive:
        key = getpass.getpass("TypeSafe API key (input hidden; create one in the TypeSafe console): ").strip()
        if key:
            keys.store(key)
            print("Key saved to the system keychain.")
        else:
            print("No key entered. Add one later with `vice key set`.")
    else:
        print("No key stored. Add one with `vice key set`, or set TYPESAFE_API_KEY.")

    cfg_path = paths.config_file()
    if cfg_path.exists() and not args.force:
        print(f"\nKeeping your existing configuration at {cfg_path}. Use --force to rewrite it.")
        return 0

    notes = [Path(n).expanduser() for n in args.notes or []]
    if interactive and not notes:
        while True:
            p = _ask("\nFolder of notes to remember (Obsidian vault or Markdown folder; blank to finish)")
            if not p:
                break
            path = Path(p).expanduser()
            if not path.exists():
                print(f"  {path} does not exist.")
                continue
            notes.append(path)
    for n in notes:
        if not n.exists():
            print(f"error: notes path {n} does not exist", file=sys.stderr)
            return 2

    clipboard = args.clipboard if args.clipboard is not None else (interactive and _yes("Watch the clipboard?", False))
    drop_folder = args.drop_folder or "~/vice-drop"
    file_drop = bool(args.drop_folder) or (interactive and _yes(f"Watch a drop folder ({drop_folder})?", False))
    notification = args.notify if args.notify is not None else (not interactive or _yes("Show a notification on a strong match?", True))

    def tilde(p: Path) -> str:
        s, h = str(p.resolve()), str(Path.home())
        return "~" + s[len(h):] if s.startswith(h) else s

    cfg_path.write_text(settings_mod.render_default([(_note_type(n), tilde(n)) for n in notes], clipboard, file_drop, drop_folder, notification))
    cfg_path.chmod(0o600)
    settings_mod.load()  # fail now, not later, if what we wrote is wrong
    print(f"\nWrote {cfg_path}")
    print("Next:  vice sync     (index your notes; the first run downloads a ~90 MB embedding model)")
    print("       vice ask \"...\"  (try a question)")
    print("       vice start    (run in the background)")
    return 0


def _load_settings():
    try:
        return settings_mod.load()
    except SettingsError as e:
        raise SystemExit(f"vice: {e}")


async def _with_app(fn, echo: bool = False):
    from .app import App
    from .jev import JudgeError

    app = App(_load_settings(), echo=echo)
    try:
        await app.start()
        return await fn(app)
    except keys.MissingKey as e:
        raise SystemExit(f"vice: {e}")
    except JudgeError as e:
        raise SystemExit(f"vice: cannot reach TypeSafe: {e}")
    except FileNotFoundError as e:
        raise SystemExit(f"vice: {e}")
    finally:
        await app.close()


def cmd_sync(args) -> int:
    from .index import NotesIndex

    s = _load_settings()
    if not s.notes:
        print(f"No notes sources configured. Add a [[notes]] block to {paths.config_file()}.")
        return 1
    try:
        _, stats = NotesIndex(s.notes, s.pipeline).build()
    except FileNotFoundError as e:
        raise SystemExit(f"vice: {e}")
    print(f"Indexed {stats.chunks} chunks from {len(s.notes)} source(s) in {stats.seconds:.1f}s "
          f"({stats.embedded} embedded, {stats.reused} reused).")
    return 0


def _print_reply(reply: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(reply, indent=2, ensure_ascii=False))
        return
    if not reply["context"]:
        why = {"gate_no": "this does not look like something that needs your notes",
               "no_relevant_context": "nothing in your notes answers this",
               "gate_unavailable": "TypeSafe did not answer in time",
               "fanout_unavailable": "TypeSafe did not answer in time"}.get(reply["reason"], reply["reason"])
        print(f"Nothing to show: {why}.")
        return
    for c in reply["context"]:
        print(f"• {c['text']}\n    {c.get('source') or c['id']}  ·  {c['written']}")


def cmd_ask(args) -> int:
    from .listeners import make_event, palette_send

    async def go() -> dict:
        if paths.socket_file().exists():
            try:
                return await palette_send(args.text)
            except (ConnectionRefusedError, FileNotFoundError):
                pass  # stale socket from a stopped service; fall through and answer directly

        async def one(app):
            return await app.handle(make_event("palette", args.text))
        return await _with_app(one)

    _print_reply(asyncio.run(go()), args.json)
    return 0


def cmd_run(args) -> int:
    paths.ensure_home()

    async def serve(app):
        await app.serve()
    try:
        asyncio.run(_with_app(serve, echo=args.verbose))
    except KeyboardInterrupt:
        pass
    return 0


def cmd_start(args) -> int:
    _load_settings()
    if not keys.source():
        raise SystemExit("vice: no TypeSafe API key. Run `vice key set` first.")
    if os.environ.get(keys.ENV) and keys.source() == "environment":
        print("note: your key is in the environment, which the background service cannot see. "
              "Store it with `vice key set`.", file=sys.stderr)
    service.start()
    print(f"vice is running in the background and will start at login.\nLogs: {paths.logs_dir()}/  ·  stop with `vice stop`")
    return 0


def cmd_stop(args) -> int:
    print("vice stopped." if service.stop() else "vice was not running.")
    return 0


def cmd_status(args) -> int:
    print(f"vice {__version__}\nhome:    {paths.home()}")
    print(f"service: {'running' if service.is_loaded() else 'not running'}")
    print(f"api key: {keys.source() or 'MISSING (run `vice key set`)'}")
    try:
        s = settings_mod.load()
    except SettingsError as e:
        print(f"config:  {e}")
        return 1
    srcs = [n for n, on in (("clipboard", s.clipboard), ("file_drop", s.file_drop), ("palette", s.palette)) if on]
    print(f"sources: {', '.join(srcs) or 'none'}")
    for f in s.drop_folders if s.file_drop else ():
        print(f"         drop folder {f}")
    print(f"outputs: {', '.join(f'{o.type}({'+'.join(o.on)})' for o in s.outputs) or 'none (decisions are still logged)'}")
    if not s.notes:
        print("notes:   none configured")
    for n in s.notes:
        print(f"notes:   {n.name} ({n.type}) {n.path}{'' if n.path.exists() else '  <-- MISSING'}")
    meta = paths.index_dir() / "meta.json"
    if meta.exists():
        print(f"index:   {len(json.loads(meta.read_text())['ids'])} chunks")
    else:
        print("index:   not built yet (run `vice sync`)")
    cal = "your own" if paths.user_calibration().exists() else "shipped default (fitted on synthetic data)"
    print(f"calibration: {cal}")
    return 0


def cmd_logs(args) -> int:
    log = paths.logs_dir() / "vice.err.log"
    if not log.exists():
        print(f"No log yet at {log}.")
        return 1
    return subprocess.call(["tail", "-n", "50", "-f", str(log)])


def cmd_mcp(args) -> int:
    from .mcp_server import main as mcp_main

    mcp_main()
    return 0


def cmd_key(args) -> int:
    if args.action == "set":
        key = getpass.getpass("TypeSafe API key (input hidden): ").strip()
        if not key:
            print("Nothing entered; key unchanged.")
            return 1
        keys.store(key)
        print("Key saved to the system keychain.")
    else:
        keys.delete()
        print("Key removed from the system keychain.")
    return 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="vice", description="Zero-UI ambient memory for your notes.")
    ap.add_argument("--version", action="version", version=f"vice {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")

    p = sub.add_parser("setup", help="first-time configuration")
    p.add_argument("--notes", action="append", metavar="PATH", help="notes folder or .jsonl file (repeatable)")
    p.add_argument("--clipboard", action=argparse.BooleanOptionalAction, default=None, help="watch the clipboard")
    p.add_argument("--drop-folder", metavar="PATH", help="watch this folder for dropped files")
    p.add_argument("--notify", action=argparse.BooleanOptionalAction, default=None, help="notify on a strong match")
    p.add_argument("--yes", action="store_true", help="do not prompt; use flags and defaults")
    p.add_argument("--force", action="store_true", help="overwrite an existing config.toml")
    p.add_argument("--no-key", action="store_true", help="skip the API key step")
    p.add_argument("--replace-key", action="store_true", help="prompt for a new key even if one is stored")
    p.set_defaults(fn=cmd_setup)

    sub.add_parser("sync", help="index your notes now").set_defaults(fn=cmd_sync)
    p = sub.add_parser("ask", help="ask a question against your notes")
    p.add_argument("text")
    p.add_argument("--json", action="store_true", help="print the full decision as JSON")
    p.set_defaults(fn=cmd_ask)
    p = sub.add_parser("run", help="run in the foreground")
    p.add_argument("-v", "--verbose", action="store_true", help="print each decision as JSON")
    p.set_defaults(fn=cmd_run)
    sub.add_parser("start", help="run in the background and at login (macOS)").set_defaults(fn=cmd_start)
    sub.add_parser("stop", help="stop the background service").set_defaults(fn=cmd_stop)
    sub.add_parser("status", help="show configuration and service state").set_defaults(fn=cmd_status)
    sub.add_parser("logs", help="follow the background service's log").set_defaults(fn=cmd_logs)
    sub.add_parser("mcp", help="run the MCP server (stdio)").set_defaults(fn=cmd_mcp)
    p = sub.add_parser("key", help="store or remove the TypeSafe API key")
    p.add_argument("action", choices=["set", "delete"])
    p.set_defaults(fn=cmd_key)

    args = ap.parse_args(argv)
    try:
        raise SystemExit(args.fn(args))
    except SettingsError as e:
        raise SystemExit(f"vice: {e}")


if __name__ == "__main__":
    main()
