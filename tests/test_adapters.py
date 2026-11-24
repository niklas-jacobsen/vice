"""Built-in source adapters: same blocks, ids and guard decisions as the legacy loaders."""
import hashlib
import json
import os

import pytest

from vice_ai import sources
from vice_ai.adapters import SourceConfigError, SourceUnavailable, adapter_class, build
from vice_ai.adapters.jsonl import JsonlSource
from vice_ai.adapters.markdown import MarkdownSource, ObsidianSource
from vice_ai.settings import Source


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "Vault"
    (v / ".obsidian").mkdir(parents=True)
    (v / ".obsidian" / "app.json").write_text("{}")
    (v / "Projects").mkdir()
    (v / "Templates").mkdir()
    (v / "Projects" / "Atlas.md").write_text(
        "---\ntitle: Atlas\ndate: 2026-03-01\n---\n# Atlas\n\nKickoff notes.\n\n## Launch\n\n"
        "Launch is set for [[2026-04-18|April 18]]. Owner is [[Priya Raman]].\n\n![[diagram.png]]\n\n%% aside %%\n\n"
        "## Stack\n\nRuns on PostgreSQL 16.\n")
    (v / "2026-10-05.md").write_text("Dentist moved to October 30.\n")
    (v / "Templates" / "daily.md").write_text("# {{date}}\n\nTemplate body.\n")
    (v / "notes.markdown").write_text("# Notes\n\n[[Link]] text\n")
    (v / "image.png").write_bytes(b"\x89PNG")
    return v


@pytest.fixture
def jsonl(tmp_path):
    f = tmp_path / "n.jsonl"
    f.write_text(json.dumps({"id": "a", "text": "Atlas ships April 18.", "ts": 100}) + "\n\n"
                 + json.dumps({"text": "Second", "ts": 200, "tokens": 9, "source": "elsewhere"}) + "\n"
                 + json.dumps({"text": "Third", "ts": 300}) + "\n")
    return f


def _entry(type_, path, **kw):
    return {"type": type_, "name": "nm", "path": str(path), **kw}


@pytest.mark.parametrize("type_,exclude", [("obsidian", ["Templates/**"]), ("markdown", [])])
def test_markdown_load_matches_legacy(vault, type_, exclude):
    a = build(_entry(type_, vault, exclude=exclude))
    blocks = a.load()
    legacy = sources.load_source(Source(type_, vault, "nm", tuple(exclude)))
    assert blocks == legacy and blocks
    assert {b.source for b in blocks} >= {"nm/Projects/Atlas.md", "nm/2026-10-05.md", "nm/notes.markdown"}
    assert not any(b.source.startswith("nm/.obsidian") for b in blocks)
    for b in blocks:  # same id scheme as the legacy loader: sha1(source NUL text)[:16]
        assert b.id == hashlib.sha1(f"{b.source}\0{b.text}".encode()).hexdigest()[:16]
    texts = "\n".join(b.text for b in blocks)
    if type_ == "obsidian":
        assert "[[" not in texts and "aside" not in texts and "diagram" not in texts
    else:
        assert "[[Link]]" in texts and "Template body" in texts


def test_jsonl_load_matches_legacy(jsonl):
    a = build(_entry("jsonl", jsonl))
    blocks = a.load()
    assert blocks == sources.load_source(Source("jsonl", jsonl, "nm"))
    assert [(b.id, b.ts, b.tokens, b.source) for b in blocks][:2] == [("a", 100.0, blocks[0].tokens, "nm:1"),
                                                                       (blocks[1].id, 200.0, 9, "elsewhere")]
    assert blocks[2].source == "nm:4" and blocks[2].id == hashlib.sha1("nm\0Third".encode()).hexdigest()[:16]


def test_registry_maps_types():
    assert adapter_class("markdown") is MarkdownSource
    assert adapter_class("obsidian") is ObsidianSource
    assert adapter_class("jsonl") is JsonlSource


def test_defaults(vault, jsonl):
    a = build({"type": "obsidian", "path": str(vault)})
    assert a.name == "Vault" and a.guard is True and a.describe() == f"obsidian {vault}"
    assert build({"type": "jsonl", "path": str(jsonl), "guard": False}).guard is False


@pytest.mark.parametrize("entry", [
    {"type": "markdown"},
    {"type": "markdown", "path": ""},
    {"type": "markdown", "path": 3},
    {"type": "markdown", "path": "x", "exclude": "Templates/**"},
    {"type": "markdown", "path": "x", "exclude": [1]},
    {"type": "markdown", "path": "x", "bogus": 1},
    {"type": "jsonl", "path": "x", "exclude": ["a"]},
])
def test_config_errors(entry):
    with pytest.raises(SourceConfigError):
        build(entry)


@pytest.mark.parametrize("type_", ["markdown", "obsidian", "jsonl"])
def test_missing_path_is_unavailable(tmp_path, type_):
    a = build(_entry(type_, tmp_path / "nope"))
    with pytest.raises(SourceUnavailable):
        a.fingerprint()
    with pytest.raises(SourceUnavailable):
        a.load()


def test_fingerprint_changes_on_edit(vault, jsonl):
    a = build(_entry("obsidian", vault))
    f1 = a.fingerprint()
    assert a.fingerprint() == f1
    note = vault / "2026-10-05.md"
    note.write_text("Dentist moved again, to November 2.\n")
    os.utime(note, ns=(1, 1))
    f2 = a.fingerprint()
    (vault / "new.md").write_text("fresh\n")
    f3 = a.fingerprint()
    assert len({f1, f2, f3}) == 3
    j = build(_entry("jsonl", jsonl))
    g1 = j.fingerprint()
    jsonl.write_text(jsonl.read_text() + json.dumps({"text": "More", "ts": 1}) + "\n")
    assert j.fingerprint() != g1


def test_indexes(vault, tmp_path, jsonl):
    (vault / ".hidden").mkdir()
    (vault / ".hidden" / "h.md").write_text("hidden\n")
    a = build(_entry("obsidian", vault, exclude=["Templates/**"]))
    rv = vault.resolve()
    assert a.indexes(rv / "Projects" / "Atlas.md", False)
    assert a.indexes(rv / "notes.markdown", False)
    assert not a.indexes(rv / "Templates" / "daily.md", False)  # excluded
    assert not a.indexes(rv / "image.png", False)  # not Markdown
    assert not a.indexes(rv / ".hidden" / "h.md", False)  # hidden
    assert not a.indexes(rv / ".obsidian" / "x.md", False)  # obsidian default exclude
    assert not a.indexes((tmp_path / "outside.md").resolve(), False)  # outside
    assert a.indexes(rv, True) and a.indexes(rv / "Projects", True)
    assert not a.indexes(rv / "Templates", True) and not a.indexes(rv / ".hidden", True)
    assert not a.indexes(tmp_path.resolve(), True)
    big = rv / "big.md"
    big.write_text("x" * (sources.MAX_FILE_BYTES + 1))
    assert not a.indexes(big, False)
    # the guard compares resolved paths, so a symlinked source path still matches
    link = tmp_path / "link"
    link.symlink_to(vault)
    assert build(_entry("markdown", link)).indexes(rv / "Projects" / "Atlas.md", False)

    j = build(_entry("jsonl", jsonl))
    assert j.indexes(jsonl.resolve(), False)
    assert not j.indexes(jsonl.resolve().parent, True)
    assert not j.indexes((tmp_path / "other.jsonl").resolve(), False)
