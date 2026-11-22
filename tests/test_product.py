"""Settings, notes import, index caching, outputs, service file, and the setup command."""
import json
import os
import plistlib
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pytest

from vice_ai import outputs, sources, paths, service, settings
from vice_ai.cli import main as cli
from vice_ai.config import Config
from vice_ai.index import Index
from vice_ai.settings import Source, Output, SettingsError
from vice_ai.types import Action, AmbientEvent, Block, Decision, PipelineResult


@pytest.fixture(autouse=True)
def vice_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VICE_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "Vault"
    (v / ".obsidian").mkdir(parents=True)
    (v / ".obsidian" / "app.json").write_text("{}")
    (v / "Projects").mkdir()
    (v / "Templates").mkdir()
    (v / "Projects" / "Atlas.md").write_text(
        "---\ntitle: Atlas\ndate: 2026-03-01\n---\n# Atlas\n\nKickoff notes.\n\n## Launch\n\n"
        "Launch is set for [[2026-04-18|April 18]]. Owner is [[Priya Raman]].\n\n![[diagram.png]]\n\n%% private aside %%\n\n"
        "## Stack\n\nRuns on PostgreSQL 16 in eu-west-1.\n")
    (v / "2026-10-05.md").write_text("Dentist moved to October 30.\n")
    (v / "Templates" / "daily.md").write_text("# {{date}}\n\nTemplate body.\n")
    (v / "image.png").write_bytes(b"\x89PNG")
    return v


# --- settings ---

def test_settings_parse_and_validation(tmp_path):
    s = settings.parse({
        "sources": [{"type": "obsidian", "path": str(tmp_path), "exclude": ["Templates/**"]}],
        "outputs": {"context_file": {"on": ["surface"]}, "command": {"run": ["/bin/cat"], "enabled": False},
                    "webhook": {"url": "http://127.0.0.1:1/x"}},
        "pipeline": {"token_budget": 200},
    })
    assert s.sources[0].name == tmp_path.name and s.sources[0].exclude == ("Templates/**",)
    assert [o.type for o in s.outputs] == ["context_file", "webhook"]  # disabled command dropped
    assert s.pipeline.token_budget == 200 and s.pipeline.top_k == Config().top_k


@pytest.mark.parametrize("bad", [
    {"trigers": {}},
    {"outputs": {"context_file": {"pth": "x"}}},
    {"sources": [{"type": "notion", "path": "x"}]},
    {"sources": [{"type": "markdown"}]},
    {"outputs": {"slack": {}}},
    {"outputs": {"command": {}}},
    {"outputs": {"webhook": {"url": "ftp://x"}}},
    {"outputs": {"context_file": {"on": ["suppress"]}}},
    {"pipeline": {"tokn_budget": 1}},
])
def test_settings_reject_typos(bad):
    with pytest.raises(SettingsError):
        settings.parse(bad)


@pytest.mark.parametrize("old, hint", [
    ({"notes": [{"type": "markdown", "path": "x"}]}, "[[sources]]"),
    ({"sources": {"clipboard": {"enabled": True}}}, "[triggers.*]"),
    ({"triggers": {"clipboard": {"enabled": True}}}, "[triggers] has been removed"),
    ({"outputs": {"notification": {"on": ["surface"]}}}, "[outputs.notification] has been removed"),
])
def test_old_keys_get_a_pointer(old, hint):
    with pytest.raises(SettingsError, match=hint.replace("[", r"\[").replace("]", r"\]").replace("*", r"\*")):
        settings.parse(old)


def test_default_is_private():
    s = settings.parse({})
    assert s.sources == () and [o.type for o in s.outputs] == []


# --- notes ---

def test_obsidian_vault_import(vault):
    src = Source("obsidian", vault, "Vault", ("Templates/**",))
    blocks = sources.load_source(src)
    text = "\n".join(c.text for c in blocks)
    assert {c.source for c in blocks} == {"Vault/Projects/Atlas.md", "Vault/2026-10-05.md"}  # template, dotdir, png skipped
    launch = next(c for c in blocks if "April 18" in c.text)
    assert launch.text.startswith("[Atlas › Launch] ") and "Owner is Priya Raman" in launch.text  # wikilinks unwrapped
    assert "[[" not in text and "diagram" not in text and "private aside" not in text
    assert any(c.text.startswith("[Atlas › Stack] ") for c in blocks)
    # Dates: frontmatter wins; a daily note's file name is used; never "now".
    assert launch.ts == datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp()
    daily = next(c for c in blocks if "Dentist" in c.text)
    assert datetime.fromtimestamp(daily.ts, timezone.utc).date().isoformat() == "2026-10-05"
    assert len({c.id for c in blocks}) == len(blocks)


def test_long_blocks_split_and_short_ones_merge():
    short = sources.split_markdown("One.\n\nTwo.\n\nThree.", "T")
    assert short == [("T", "One.\n\nTwo.\n\nThree.")]
    long = "\n\n".join(f"Paragraph {i} " + "word " * 80 for i in range(6))
    pieces = sources.split_markdown(long, "T")
    assert len(pieces) >= 4 and all(sources.count_tokens(b) <= sources.MAX_TOKENS for _, b in pieces)
    giant = sources.split_markdown("x" * 5000, "T")
    assert len(giant) > 1


