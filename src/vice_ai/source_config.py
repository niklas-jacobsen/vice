"""`vice sources types|add|remove`: edit [[sources]] in config.toml without touching anything else.

New tables are appended as text and removed tables are cut out by line span, so comments and
unrelated lines survive byte for byte. Every edit is checked by parsing the file before and after.
"""
from __future__ import annotations

import argparse
import os
import re
import stat
import sys
import tempfile
import tomllib
from pathlib import Path

from . import adapters, paths, settings as settings_mod
from .adapters.base import RESERVED_KEYS, SourceConfigError

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_HEADER = re.compile(r"^\s*\[")
_SOURCES_HEADER = re.compile(r"^\s*\[\[\s*sources\s*\]\]\s*(#.*)?$")
_COMMENT_OR_BLANK = re.compile(r"^\s*(#.*)?$")
_PLUGIN_HINT = "install a source plugin with `vice plugin install`"


class EditError(Exception):
    pass


# --- TOML values ---------------------------------------------------------------------

def parse_value(raw: str):
    """A TOML value if `raw` parses as one we can write back, else the plain string."""
    try:
        v = tomllib.loads(f"v = {raw}")["v"]
    except tomllib.TOMLDecodeError:
        return raw
    return v if _writable(v) else raw


def _writable(v) -> bool:
    if isinstance(v, list):
        return all(_writable(x) for x in v)
    return isinstance(v, (str, int, float, bool))


_ESC = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _quote(s: str) -> str:
    return '"' + "".join(_ESC.get(c) or (f"\\u{ord(c):04x}" if ord(c) < 0x20 or ord(c) == 0x7F else c) for c in s) + '"'


def dump_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return "nan" if v != v else ("inf" if v == float("inf") else "-inf" if v == float("-inf") else repr(v))
    if isinstance(v, str):
        return _quote(v)
    if isinstance(v, list):
        return "[" + ", ".join(dump_value(x) for x in v) + "]"
    raise EditError(f"cannot write a {type(v).__name__} value")


def render_table(entry: dict) -> str:
    return "[[sources]]\n" + "".join(f"{k} = {dump_value(v)}\n" for k, v in entry.items())


# --- file access ---------------------------------------------------------------------

def _write(path: Path, text: str) -> None:
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read(path: Path) -> tuple[str, dict]:
    if not path.exists():
        raise EditError(f"no configuration at {path}. Run `vice setup` first.")
    text = path.read_bytes().decode()
    try:
        return text, tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise EditError(f"{path} is not valid TOML: {e}") from e


def _name_of(entry: dict) -> str | None:
    try:
        return adapters.build(entry).name
    except SourceConfigError:
        return entry.get("name") if isinstance(entry.get("name"), str) else None


# --- add -----------------------------------------------------------------------------

def add(path: Path, type_: str, pairs: list[str], name: str | None = None, guard: bool = True) -> str:
    """Append a [[sources]] table; returns the new source's name."""
    if type_ not in adapters.available():
        raise EditError(f"unknown source type {type_!r}; available: {sorted(adapters.available())}; "
                        f"{_PLUGIN_HINT}")
    entry: dict = {"type": type_}
    if name is not None:
        entry["name"] = name
    if not guard:
        entry["guard"] = False
    for p in pairs:
        k, eq, raw = p.partition("=")
        k = k.strip()
        if not eq or not _BARE_KEY.match(k):
            raise EditError(f"expected key=value, got {p!r}")
        if k in RESERVED_KEYS:
            raise EditError(f"{k} is not an option; use {'--name' if k == 'name' else '--no-guard' if k == 'guard' else 'the type argument'}")
        if k in entry:
            raise EditError(f"{k} given twice")
        entry[k] = parse_value(raw.strip())
    try:
        new_name = adapters.build(entry).name
    except SourceConfigError as e:
        raise EditError(str(e)) from e

    old, data = _read(path)
    if new_name in {_name_of(e) for e in data.get("sources", [])}:
        raise EditError(f"a source named {new_name!r} already exists; pass --name to choose another")

    new = old + ("" if not old or old.endswith("\n") else "\n") + ("\n" if old else "") + render_table(entry)
    _write(path, new)
    try:
        settings_mod.load(path)
    except settings_mod.SettingsError as e:
        _write(path, old)
        raise EditError(f"the edited config did not load, so it was restored: {e}") from e
    return new_name


# --- remove --------------------------------------------------------------------------

