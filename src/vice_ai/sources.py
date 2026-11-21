"""Information sources: turn a folder of Markdown, an Obsidian vault, or a JSONL file into
blocks (`Block`s).

Each Markdown block carries its document title and heading path, so it reads sensibly on its own, both
to the embedder and to Jev, which sees one block at a time.

Timestamps matter because newer facts supersede older ones. In order of preference:
frontmatter `date` / `created` / `updated`, a YYYY-MM-DD in the file name (daily notes),
then the file's modification time.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .settings import Source
from .types import Block

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
_enc = None


def count_tokens(text: str) -> int:
    global _enc
    if _enc is None:
        import tiktoken

        _enc = tiktoken.get_encoding("cl100k_base")
    return len(_enc.encode(text, disallowed_special=()))


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


def iter_files(src: Source) -> Iterator[Path]:
    if src.type == "jsonl":
        if src.path.is_file():
            yield src.path
        return
    patterns = ALWAYS_EXCLUDE + (OBSIDIAN_EXCLUDE if src.type == "obsidian" else ()) + src.exclude
    for root, dirs, files in os.walk(src.path):
        rel_root = Path(root).relative_to(src.path).as_posix()
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not _excluded(f"{rel_root}/{d}".lstrip("./") + "/x", patterns))
        for f in sorted(files):
            p = Path(root) / f
            if p.suffix.lower() in (".md", ".markdown") and not _excluded(p.relative_to(src.path).as_posix(), patterns):
                yield p


def fingerprint(sources: tuple[Source, ...]) -> str:
    """Changes whenever any source file is added, removed or modified. Cheap: stat calls only."""
    h = hashlib.sha1()
    for src in sources:
        for p in iter_files(src):
            try:
                st = p.stat()
            except OSError:
                continue
            h.update(f"{p}|{st.st_mtime_ns}|{st.st_size}\n".encode())
    return h.hexdigest()


def _block_id(source: str, text: str) -> str:
    return hashlib.sha1(f"{source}\0{text}".encode()).hexdigest()[:16]


def load_source(src: Source) -> list[Block]:
    blocks: list[Block] = []
    if src.type == "jsonl":
        for n, line in enumerate(src.path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            d = json.loads(line)
            text = str(d["text"])
            blocks.append(Block(str(d.get("id") or _block_id(src.name, text)), text, float(d["ts"]),
                                int(d.get("tokens") or count_tokens(text)), d.get("source") or f"{src.name}:{n + 1}"))
        return blocks

    for p in iter_files(src):
        try:
            st = p.stat()
            if st.st_size > MAX_FILE_BYTES:
                continue
            raw = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta, body = _frontmatter(raw)
        if src.type == "obsidian":
            body = clean_obsidian(body)
        title = meta.get("title", "").strip("\"'") or p.stem
        ts = note_timestamp(meta, p, st.st_mtime)
        rel = f"{src.name}/{p.relative_to(src.path).as_posix()}"
        for heading_path, part in split_markdown(body, title):
            text = f"[{heading_path}] {part}"
            blocks.append(Block(_block_id(rel, text), text, ts, count_tokens(text), rel))
    return blocks


def load_all(sources: tuple[Source, ...]) -> list[Block]:
    seen: dict[str, Block] = {}
    for src in sources:
        if not src.path.exists():
            raise FileNotFoundError(f"source {src.name!r}: {src.path} does not exist")
        for c in load_source(src):
            seen.setdefault(c.id, c)  # identical text in the same file collapses to one block
    return list(seen.values())
