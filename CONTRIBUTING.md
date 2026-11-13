# Contributing

Thanks for looking. vice is small and young; issues and pull requests are welcome.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[mcp,eval,dev]"
```

```bash
pytest -q
```

The tests need no API key and make no network calls to TypeSafe. They use a scripted
stand-in for Jev, so they check the code paths, not Jev's accuracy.

## Ground rules

- **Jev makes judgments, code makes decisions.** A question to Jev asks for one thing a
  person could judge at a glance. If a change asks Jev what the system should *do*, break
  it into the judgments that decision depends on and write the decision in `decide.py`.
- **All wording sent to Jev lives in `questions.py`**, and all numbers in `config.py` or
  the calibration file. Please keep it that way; it is what makes the system auditable.
- **A failed call is never an answer.** Timeouts and errors get their own outcome and
  vice stays silent. Do not turn a failure into a "no".
- **Changes to questions or thresholds need numbers.** Run the harness in
  [docs/evaluation.md](docs/evaluation.md) and include before and after results. Tune on
  the calibration split only; the test split is for reporting.
- **Privacy defaults stay conservative.** Nothing new is sent off the machine, and no
  source is switched on, without the user choosing it.

## Good first contributions

- A note source for another tool (see `notes.py`; a source turns files into `Chunk`s).
- Linux or Windows listeners (`listeners.py`) and service management (`service.py`).
- A command that fits `~/.vice/calibration.json` from a user's own labelled decisions.
- Trying the MCP server in Claude Desktop and Claude Code and correcting
  [docs/integrations.md](docs/integrations.md) where it is wrong.

## Pull requests

Keep them focused, add or update tests, and say plainly what you verified and what you
did not.