def _spans(lines: list[str]) -> list[tuple[int, int]]:
    """(start, end) line ranges of each [[sources]] table: header to its last key line."""
    out = []
    for i, line in enumerate(lines):
        if not _SOURCES_HEADER.match(line):
            continue
        j = i + 1
        while j < len(lines) and not _HEADER.match(lines[j]):
            j += 1
        end = j
        while end > i + 1 and _COMMENT_OR_BLANK.match(lines[end - 1]):
            end -= 1
        out.append((i, end))
    return out


def remove(path: Path, name: str) -> None:
    old, data = _read(path)
    entries = data.get("sources", [])
    if not isinstance(entries, list):
        raise EditError("[[sources]] is not a list of tables")
    hits = [i for i, e in enumerate(entries) if _name_of(e) == name]
    if not hits:
        raise EditError(f"no source named {name!r}")
    if len(hits) > 1:
        raise EditError(f"{len(hits)} sources are named {name!r}; fix config.toml by hand")
    k = hits[0]

    lines = old.splitlines(keepends=True)
    spans = _spans(lines)
    if len(spans) != len(entries):
        raise EditError("could not match [[sources]] tables to entries (is `sources` written inline?); edit config.toml by hand")
    start, end = spans[k]
    after = end
    if after < len(lines) and not lines[after].strip():
        after += 1  # the blank line that separated this table from the next block
    elif after >= len(lines) and start > 0 and not lines[start - 1].strip():
        start -= 1  # last table: take the blank line above instead
    new = "".join(lines[:start] + lines[after:])

    try:
        got = tomllib.loads(new)
    except tomllib.TOMLDecodeError as e:
        raise EditError(f"refusing to edit: result is not valid TOML ({e}); edit config.toml by hand") from e
    want = {**data, "sources": entries[:k] + entries[k + 1:]}
    if not want["sources"]:
        want.pop("sources")
    if got != want:
        raise EditError("refusing to edit: could not isolate that table safely; edit config.toml by hand")
    _write(path, new)
    try:
        settings_mod.load(path)
    except settings_mod.SettingsError as e:
        _write(path, old)
        raise EditError(f"the edited config did not load, so it was restored: {e}") from e


# --- commands ------------------------------------------------------------------------

def cmd_types(args) -> int:
    dists = {ep.name: ep.dist.name if ep.dist else "?" for ep in adapters.registry.entry_points(group=adapters.ENTRY_POINT_GROUP)}
    for t in sorted(adapters.available()):
        who = "built-in" if t in adapters.registry.BUILTIN else dists.get(t, "?")
        try:
            keys = ", ".join(sorted(adapters.adapter_class(t).option_keys)) or "(no options)"
        except Exception as e:  # a broken third-party module must not hide the rest
            keys = f"unavailable: {e}"
        print(f"{t:<12} {who:<20} {keys}")
    return 0


def cmd_add(args) -> int:
    try:
        name = add(paths.config_file(), args.type, args.options, args.name, not args.no_guard)
    except EditError as e:
        print(f"vice: {e}", file=sys.stderr)
        return 1
    print(f"added source {name!r}. `vice sync` (or the running service's next resync) will index it.")
    return 0


def cmd_remove(args) -> int:
    try:
        remove(paths.config_file(), args.name)
    except EditError as e:
        print(f"vice: {e}", file=sys.stderr)
        return 1
    print(f"removed source {args.name!r}. Its blocks leave the index on the next sync.")
    return 0


class _Intermixed(argparse.ArgumentParser):
    """Lets `key=value` arguments and flags come in any order."""
    _mixing = False

    def parse_known_args(self, args=None, namespace=None):
        if self._mixing:
            return super().parse_known_args(args, namespace)
        self._mixing = True
        try:
            return self.parse_known_intermixed_args(args, namespace)
        finally:
            self._mixing = False


def register(sub) -> None:
    p = sub.add_parser("sources", help="list source types, add or remove a source")
    s = p.add_subparsers(dest="sources_cmd", required=True, metavar="action", parser_class=_Intermixed)
    s.add_parser("types", help="list available source types and their options").set_defaults(fn=cmd_types)
    a = s.add_parser("add", help="add a source to config.toml")
    a.add_argument("type")
    a.add_argument("options", nargs="*", metavar="key=value", help='option, e.g. path=~/Notes exclude=\'["Templates/**"]\'')
    a.add_argument("--name", help="unique label (default: derived from the source)")
    a.add_argument("--no-guard", action="store_true", help="do not block agents from reading this source's files directly")
    a.set_defaults(fn=cmd_add)
    r = s.add_parser("remove", help="remove a source from config.toml")
    r.add_argument("name")
    r.set_defaults(fn=cmd_remove)
