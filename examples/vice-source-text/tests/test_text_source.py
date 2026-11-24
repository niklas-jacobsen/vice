import os

import pytest

from vice_ai.adapters import SourceConfigError, SourceUnavailable, build
from vice_source_text import TextSource


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "a.txt").write_text("First paragraph.\n\nSecond paragraph.\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("Only paragraph.")
    (tmp_path / "skip.md").write_text("not indexed")
    return tmp_path


def test_configure_rejects_bad_options(folder):
    with pytest.raises(SourceConfigError):
        TextSource(None, {})
    with pytest.raises(SourceConfigError):
        TextSource(None, {"path": str(folder), "glob": "*"})


def test_load(folder):
    src = TextSource("notes", {"path": str(folder)})
    blocks = src.load()
    assert [b.text for b in blocks] == ["First paragraph.", "Second paragraph.", "Only paragraph."]
    assert blocks[0].source == "notes/a.txt"
    assert blocks[0].ts == (folder / "a.txt").stat().st_mtime
    assert len({b.id for b in blocks}) == 3
    assert [b.id for b in src.load()] == [b.id for b in blocks]  # stable across loads


def test_default_name(folder):
    assert TextSource(None, {"path": str(folder)}).name == folder.name


def test_fingerprint_tracks_changes(folder):
    src = TextSource("notes", {"path": str(folder)})
    before = src.fingerprint()
    assert src.fingerprint() == before
    f = folder / "a.txt"
    f.write_text("Changed.")
    os.utime(f, (1, 1))
    assert src.fingerprint() != before


def test_unavailable(tmp_path):
    src = TextSource("gone", {"path": str(tmp_path / "missing")})
    with pytest.raises(SourceUnavailable):
        src.fingerprint()
    with pytest.raises(SourceUnavailable):
        src.load()


def test_indexes(folder):
    src = TextSource("notes", {"path": str(folder)})
    root = folder.resolve()
    assert src.indexes(root / "a.txt", is_dir=False)
    assert src.indexes(root / "sub" / "b.txt", is_dir=False)
    assert not src.indexes(root / "skip.md", is_dir=False)
    assert src.indexes(root, is_dir=True)
    assert src.indexes(root / "sub", is_dir=True)
    assert not src.indexes(root.parent, is_dir=True)


def test_registered_by_entry_point(folder):
    src = build({"type": "text", "path": str(folder), "name": "notes"})
    assert isinstance(src, TextSource)
    assert len(src.load()) == 3
