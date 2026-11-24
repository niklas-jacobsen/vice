"""vice plugin: manifest, activation, dependency filtering, safe swap, and a real install."""
import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from vice_ai import plugins
from vice_ai.plugins import PluginError

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("VICE_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr("vice_ai.service.is_loaded", lambda: False)
    return tmp_path


def test_manifest_roundtrip(home):
    assert plugins.load_manifest() == []
    plugins.save_manifest(['a==1', '/p/with "quote"', 'git+https://x/y.git@v1'])
    assert plugins.load_manifest() == ['a==1', '/p/with "quote"', 'git+https://x/y.git@v1']
    assert (home / "plugins.toml").read_text().startswith("packages = [")


def test_manifest_rejects_bad_shape(home):
    (home / "plugins.toml").write_text("packages = 3\n")
    with pytest.raises(PluginError):
        plugins.load_manifest()


def test_plugin_dir_is_per_python(home):
    assert plugins.plugin_dir() == home / "plugins" / f"py{sys.version_info.major}.{sys.version_info.minor}"


def test_activate_noop_when_missing(home):
    before = list(sys.path)
    plugins.activate()
    assert sys.path == before


def test_activate_appends_once(home):
    d = plugins.plugin_dir()
    d.mkdir(parents=True)
    plugins.activate()
    plugins.activate()
    assert sys.path.count(str(d)) == 1
    assert sys.path[-1] == str(d)


def test_spec_matching():
    assert plugins.spec_matches("vice-source-text==1.0", "vice_source_text")
    assert plugins.spec_matches("Foo[extra]>=2", "foo")
    assert plugins.spec_matches("foo @ https://x/foo.whl", "foo")
    assert not plugins.spec_matches("foobar", "foo")
    assert not plugins.spec_matches("/some/path/foo", "foo")


def test_missing_deps_skips_requested_and_provided():
    resolved = [("vice-source-x", "1.0"), ("httpx", "0.27")]
    assert plugins.missing_deps(resolved, {"vice-source-x"}, {"numpy": "2.0"}) == ["httpx==0.27"]


def test_missing_deps_conflict_names_package():
    with pytest.raises(PluginError, match=r"numpy==2.1 but vice's environment has numpy==1.26"):
        plugins.missing_deps([("numpy", "2.1")], set(), {"numpy": "1.26"})


# a fake pip: creates dist-info (optionally with an entry point) in --target

def fake_dist(target: Path, name: str, ep: str | None = "text = mod:Cls"):
    di = target / f"{name.replace('-', '_')}-1.0.dist-info"
    di.mkdir(parents=True)
    (di / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
    if ep:
        (di / "entry_points.txt").write_text(f"[vice.sources]\n{ep}\n")


class FakePip:
    def __init__(self, fail_on: str | None = None, resolved=()):
        self.calls, self.fail_on, self.resolved = [], fail_on, resolved

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if "--dry-run" in cmd:
            rep = {"install": [{"metadata": {"name": n, "version": v}} for n, v in self.resolved]}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(rep), "")
        specs = cmd[cmd.index("--target") + 2:]
        if self.fail_on and self.fail_on in specs:
            return subprocess.CompletedProcess(cmd, 1, "", "boom: no such package")
        target = Path(cmd[cmd.index("--target") + 1])
        for s in specs:
            name = s.split("==")[0]
            fake_dist(target, name, None if name.startswith("noeps") else "text = mod:Cls")
        return subprocess.CompletedProcess(cmd, 0, "", "")


@pytest.fixture
def pip(monkeypatch, home):
    fp = FakePip()
    monkeypatch.setattr(plugins.subprocess, "run", fp)
    monkeypatch.setattr(plugins, "_have_pip", lambda: True)
    monkeypatch.setattr(plugins, "env_provided", lambda: {"numpy": "1.26"})
    return fp


def install(*specs, reinstall=False):
    return plugins.cmd_install(argparse.Namespace(specs=list(specs), reinstall=reinstall))


def test_install_records_manifest_and_folder(pip, home, capsys):
    pip.resolved = [("vice-source-a", "1.0")]
    assert install("vice-source-a") == 0
    assert plugins.load_manifest() == ["vice-source-a"]
    assert any(plugins.plugin_dir().glob("vice_source_a-*.dist-info"))
    assert "text" in capsys.readouterr().out
    install_calls = [c for c in pip.calls if "--dry-run" not in c]
    assert all("--no-deps" in c for c in install_calls)


def test_install_pins_only_missing_deps(pip, home):
    pip.resolved = [("vice-source-a", "1.0"), ("httpx", "0.27")]
    install("vice-source-a")
    last = [c for c in pip.calls if "--dry-run" not in c][-1]
    assert last[last.index("--target") + 2:] == ["httpx==0.27"]


def test_conflicting_dep_fails_and_leaves_state(pip, home):
    install("vice-source-a")
    before = sorted(p.name for p in plugins.plugin_dir().iterdir())
    pip.resolved = [("numpy", "2.1")]
    with pytest.raises(PluginError, match="numpy"):
        install("vice-source-b")
    assert plugins.load_manifest() == ["vice-source-a"]
    assert sorted(p.name for p in plugins.plugin_dir().iterdir()) == before
    assert not [p for p in plugins.plugin_dir().parent.iterdir() if p.name.startswith(".")]


def test_failed_pip_keeps_working_set(pip, home):
    install("vice-source-a")
    pip.fail_on = "vice-source-b"
    with pytest.raises(PluginError, match="boom"):
        install("vice-source-b")
    assert plugins.load_manifest() == ["vice-source-a"]
    assert any(plugins.plugin_dir().glob("vice_source_a-*.dist-info"))
    assert not any(plugins.plugin_dir().glob("vice_source_b-*"))


def test_package_without_entry_point_is_rejected(pip, home):
    with pytest.raises(PluginError, match="registers no source types"):
        install("noeps-pkg")
    assert plugins.load_manifest() == []
    assert not plugins.plugin_dir().exists()


def test_remove_rebuilds_from_remaining(pip, home, capsys):
    install("vice-source-a", "vice-source-b")
    assert plugins.cmd_remove(argparse.Namespace(name="vice_source_a")) == 0
    assert plugins.load_manifest() == ["vice-source-b"]
    assert not any(plugins.plugin_dir().glob("vice_source_a-*"))
    assert any(plugins.plugin_dir().glob("vice_source_b-*"))


def test_remove_last_deletes_folder(pip, home):
    install("vice-source-a")
    plugins.cmd_remove(argparse.Namespace(name="vice-source-a"))
    assert plugins.load_manifest() == []
    assert not plugins.plugin_dir().exists()


def test_remove_unknown_fails(pip, home):
    with pytest.raises(PluginError, match="no plugin"):
        plugins.cmd_remove(argparse.Namespace(name="nope"))


def test_reinstall_rebuilds_from_manifest(pip, home):
    plugins.save_manifest(["vice-source-a"])
    assert not plugins.plugin_dir().exists()
    assert install(reinstall=True) == 0
    assert any(plugins.plugin_dir().glob("vice_source_a-*"))


def test_list_flags_missing_entries(pip, home, capsys):
    plugins.save_manifest(["vice-source-a"])
    plugins.cmd_list(argparse.Namespace())
    out = capsys.readouterr().out
    assert "MISSING" in out and "--reinstall" in out


def test_no_backend_explains(monkeypatch, home):
    monkeypatch.setattr(plugins, "_have_pip", lambda: False)
    monkeypatch.setattr(plugins.shutil, "which", lambda _: None)
    with pytest.raises(PluginError, match="neither pip nor uv"):
        install("x")


def test_uv_fallback_command(monkeypatch, home):
    monkeypatch.setattr(plugins, "_have_pip", lambda: False)
    monkeypatch.setattr(plugins.shutil, "which", lambda _: "/bin/uv")
    cmd = plugins._install_cmd(plugins._backend(), Path("/t"), ["x"])
    assert cmd[:3] == ["uv", "pip", "install"] and "--python" in cmd and cmd[-1] == "x"


@pytest.mark.skipif(importlib.util.find_spec("setuptools") is None or importlib.util.find_spec("pip") is None,
                    reason="needs pip and setuptools")
def test_end_to_end_local_package(home, monkeypatch):
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_NO_BUILD_ISOLATION", "0")  # pip's spelling of --no-build-isolation
    assert install(str(ROOT / "examples" / "vice-source-text")) == 0
    try:
        from vice_ai.adapters import build

        docs = home / "notes"
        docs.mkdir()
        (docs / "a.txt").write_text("hello world\n\nsecond paragraph\n")
        src = build({"type": "text", "path": str(docs)})
        assert src.type == "text"
        assert plugins.installed()[0]["types"] == {"text": None}
    finally:
        for m in [m for m in sys.modules if m.startswith("vice_source_text")]:
            del sys.modules[m]
