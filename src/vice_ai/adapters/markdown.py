"""Markdown folders and Obsidian vaults: turn notes into blocks.

Each block carries its document title and heading path, so it reads sensibly on its own, both
to the embedder and to Jev, which sees one block at a time.

Timestamps matter because newer facts supersede older ones. In order of preference:
frontmatter `date` / `created` / `updated`, a YYYY-MM-DD in the file name (daily notes),
then the file's modification time.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ..types import Block
from ._common import PathSource, count_tokens, legacy_block_id
from .base import SourceConfigError

TARGET_TOKENS = 120  # merge small paragraphs up to about this size
MAX_TOKENS = 220  # split anything larger
MAX_FILE_BYTES = 2_000_000
ALWAYS_EXCLUDE = (".*/**", ".*", "**/.*/**", "node_modules/**")
OBSIDIAN_EXCLUDE = (".obsidian/**", ".trash/**")

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_EMBED = re.compile(r"!\[\[[^\]]*\]\]")
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_COMMENT = re.compile(r"%%.*?%%", re.S)
_FILE_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _parse_date(value: str) -> float | None:
    value = value.strip().strip("\"'")
    for fmt in (None, "%Y-%m-%d %H:%M", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            d = datetime.fromisoformat(value) if fmt is None else datetime.strptime(value, fmt)
            return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
        except ValueError:
            continue
    return None


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta, text[m.end():]


def note_timestamp(meta: dict[str, str], path: Path, mtime: float) -> float:
    for key in ("updated", "modified", "date", "created"):
        if key in meta and (ts := _parse_date(meta[key])) is not None:
            return ts
    if m := _FILE_DATE.search(path.stem):
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]), 12, tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    return mtime


def clean_obsidian(text: str) -> str:
    text = _COMMENT.sub("", text)
    text = _EMBED.sub("", text)
    return _WIKILINK.sub(lambda m: m.group(2) or m.group(1).split("#")[0], text)


def _split_long(text: str) -> list[str]:
    """Break oversized text at line, then sentence, boundaries."""
    if count_tokens(text) <= MAX_TOKENS:
        return [text]
    units = text.split("\n") if "\n" in text else re.split(r"(?<=[.!?])\s+", text)
    if len(units) == 1:  # one enormous unbroken run: hard cut by characters
        step = MAX_TOKENS * 3
        return [text[i:i + step] for i in range(0, len(text), step)]
    out, cur = [], ""
    for u in units:
        cand = f"{cur}\n{u}" if cur else u
        if cur and count_tokens(cand) > MAX_TOKENS:
            out.extend(_split_long(cur))
            cur = u
        else:
            cur = cand
    if cur:
        out.extend(_split_long(cur) if count_tokens(cur) > MAX_TOKENS else [cur])
    return out


def split_markdown(text: str, title: str) -> list[tuple[str, str]]:
    """Return (heading path, body) pieces. Paragraphs under one heading merge up to TARGET_TOKENS."""
    headings: list[tuple[int, str]] = []
    pieces: list[tuple[str, str]] = []
    para_lines: list[str] = []
    pending: list[str] = []
    in_code = False

    def path() -> str:
        return " › ".join([title] + [h for _, h in headings if h != title])

    def flush_pending() -> None:
        if pending:
            for part in _split_long("\n\n".join(pending)):
                pieces.append((path(), part))
            pending.clear()

    def flush_paragraph() -> None:
        if not para_lines:
            return
        para = "\n".join(para_lines).strip()
        para_lines.clear()
        if not para:
            return
        if pending and count_tokens("\n\n".join(pending + [para])) > TARGET_TOKENS:
            flush_pending()
        pending.append(para)

    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
            para_lines.append(line)
            continue
        m = None if in_code else _HEADING.match(line)
        if m:
            flush_paragraph()
            flush_pending()
            level = len(m.group(1))
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, m.group(2).strip()))
        elif not line.strip() and not in_code:
            flush_paragraph()
        else:
            para_lines.append(line.rstrip())
    flush_paragraph()
    flush_pending()
    return pieces


def _excluded(rel: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p.rstrip("/*") + "/*") for p in patterns)


def _dir_excluded(rel_dir: str, patterns: tuple[str, ...]) -> bool:
    return _excluded(rel_dir.lstrip("./") + "/x", patterns)


def _is_doc(rel: str, patterns: tuple[str, ...]) -> bool:
    return Path(rel).suffix.lower() in (".md", ".markdown") and not _excluded(rel, patterns)


def _dirs_included(parts: tuple[str, ...], patterns: tuple[str, ...]) -> bool:
    for i in range(1, len(parts) + 1):
        if parts[i - 1].startswith(".") or _dir_excluded("/".join(parts[:i]), patterns):
            return False
    return True


class MarkdownSource(PathSource):
    """A folder of Markdown files."""

    type = "markdown"
    option_keys = frozenset({"path", "exclude"})
    builtin_exclude: tuple[str, ...] = ()

    def configure(self, options: dict[str, Any]) -> None:
        super().configure(options)
        exclude = options.get("exclude", [])
        if not (isinstance(exclude, list) and all(isinstance(p, str) for p in exclude)):
            raise SourceConfigError(f"type {self.type!r}: exclude must be a list of glob patterns")
        self.exclude = tuple(exclude)

    @property
    def patterns(self) -> tuple[str, ...]:
        return ALWAYS_EXCLUDE + self.builtin_exclude + self.exclude

    def clean(self, body: str) -> str:
        return body

    def iter_files(self) -> Iterator[Path]:
        patterns = self.patterns
        for root, dirs, files in os.walk(self.path):
            rel_root = Path(root).relative_to(self.path).as_posix()
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not _dir_excluded(f"{rel_root}/{d}", patterns))
            for f in sorted(files):
                p = Path(root) / f
                if _is_doc(p.relative_to(self.path).as_posix(), patterns):
                    yield p

    def _fingerprint(self) -> str:
        h = hashlib.sha1()
        for p in self.iter_files():
            try:
                st = p.stat()
            except OSError:
                continue
            h.update(f"{p}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        return h.hexdigest()

    def _load(self) -> list[Block]:
        blocks: list[Block] = []
        for p in self.iter_files():
            try:
                st = p.stat()
                if st.st_size > MAX_FILE_BYTES:
                    continue
                raw = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            meta, body = _frontmatter(raw)
            body = self.clean(body)
            title = meta.get("title", "").strip("\"'") or p.stem
            ts = note_timestamp(meta, p, st.st_mtime)
            rel = f"{self.name}/{p.relative_to(self.path).as_posix()}"
            for heading_path, part in split_markdown(body, title):
                text = f"[{heading_path}] {part}"
                blocks.append(Block(legacy_block_id(rel, text), text, ts, count_tokens(text), rel))
        return blocks

    def _rel_parts(self, path: Path) -> tuple[str, ...] | None:
        try:
            return path.relative_to(self.path.resolve()).parts
        except ValueError:
            return None

    def indexes(self, path: Path, is_dir: bool) -> bool:
        parts = self._rel_parts(path)
        if parts is None:
            return False
        patterns = self.patterns
        if is_dir:
            return _dirs_included(parts, patterns)
        if not parts or not _dirs_included(parts[:-1], patterns) or not _is_doc("/".join(parts), patterns):
            return False
        try:
            return path.stat().st_size <= MAX_FILE_BYTES
        except OSError:
            return True  # not there (yet): judged by name alone


class ObsidianSource(MarkdownSource):
    """An Obsidian vault: Markdown plus wikilink, embed and comment cleanup."""

    type = "obsidian"
    builtin_exclude = OBSIDIAN_EXCLUDE

    def clean(self, body: str) -> str:
        return clean_obsidian(body)
