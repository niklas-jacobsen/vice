# Usage

## First-time setup

```bash
vice setup
```

Setup shows what vice sends where, then asks for:

1. **Your TypeSafe API key.** Input is hidden and the key goes into the macOS Keychain. It
   is never written to a file.
2. **Notes folders.** An Obsidian vault is detected automatically; any other folder is
   treated as plain Markdown. Enter as many as you like, blank to finish.
3. **Whether to watch the clipboard.** Off by default.
4. **Whether to watch a drop folder** (`~/vice-drop` by default).
5. **Whether to notify you** on a strong match.

The answers are written to `~/.vice/config.toml`, which you can edit by hand afterwards.
Running `vice setup` again keeps your existing file; `--force` rewrites it.

Without prompts:

```bash
vice setup --yes --notes ~/Documents/Vault --no-clipboard --drop-folder ~/vice-drop
```

Then index your notes:

```bash
vice sync
```

The first sync downloads the embedding model (about 90 MB, from Hugging Face, into
`~/.vice/models`) and embeds every note. Later
syncs only embed text that changed.

## Commands

| Command | What it does |
|---|---|
| `vice setup` | First-time configuration. |
| `vice sync` | Index your notes now. |
| `vice ask "..."` | Ask a question against your notes. `--json` prints the full decision. |
| `vice run` | Run in the foreground. `-v` prints each decision. Stop with Ctrl-C. |
| `vice start` | Run in the background, now and at every login. |
| `vice stop` | Stop the background service and remove its login item. |
| `vice status` | Show configuration, key, index size, and whether the service runs. |
| `vice logs` | Follow the background service's log. |
| `vice mcp` | MCP server for assistants. See [Integrations](integrations.md). |
| `vice key set` / `vice key delete` | Store or remove the API key. |

`vice ask` uses the running service if there is one, and otherwise answers directly.

## What vice does with an event

An event is something you copied, a file you dropped, or a question you typed. For each:

1. **Local checks.** Too short, a duplicate, a bare number, or something that looks like a
   password: dropped, nothing is sent anywhere.
2. **Does it need your notes?** Jev judges whether the text names something particular and
   depends on a detail it does not state. "Thanks Priya, that works!" does not.
3. **Which notes?** The 20 most similar note chunks are found locally, and Jev judges each
   one for whether it states the needed detail.
4. **Which version?** If two relevant notes give different values for the same fact, the
   newer one wins.
5. **Decision.** One of three outcomes.

| Outcome | Meaning | Default outputs |
|---|---|---|
| `suppress` | Nothing useful, or not confident enough. Nothing happens. | none |
| `attach` | Relevant notes found. Made available quietly. | context file |
| `surface` | A strong match. | context file, notification |

Every event, including suppressed ones, is appended to `~/.vice/decisions.jsonl` with the
reason. That file is the place to look when vice did something you did not expect.

### Reasons you may see

| Reason | Meaning |
|---|---|
| `strong_match`, `relevant_context` | Notes were found. |
| `gate_no` | The text did not look like it needed your notes. |
| `no_relevant_context` | It did, but no note states the needed detail. |
| `unsettled_gate_weak_match` | Unclear whether it needed notes, and no strong match. |
| `pregate_*` | Stopped by a local check (`too_short`, `duplicate`, `probable_secret`, ...). |
| `gate_unavailable`, `fanout_unavailable` | TypeSafe did not answer in time. vice stays silent rather than guess. |

## Where things live

Everything is under `~/.vice/` (set `VICE_HOME` to move it):

| Path | Contents |
|---|---|
| `config.toml` | Your settings. |
| `context.json` | The latest context vice produced. |
| `decisions.jsonl` | One line per event handled. |
| `index/` | Embedded notes. Safe to delete; `vice sync` rebuilds it. |
| `models/` | The embedding model (about 90 MB), pinned to one version. Safe to delete; it is downloaded again when needed. |
| `logs/` | Background service output. |

## How notes are read

- Markdown files are split by heading and paragraph into chunks of roughly 120 tokens.
  Each chunk is prefixed with its note title and heading path.
- **Dates decide which fact is current**, so vice works out when each note was written,
  in this order: frontmatter `updated`, `modified`, `date` or `created`; a `YYYY-MM-DD`
  in the file name (daily notes); the file's modification time.
- In Obsidian vaults, `[[links]]` are reduced to their text, and embeds, `%%comments%%`,
  `.obsidian/` and `.trash/` are skipped.
- Notes are re-read every two minutes while the service runs.

## Uninstall

```bash
vice stop
```

```bash
vice key delete
```

```bash
rm -rf ~/.vice
```

Then remove the package with `pipx uninstall vice-ai` or `brew uninstall vice-ai`.
