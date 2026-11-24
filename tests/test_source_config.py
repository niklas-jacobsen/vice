"""vice sources types|add|remove: edits keep comments and unrelated lines byte for byte."""
import os
import types

import pytest

from vice_ai import cli, paths, settings, source_config
from vice_ai.adapters import registry


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("VICE_HOME", str(tmp_path / "vh"))
    (tmp_path / "vh").mkdir()
    return tmp_path


@pytest.fixture
def cfg(home):
    return paths.config_file()


def run(*argv):
    try:
        cli.main(list(argv))
    except SystemExit as e:
        return e.code
    return 0


def folders(home, *names):
    out = []
    for n in names:
        d = home / n
        d.mkdir(exist_ok=True)
        out.append(str(d))
    return out


def test_add_remove_round_trip_keeps_template(home, cfg, capsys):
    cfg.write_text(settings.render_default([]))
    original = cfg.read_text()
    a, = folders(home, "notes")
    assert run("sources", "add", "markdown", f"path={a}", "name=x") == 1  # name is a flag
    assert cfg.read_text() == original
    assert run("sources", "add", "markdown", f"path={a}", "--name", "n", 'exclude=["T/**"]') == 0
    assert "vice sync" in capsys.readouterr().out
    s = settings.load()
    assert [x.name for x in s.sources] == ["n"]
    assert cfg.read_text().startswith(original)
    assert run("sources", "remove", "n") == 0
    assert cfg.read_text() == original


def test_remove_middle_of_three_keeps_everything_else(home, cfg):
    a, b, c = folders(home, "a", "b", "c")
    text = (f"# top\n[[sources]]  # first\ntype = \"markdown\"\npath = \"{a}\"\n\n# about b\n"
            f"[[sources]]\ntype = \"markdown\"\nname = \"bee\"\npath = \"{b}\"  # mine\n\n"
            f"[[sources]]\ntype = \"markdown\"\nname = \"cee\"\npath = \"{c}\"\n\n# ---- outputs\n[outputs.context_file]\nenabled = true\n")
    cfg.write_text(text)
    assert run("sources", "remove", "bee") == 0
    want = text.replace(f"[[sources]]\ntype = \"markdown\"\nname = \"bee\"\npath = \"{b}\"  # mine\n\n", "")
    assert cfg.read_text() == want
    assert [x.name for x in settings.load().sources] == ["a", "cee"]


def test_remove_entry_without_explicit_name(home, cfg):
    a, b = folders(home, "alpha", "beta")
    cfg.write_text(f'[[sources]]\ntype = "markdown"\npath = "{a}"\n\n[[sources]]\ntype = "markdown"\npath = "{b}"\n')
    assert [x.name for x in settings.load().sources] == ["alpha", "beta"]
    assert run("sources", "remove", "alpha") == 0
    assert cfg.read_text() == f'[[sources]]\ntype = "markdown"\npath = "{b}"\n'
    assert run("sources", "remove", "alpha") == 1


def test_remove_unknown_name_leaves_file(home, cfg):
    cfg.write_text("# c\n")
    assert run("sources", "remove", "nope") == 1
    assert cfg.read_text() == "# c\n"


def test_value_parsing():
    p = source_config.parse_value
    assert p("50") == 50 and p("true") is True and p("1.5") == 1.5
    assert p('["a", "b"]') == ["a", "b"]
    assert p("~/Notes") == "~/Notes" and p("foo") == "foo"
    assert p("2026-01-01") == "2026-01-01"  # dates are not writable, stay strings
    assert p('"quoted"') == "quoted"


def test_value_writer_escapes():
    import tomllib
    for v in ['a"b\\c\nd\t\x7f', ["x", 1, 2.5, True, ["n"]], "é"]:
        assert tomllib.loads(f"v = {source_config.dump_value(v)}")["v"] == v


def test_add_typed_values_and_no_guard(home, cfg):
    d, = folders(home, "d")
    cfg.write_text("")
    assert run("sources", "add", "obsidian", f"path={d}", 'exclude=["Templates/**"]', "--no-guard", "--name", "v") == 0
    (src,) = settings.load().sources
    assert src.name == "v" and src.guard is False
    assert 'exclude = ["Templates/**"]' in cfg.read_text() and "guard = false" in cfg.read_text()


def test_duplicate_name_refused(home, cfg):
    d, = folders(home, "d")
    cfg.write_text(f'[[sources]]\ntype = "markdown"\npath = "{d}"\n')
    before = cfg.read_text()
    assert run("sources", "add", "markdown", f"path={d}") == 1  # default name "d" collides
    assert run("sources", "add", "markdown", f"path={d}", "--name", "d") == 1
    assert cfg.read_text() == before
    assert run("sources", "add", "markdown", f"path={d}", "--name", "d2") == 0


def test_unknown_type_mentions_plugin_install(home, cfg, capsys):
    cfg.write_text("# c\n")
    assert run("sources", "add", "nosuch", "path=x") == 1
    assert "vice plugin install" in capsys.readouterr().err
    assert cfg.read_text() == "# c\n"


def test_invalid_options_leave_file_untouched(home, cfg):
    cfg.write_text("# c\n")
    assert run("sources", "add", "markdown", "bogus=1") == 1
    assert run("sources", "add", "markdown") == 1  # path missing
    assert cfg.read_text() == "# c\n"


def test_add_restores_when_whole_file_does_not_load(home, cfg):
    d, = folders(home, "d")
    bad = "resync_s = 1\nunknown_key = 1\n"
    cfg.write_text(bad)
    assert run("sources", "add", "markdown", f"path={d}") == 1
    assert cfg.read_text() == bad


def test_add_without_trailing_newline_and_permissions(home, cfg):
    d, = folders(home, "d")
    cfg.write_text("# c")
    os.chmod(cfg, 0o640)
    assert run("sources", "add", "markdown", f"path={d}") == 0
    assert cfg.read_text().startswith("# c\n\n[[sources]]")
    assert oct(cfg.stat().st_mode & 0o777) == "0o640"
    assert not [p for p in cfg.parent.iterdir() if p.name.endswith(".tmp")]


def test_types_lists_builtin_and_broken_plugin(home, monkeypatch, capsys):
    ep = types.SimpleNamespace(name="ghost", value="no_such_module_xyz:Ghost", dist=types.SimpleNamespace(name="vice-ghost"))
    monkeypatch.setattr(registry, "entry_points", lambda group: [ep])
    assert run("sources", "types") == 0
    rows = {l.split()[0]: l for l in capsys.readouterr().out.splitlines()}
    assert "built-in" in rows["markdown"] and "path" in rows["markdown"]
    assert "vice-ghost" in rows["ghost"] and "unavailable" in rows["ghost"]
    assert {"obsidian", "jsonl"} <= set(rows)
