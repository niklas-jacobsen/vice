"""vice command line.

    vice setup        first-time configuration (key, sources)
    vice sync         index your sources now
    vice ask "..."    print what an agent receives for this text
    vice connect claude-code   register the hooks and MCP server with Claude Code
    vice hook         Claude Code UserPromptSubmit hook (prompt JSON on stdin)
    vice guard        Claude Code PreToolUse hook (tool call JSON on stdin)
    vice run          run in the foreground
    vice start|stop   run in the background (macOS)
    vice status       what is configured and whether it is running
    vice logs         follow the background service's log
    vice mcp          MCP server for agents such as Claude Code
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
from .adapters import SourceUnavailable
from .settings import SettingsError

PRIVACY = """\
Before you start, what vice sends where:

  * Your sources are indexed on this machine. Embeddings never leave it.
  * For each query that passes the local checks, its text and the ~20 most
    similar blocks are sent to TypeSafe's API (api.typesafe.ai) to be judged.
  * Text that looks like a password, key, token or card number is removed first.
"""


def _ask(prompt: str, default: str = "") -> str:
    try:
        ans = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    except EOFError:
        ans = ""
    return ans or default


def _source_type(path: Path) -> str:
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

    sources = [Path(n).expanduser() for n in args.source or []]
    if interactive and not sources:
        while True:
            p = _ask("\nSource to index (Obsidian vault, Markdown folder or .jsonl file; blank to finish)")
            if not p:
                break
            path = Path(p).expanduser()
            if not path.exists():
                print(f"  {path} does not exist.")
                continue
            sources.append(path)
    for n in sources:
        if not n.exists():
            print(f"error: source path {n} does not exist", file=sys.stderr)
            return 2

    def tilde(p: Path) -> str:
        s, h = str(p.resolve()), str(Path.home())
        return "~" + s[len(h):] if s.startswith(h) else s

    cfg_path.write_text(settings_mod.render_default([(_source_type(n), tilde(n)) for n in sources]))
    cfg_path.chmod(0o600)
    settings_mod.load()  # fail now, not later, if what we wrote is wrong
    print(f"\nWrote {cfg_path}")
    print("Next:  vice sync     (index your sources; the first run downloads a ~90 MB embedding model)")
    print("       claude mcp add vice -- vice mcp   (connect Claude Code)")
    print("       vice ask \"...\"  (check what an agent would receive)")
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
    from .index import Index

    s = _load_settings()
    if not s.sources:
        print(f"No sources configured. Add a [[sources]] entry to {paths.config_file()}.")
        return 1
    try:
        _, stats = Index(s.sources, s.pipeline).build()
    except FileNotFoundError as e:
        raise SystemExit(f"vice: {e}")
    print(f"Indexed {stats.blocks} blocks from {len(s.sources) - len(stats.skipped)} source(s) in {stats.seconds:.1f}s "
          f"({stats.embedded} embedded, {stats.reused} reused).")
    for line in stats.skipped_lines():
        print(f"  {line}", file=sys.stderr)
    return 0


class ServiceDown(Exception):
    pass


def _query(text: str, trigger: str, local: bool = True) -> dict:
    """Answer through the running service if there is one, otherwise in-process
    (unless `local` is false: loading the index takes seconds)."""
    from . import ask

    async def go() -> dict:
        if paths.socket_file().exists():
            try:
                return await ask.send(text, trigger=trigger)
            except (ConnectionRefusedError, FileNotFoundError):
                pass  # stale socket from a stopped service; fall through and answer directly
        if not local:
            raise ServiceDown("the service is not running (`vice start`); no context added")

        async def one(app):
            return await app.handle(ask.make_event(trigger, text))
        return await _with_app(one)

    return asyncio.run(go())


def cmd_ask(args) -> int:
    from .outputs import format_reply

    reply = _query(args.text, "ask")
    print(json.dumps(reply, indent=2, ensure_ascii=False) if args.json else format_reply(reply))
    return 0


def cmd_hook(args) -> int:
    """Never blocks or fails the prompt: on any error it prints nothing and exits 0.
    Claude Code does not show the agent stderr from a hook that exits 0."""
    from .outputs import format_hook

    try:
        prompt = str(json.load(sys.stdin).get("prompt") or "").strip()
        context = format_hook(_query(prompt, "hook", local=False)) if prompt else ""
    except (Exception, SystemExit) as e:  # noqa: BLE001
        print(f"vice hook: {e}", file=sys.stderr)
        return 0
    if context:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}))
    return 0


def cmd_guard(args) -> int:
    """Never breaks a tool call by failing: on any error it allows the call."""
    from .guard import decide

    try:
        reply = decide(json.load(sys.stdin), settings_mod.load().sources)
    except Exception as e:  # noqa: BLE001
        print(f"vice guard: {e}", file=sys.stderr)
        return 0
    if reply:
        print(json.dumps(reply))
    return 0


def cmd_connect(args) -> int:
    from . import claude_code as cc

    s = None if args.remove else _load_settings()
    command = cc.vice_command()
    path = args.settings or cc.settings_path()
    backup = cc.write_settings(path, command, remove=args.remove)
    print(f"{'Removed vice from' if args.remove else 'Added the prompt hook and read guard to'} {path}"
          + (f" (previous version: {backup})" if backup else ""))
    if not args.no_mcp:
        print(cc.mcp(command, remove=args.remove))
    if args.remove:
        return 0
    guarded = [src for src in s.sources if src.guard]
    print("Guarded sources: " + (", ".join(f"{src.name} ({src.describe()})" for src in guarded) or "none"))
    if not service.is_loaded():
        print("The prompt hook adds context only while the service runs: vice start")
    print("Restart Claude Code sessions to load the changes.")
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
    print(f"outputs: {', '.join(f'{o.type}({'+'.join(o.on)})' for o in s.outputs) or 'none (decisions are still logged)'}")
    if not s.sources:
        print("sources: none configured")
    for n in s.sources:
        try:
            n.fingerprint()
            state = ""
        except SourceUnavailable as e:
            state = f"  UNAVAILABLE: {e}"
        except Exception as e:  # a third-party adapter bug should not break status
            state = f"  ERROR: {type(e).__name__}: {e}"
        print(f"sources: {n.name}  {n.describe()}{state}")
    meta = paths.index_dir() / "meta.json"
    if meta.exists():
        print(f"index:   {len(json.loads(meta.read_text())['ids'])} blocks")
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
    ap = argparse.ArgumentParser(prog="vice", description="Context retrieval engine for AI agents.")
    ap.add_argument("--version", action="version", version=f"vice {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")

    p = sub.add_parser("setup", help="first-time configuration")
    p.add_argument("--source", action="append", metavar="PATH", help="Obsidian vault, Markdown folder or .jsonl file (repeatable)")
    p.add_argument("--yes", action="store_true", help="do not prompt; use flags and defaults")
    p.add_argument("--force", action="store_true", help="overwrite an existing config.toml")
    p.add_argument("--no-key", action="store_true", help="skip the API key step")
    p.add_argument("--replace-key", action="store_true", help="prompt for a new key even if one is stored")
    p.set_defaults(fn=cmd_setup)

    sub.add_parser("sync", help="index your sources now").set_defaults(fn=cmd_sync)
    p = sub.add_parser("ask", help="print what an agent receives for this text")
    p.add_argument("text")
    p.add_argument("--json", action="store_true", help="print the full decision as JSON")
    p.set_defaults(fn=cmd_ask)
    p = sub.add_parser("connect", help="register vice with an agent")
    p.add_argument("agent", choices=["claude-code"])
    p.add_argument("--remove", action="store_true", help="remove vice's hooks and MCP server instead")
    p.add_argument("--settings", type=Path, metavar="PATH", help="settings file (default ~/.claude/settings.json)")
    p.add_argument("--no-mcp", action="store_true", help="do not add or remove the MCP server")
    p.set_defaults(fn=cmd_connect)
    sub.add_parser("hook", help="Claude Code UserPromptSubmit hook (reads the prompt JSON on stdin)").set_defaults(fn=cmd_hook)
    sub.add_parser("guard", help="Claude Code PreToolUse hook (reads the tool call JSON on stdin)").set_defaults(fn=cmd_guard)
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
