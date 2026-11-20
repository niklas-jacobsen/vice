# vice - very interesting context engine

vice is a zero-UI ambient memory for your notes that works in the background. When you copy something, drop a file, or ask a question, it
decides whether your own notes hold a detail you need, finds the right note, and drops
any older version of the same fact. If nothing in your notes helps, it does nothing.

```console
$ vice ask "when does Atlas launch?"
• [2026-10-20] Planning call. Atlas launch has slipped: new date is December 2.
    Vault/Daily/2026-10-20.md  ·  2026-10-20
```

The note from June that said September 15 is not shown: vice saw the two disagree and
kept the newer one.

**No generative model decides anything.** TypeSafe's [Jev](https://docs.typesafe.ai)
answers small typed questions with probabilities ("does this note state the detail this
text depends on?"). Every threshold, branch and side effect is ordinary, testable code.

> **Status: alpha, macOS only.** Thresholds are fitted on synthetic data. See
> [Evaluation](docs/evaluation.md) for what has and has not been measured.

## Install

Requires macOS, Python 3.12+, and a [TypeSafe](https://typesafe.ai) API key.

> Not yet published. Until the first release, install from a checkout:
> `pip install -e ".[mcp]"`. The commands below are how it will be installed afterwards.

```bash
pipx install "vice-ai[mcp]"
```

or with Homebrew, from the project tap:

```bash
brew install niklas-jacobsen/tap/vice-ai
```

## Quick start

```bash
vice setup
```

```bash
vice sync
```

```bash
vice ask "who is on call for the billing service?"
```

```bash
vice start
```

`setup` asks for your API key (stored in the macOS Keychain) and a notes folder, and
writes `~/.vice/config.toml`. `sync` indexes your notes; the first run downloads a 90 MB
embedding model. `start` runs vice in the background and at login.

## What you can configure

| | Options |
|---|---|
| **Notes** | Obsidian vaults, Markdown folders, JSONL files. Any number of each. |
| **Event sources** | Clipboard, drop folders, typed questions. Each can be switched off. |
| **Outputs** | A context file, macOS notifications, a command of your choice, a webhook. |
| **Assistants** | An MCP server for Claude Desktop, Claude Code, and other MCP clients. |

## Documentation

- [Usage](docs/usage.md): setup, commands, what the outcomes mean
- [Configuration](docs/configuration.md): notes, sources, outputs, tunables
- [Integrations](docs/integrations.md): Claude Desktop and Claude Code via MCP, scripts, webhooks
- [Privacy](docs/privacy.md): exactly what leaves your machine
- [Troubleshooting](docs/troubleshooting.md)
- [Evaluation](docs/evaluation.md): architecture, measured results, how to recalibrate
- [Releasing](docs/releasing.md) and [Contributing](CONTRIBUTING.md)

## Privacy in one paragraph

Your notes are indexed locally. When an event passes local checks, its text and about 20
candidate note excerpts are sent to TypeSafe's API to be judged. Text that looks like a
credential is stripped first, password-manager clipboard entries are never read, and
clipboard watching is off unless you turn it on. Details in [Privacy](docs/privacy.md).

## Licence

MIT. See [LICENSE](LICENSE).
