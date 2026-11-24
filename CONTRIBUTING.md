# Contributing

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[mcp,eval,dev]"
```

```bash
pytest -q
```

Tests use a scripted Jev stand-in; no API key or network needed.

## Rules

- **Jev judges, code decides.** One judgment per question. Decisions go in `decide.py`.
- **One home for prompts and numbers.** Jev wording in `questions.py`; numbers in
  `config.py` or the calibration file.
- **Failures are not answers.** Timeouts and errors suppress; never treat them as "no".
- **Question or threshold changes need numbers.** Include before/after harness results
  ([Evaluation](docs/evaluation.md)). Tune on the calibration split only.
- **Privacy stays opt-in.** New outbound data must be off by default.
- **Agent output stays minimal.** No new fields or prose in what the hook, `recall` or
  `vice ask` return without a clear need. The hook prints nothing when nothing is
  relevant.

## Open work

- Source types for other tools: write an adapter, see [Sources](docs/sources.md).
- Linux and Windows service management (`service.py`).
- Fitting `~/.vice/calibration.json` from labelled decisions.
- Prompt hooks for other agents.
- Verifying the MCP setup in Claude Desktop and Claude Code.

## Pull requests

Focused, with tests, stating what was and was not verified.
