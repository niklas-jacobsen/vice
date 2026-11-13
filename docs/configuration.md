# Configuration

Settings live in `~/.vice/config.toml`. Unknown keys are rejected with a message naming
the key, so a typo never silently does nothing. Check a change with `vice status`, and
restart the service (`vice start`) for it to take effect.

## Notes

One `[[notes]]` block per source.

```toml
[[notes]]
type = "obsidian"
path = "~/Documents/Vault"
exclude = ["Templates/**", "Archive/**"]

[[notes]]
type = "markdown"
path = "~/work/meeting-notes"
name = "meetings"

[[notes]]
type = "jsonl"
path = "~/exports/crm-notes.jsonl"
```

| Key | Required | Meaning |
|---|---|---|
| `type` | yes | `obsidian`, `markdown`, or `jsonl`. |
| `path` | yes | Folder (or file, for `jsonl`). `~` is expanded. |
| `name` | no | Label shown in results. Defaults to the folder name; must be unique. |
| `exclude` | no | Glob patterns relative to `path`. |

`markdown` reads every `.md` file under the folder. `obsidian` does the same and also
understands wikilinks, embeds and comments, and skips `.obsidian/` and `.trash/`. Hidden
folders are always skipped, as are files over 2 MB.

`jsonl` is the escape hatch for anything else: one JSON object per line with `text` and
`ts` (when it was written, as Unix seconds), and optionally `id` and `source`. Export
from any tool into this shape and vice can use it.

## Event sources

```toml
[sources.clipboard]
enabled = false

[sources.file_drop]
enabled = true
folders = ["~/vice-drop", "~/Downloads/inbox"]

[sources.palette]
enabled = true
```

| Source | Fires when | Notes |
|---|---|---|
| `clipboard` | You copy text. | Off by default. Entries a password manager marks as concealed are never read. |
| `file_drop` | A file appears in one of `folders`. | Text files: the name and first 1,200 characters. Other files: the name only. |
| `palette` | You run `vice ask`. | Also what the MCP server uses. Disabling it stops `vice ask` reaching the service. |

## Outputs

Each output has `enabled` and `on`, the list of outcomes it reacts to (`"surface"`,
`"attach"`, or both). Outputs are independent: if one fails, the others still run and the
error is recorded in `decisions.jsonl`.

```toml
[outputs.context_file]
enabled = true
on = ["surface", "attach"]
# path = "~/.vice/context.json"

[outputs.notification]
enabled = true
on = ["surface"]

[outputs.command]
enabled = true
on = ["surface", "attach"]
run = ["/Users/me/bin/on-vice-context"]
# timeout_s = 10

[outputs.webhook]
enabled = true
on = ["surface"]
url = "http://127.0.0.1:8787/vice"
# timeout_s = 5
```

| Output | What it does |
|---|---|
| `context_file` | Overwrites one JSON file with the latest context. |
| `notification` | A macOS notification with the first note and its source. |
| `command` | Runs your program with the decision as JSON on stdin. `run` is a list: program, then arguments. No shell is involved. |
| `webhook` | POSTs the decision as JSON. |

The JSON every output receives:

```json
{
  "action": "surface",
  "reason": "strong_match",
  "event": {"source": "clipboard", "text": "when does Atlas launch?"},
  "gate": {"status": "yes", "p": 0.99},
  "context": [
    {"id": "6c86cdb2dbc4b879", "text": "[2026-10-20] Atlas launch has slipped: new date is December 2.",
     "source": "Vault/Daily/2026-10-20.md", "written": "2026-10-20"}
  ],
  "ms": {"gate": 162.3, "fanout": 210.0, "total": 214.5},
  "at": "2026-11-13T15:53:50Z"
}
```

A webhook sends your note excerpts wherever the URL points. Keep it on `127.0.0.1` unless
you mean to send them elsewhere.

## Other top-level keys

| Key | Default | Meaning |
|---|---|---|
| `resync_s` | `120` | Seconds between checks for changed notes. |
| `tracing` | `false` | Write OpenTelemetry spans to `~/.vice/traces/spans.jsonl`. |

## Pipeline tunables

Optional, under `[pipeline]`. The defaults were chosen by measurement; see
[Evaluation](evaluation.md).

| Key | Default | Meaning |
|---|---|---|
| `token_budget` | `400` | Maximum size of the context vice returns, in tokens. |
| `top_k` | `20` | Candidate notes sent to Jev per event. |
| `gate_timeout_ms` | `300` | How long to wait for the gate before staying silent. |
| `conflict_half_life_days` | `14` | How quickly a contradicted older note loses out. Lower retires old facts faster. |
| `min_chars` / `max_chars` | `8` / `2000` | Events shorter are ignored; longer are truncated. |
| `dedupe_window_s` | `60` | Ignore an identical copy or drop within this many seconds. |
| `model` | `jev-1.14.0` | Pinned Jev version. Changing it requires recalibrating. |

Thresholds (`gate_yes`, `gate_no`, `relevance_min`, `surface_min`, `conflict_min`) come
from calibration, not from this file. To change them, put your own
`~/.vice/calibration.json` in place; see [Evaluation](evaluation.md#recalibrating).

## Environment variables

| Variable | Meaning |
|---|---|
| `TYPESAFE_API_KEY` | Overrides the Keychain. The background service does not see your shell's environment, so prefer `vice key set`. |
| `VICE_HOME` | Use a folder other than `~/.vice`. |
| `VICE_SOCKET` | Path of the socket `vice ask` uses. Needed only if your home path is very long. |
