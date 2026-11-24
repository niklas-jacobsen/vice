# Configuration

`~/.vice/config.toml`. Unknown keys are an error. Validate with `vice status`; apply to
a running service with `vice start`.

## Sources

`vice sources add` and `vice sources remove` are the normal way to edit `[[sources]]`; see
[Sources](sources.md#managing-sources). They validate the entry and keep comments. The
file can still be edited by hand.

```toml
[[sources]]
type = "obsidian"
path = "~/Documents/Vault"
exclude = ["Templates/**", "Archive/**"]

[[sources]]
type = "markdown"
path = "~/work/meeting-notes"
name = "meetings"

[[sources]]
type = "jsonl"
path = "~/exports/crm-notes.jsonl"
```

| Key | Required | Meaning |
|---|---|---|
| `type` | yes | `obsidian`, `markdown`, `jsonl`, or a type added by an installed package. |
| `path` | yes | Folder (or file, for `jsonl`). `~` is expanded. |
| `name` | no | Unique label. Defaults to the folder name. |
| `exclude` | no | Glob patterns relative to `path`. |
| `guard` | no | Default `true`: connected agents may not read indexed files directly. See [Integrations](integrations.md#read-guard). |

`markdown` reads every `.md` file under `path`. `obsidian` also handles wikilinks,
embeds and comments. Hidden directories and files over 2 MB are skipped.

`jsonl`: one object per line with `text` and `ts` (Unix seconds); `id` and `source`
optional.

Other source types come from installed packages (`vice plugin install`). See
[Sources](sources.md#installing-a-source-type).

## Outputs

`on` lists the outcomes an output fires for: `"surface"`, `"attach"`. Output errors are
logged to `decisions.jsonl` and do not affect other outputs. MCP `recall` fires
`context_file` only.

```toml
[outputs.context_file]
enabled = true
on = ["surface", "attach"]
# path = "~/.vice/context.json"

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
| `context_file` | Overwrites a JSON file with the latest decision. |
| `command` | Runs `run` (argv list, no shell) with the decision JSON on stdin. |
| `webhook` | POSTs the decision JSON. |

Decision schema:

```json
{
  "action": "surface",
  "reason": "strong_match",
  "event": {"trigger": "ask", "text": "when does Atlas launch?"},
  "gate": {"status": "yes", "p": 0.99},
  "context": [
    {"id": "6c86cdb2dbc4b879", "text": "Atlas launches December 2.",
     "source": "Vault/Daily/2026-10-20.md", "written": "2026-10-20"}
  ],
  "ms": {"gate": 162.3, "fanout": 210.0, "total": 214.5},
  "at": "2026-11-13T15:53:50Z"
}
```


## Other top-level keys

| Key | Default | Meaning |
|---|---|---|
| `resync_s` | `120` | Seconds between checks for changed sources. |
| `tracing` | `false` | Write OpenTelemetry spans to `~/.vice/traces/spans.jsonl`. |

## Pipeline tunables

Under `[pipeline]`.

| Key | Default | Meaning |
|---|---|---|
| `token_budget` | `400` | Maximum context size, in tokens. |
| `top_k` | `20` | Candidate blocks sent to Jev per event. |
| `gate_timeout_ms` | `300` | Gate timeout. A timeout suppresses. |
| `conflict_half_life_days` | `14` | Half-life, in days of age difference, of the weight kept by the older of two contradicting blocks. |
| `min_chars` / `max_chars` | `8` / `2000` | Shorter events are dropped; longer are truncated. |
| `model` | `jev-1.14.0` | Pinned Jev version. Requires matching calibration. |

Thresholds (`gate_yes`, `gate_no`, `relevance_min`, `surface_min`, `conflict_min`) come
from the calibration file, overridable with `~/.vice/calibration.json`. See
[Evaluation](evaluation.md#recalibrating).

## Environment variables

| Variable | Meaning |
|---|---|
| `TYPESAFE_API_KEY` | Overrides the Keychain. Not visible to the launchd service. |
| `VICE_HOME` | State directory. Default `~/.vice`. |
| `VICE_SOCKET` | Service socket path. Default `~/.vice/vice.sock`. |