def test_code_fence_headings_are_not_headings():
    pieces = sources.split_markdown("# Real\n\n```\n# not a heading\n```\n", "T")
    assert pieces == [("T › Real", "```\n# not a heading\n```")]


def test_jsonl_source(tmp_path):
    f = tmp_path / "n.jsonl"
    f.write_text(json.dumps({"id": "a", "text": "Atlas ships April 18.", "ts": 100}) + "\n")
    (c,) = sources.load_source(Source("jsonl", f, "n"))
    assert (c.id, c.ts, c.source) == ("a", 100.0, "n:1") and c.tokens > 0


# --- index ---

class CountingEmbedder:
    name = "stub"

    def __init__(self):
        self.embedded: list[str] = []

    def embed_docs(self, texts):
        self.embedded += texts
        rng = np.random.default_rng(len(texts))
        v = rng.normal(size=(len(texts), 8)).astype(np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    def embed_query(self, text):
        return np.ones(8, dtype=np.float32) / np.sqrt(8)


def test_index_only_embeds_what_changed(vault, tmp_path):
    src = (Source("obsidian", vault, "Vault", ("Templates/**",)),)
    emb = CountingEmbedder()
    idx = Index(src, Config(), tmp_path / "idx", emb)
    rt, stats = idx.build()
    assert stats.embedded == stats.blocks == len(rt.blocks) > 0 and not idx.changed()

    _, again = Index(src, Config(), tmp_path / "idx", CountingEmbedder()).build()  # fresh process, warm cache
    assert again.embedded == 0 and again.reused == stats.blocks

    time.sleep(0.01)
    (vault / "New.md").write_text("Gym locker is number 42.\n")
    assert idx.changed()
    before = len(emb.embedded)
    rt, third = idx.build()
    assert third.embedded == 1 and len(emb.embedded) == before + 1 and "Gym locker" in emb.embedded[-1]
    assert [c.block.source for c in rt.search("gym locker", 3)][0] == "Vault/New.md"

    (vault / "New.md").unlink()
    rt, fourth = idx.build()
    assert fourth.blocks == stats.blocks and all("Gym" not in c.text for c in rt.blocks)


def test_empty_index_is_usable(tmp_path):
    rt, stats = Index((), Config(), tmp_path / "idx", CountingEmbedder()).build()
    assert stats.blocks == 0 and rt.search("anything", 5) == []


def test_missing_notes_folder_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        Index((Source("markdown", tmp_path / "nope", "nope"),), Config(), tmp_path / "idx", CountingEmbedder()).build()


# --- outputs ---

def result(action, n=1):
    ctx = [Block(f"c{i}", f"Atlas ships April {18 + i}.", 1_700_000_000.0, 6, "Vault/Atlas.md") for i in range(n)]
    reason = "strong_match" if action == Action.SURFACE else "relevant_context" if action == Action.ATTACH else "gate_no"
    return PipelineResult(AmbientEvent("e", "ask", "when does Atlas ship?", 0.0),
                          Decision(action, reason, ctx if action != Action.SUPPRESS else []), 0.9, "yes")


async def test_outputs_respect_on_and_log_everything(tmp_path):
    seen = tmp_path / "seen.json"
    script = tmp_path / "hook.py"
    script.write_text(f"import sys, pathlib; pathlib.Path({str(seen)!r}).write_text(sys.stdin.read())")
    d = outputs.Dispatcher((Output("context_file", ("surface", "attach")),
                            Output("command", ("surface",), {"run": [sys.executable, str(script)]})))
    await d.emit(result(Action.ATTACH))
    assert json.loads(paths.context_file().read_text())["action"] == "attach" and not seen.exists()  # command is surface-only
    assert oct(paths.context_file().stat().st_mode)[-3:] == "600"
    await d.emit(result(Action.SURFACE, 2))
    got = json.loads(seen.read_text())
    assert got["action"] == "surface" and got["context"][0]["source"] == "Vault/Atlas.md" and len(got["context"]) == 2
    await d.emit(result(Action.SUPPRESS))
    assert json.loads(paths.context_file().read_text())["action"] == "surface"  # suppress never overwrites context
    assert [json.loads(l)["action"] for l in paths.decisions_file().read_text().splitlines()] == ["attach", "surface", "suppress"]


async def test_a_failing_output_does_not_stop_the_others(capsys):
    d = outputs.Dispatcher((Output("command", ("surface",), {"run": ["/nonexistent/program"]}),
                            Output("webhook", ("surface",), {"url": "http://127.0.0.1:9/x", "timeout_s": 0.5}),
                            Output("context_file", ("surface",))))
    reply = await d.emit(result(Action.SURFACE))
    assert reply["action"] == "surface" and paths.context_file().exists()
    logged = json.loads(paths.decisions_file().read_text().splitlines()[-1])
    assert set(logged["output_errors"]) == {"command", "webhook"}
    assert "output command failed" in capsys.readouterr().err


# --- service ---

def test_launchd_plist():
    p = plistlib.loads(service.plist_bytes())
    assert p["Label"] == "ai.vice.agent" and p["ProgramArguments"] == [sys.executable, "-m", "vice_ai", "run"]
    assert p["RunAtLoad"] and p["KeepAlive"] == {"SuccessfulExit": False}
    assert p["StandardErrorPath"].endswith("logs/vice.err.log") and p["EnvironmentVariables"]["VICE_HOME"] == os.environ["VICE_HOME"]
    assert "TYPESAFE" not in json.dumps(p)  # the key is never written into the service file


# --- setup command ---

def run_cli(*argv):
    with pytest.raises(SystemExit) as e:
        cli(list(argv))
    return e.value.code


def test_setup_writes_a_valid_private_config(vault, capsys):
    assert run_cli("setup", "--yes", "--no-key", "--source", str(vault)) == 0
    out = capsys.readouterr().out
    assert "sent to TypeSafe" in out  # the privacy notice is always shown
    cfg = paths.config_file()
    assert oct(cfg.stat().st_mode)[-3:] == "600" and oct(paths.home().stat().st_mode)[-3:] == "700"
    s = settings.load()
    assert s.sources[0].type == "obsidian"
    assert [o.type for o in s.outputs] == ["context_file"]
    # Re-running never clobbers hand edits.
    cfg.write_text(cfg.read_text() + "\n# my edit\n")
    assert run_cli("setup", "--yes", "--no-key") == 0 and "# my edit" in cfg.read_text()


def test_status_before_setup_explains_what_to_do(capsys):
    assert run_cli("status") == 1
    assert "vice setup" in capsys.readouterr().out


async def test_dispatcher_only_limits_outputs_but_always_logs(tmp_path):
    seen = tmp_path / "seen.json"
    script = tmp_path / "hook.py"
    script.write_text(f"import sys, pathlib; pathlib.Path({str(seen)!r}).write_text(sys.stdin.read())")
    d = outputs.Dispatcher((Output("context_file", ("surface",)),
                            Output("command", ("surface",), {"run": [sys.executable, str(script)]})))
    await d.emit(result(Action.SURFACE), only=("context_file",))
    assert paths.context_file().exists() and not seen.exists()
    await d.emit(result(Action.SUPPRESS), only=("context_file",))
    assert [json.loads(l)["action"] for l in paths.decisions_file().read_text().splitlines()] == ["surface", "suppress"]


@pytest.mark.parametrize("trigger", ["ask", "mcp"])
def test_queries_are_not_deduplicated(trigger):
    from vice_ai.pregate import PreGate
    pg = PreGate(Config())
    ev = AmbientEvent("m1", trigger, "when does the Atlas project launch?", 100.0)
    assert pg.check(ev).ok and pg.check(ev).ok


# --- MCP server ---

def _reply(action, reason, n=0):
    return outputs.as_reply(PipelineResult(
        AmbientEvent("e", "mcp", "when does Atlas ship?", 0.0),
        Decision(action, reason, [Block(f"c{i}", f"Atlas ships\n  April {18 + i}.", 1_700_000_000.0, 6, "Vault/Atlas.md")
                                  for i in range(n)]), 0.9, "yes"))


def test_agent_output_is_one_line_per_block_and_nothing_else():
    out = outputs.format_reply(_reply(Action.SURFACE, "strong_match", 2))
    assert out.splitlines() == ["[2023-11-14] Atlas ships April 18.", "[2023-11-14] Atlas ships April 19."]
    assert outputs.format_reply(_reply(Action.SUPPRESS, "gate_no")) == outputs.NO_CONTEXT
    assert outputs.format_reply(_reply(Action.SUPPRESS, "gate_unavailable")) == outputs.UNAVAILABLE


async def test_mcp_server_end_to_end(monkeypatch):
    pytest.importorskip("mcp")
    from mcp import Client
    from vice_ai import mcp_server as M

    class FakePipeline:
        async def handle(self, event):
            assert event.trigger == "mcp"
            return PipelineResult(event, Decision(Action.SURFACE, "strong_match",
                                  [Block("c0", "Atlas ships December 2.", 1_700_000_000.0, 4, "Vault/Atlas.md")]), 0.9, "yes")

    class FakeApp:
        def __init__(self, _settings):
            self.pipeline = FakePipeline()
            self.dispatcher = outputs.Dispatcher((Output("context_file", ("surface", "attach")),))
        async def start(self): pass
        async def resync(self): pass

    monkeypatch.setattr(M, "App", FakeApp)
    monkeypatch.setattr(M.settings_mod, "load", lambda: None)
    async with Client(M.build_server()) as c:
        tools = (await c.list_tools()).tools
        assert [t.name for t in tools] == ["recall"] and "do not retry" in tools[0].description
        res = await c.call_tool("recall", {"query": "when does Atlas ship?"})
        assert res.content[0].text == "[2023-11-14] Atlas ships December 2."
    assert json.loads(paths.decisions_file().read_text().splitlines()[-1])["event"]["trigger"] == "mcp"
