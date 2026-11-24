# Usage

## Terms

| Term | Meaning |
|---|---|
| Source | An Obsidian vault, Markdown folder, JSONL file or other system that vice indexes. |
| Block | A passage from a source, with its date. The unit vice indexes and returns. |
| Trigger | What starts an event: the prompt hook, MCP `recall` or `vice ask`. |

## Commands

| Command | |
|---|---|
| `vice setup` | Write `~/.vice/config.toml` and store the API key. |
| `vice sync` | Index all sources. |
| `vice ask "..."` | Print what an agent receives for the text. `--json` prints the full decision. |
| `vice connect claude-code` | Register the hooks and MCP server with Claude Code. `--remove` undoes it. |
| `vice hook` / `vice guard` | Claude Code hooks, run by Claude Code. See [Integrations](integrations.md#claude-code). |
| `vice run` | Run the service in the foreground. `-v` prints each decision. |
| `vice start` / `vice stop` | Install or remove the launchd service. |
| `vice sources types` / `add` / `remove` | List source types, add or remove a source. See [Sources](sources.md#managing-sources). |
| `vice plugin install` / `list` / `remove` | Manage source type packages. See [Sources](sources.md#installing-a-source-type). |
| `vice status` | Configuration, key, index size, service state, plugins. |
| `vice logs` | Follow the service log. |
| `vice mcp` | MCP server. See [Integrations](integrations.md). |
| `vice key set` / `vice key delete` | Manage the Keychain entry. |

The service keeps the index and embedding model loaded and answers `vice hook` and
`vice ask` over a local socket. Without it, both load them on every call. MCP does not
use the service.

## Event handling

1. Local checks: length, secret detection. Rejected events are not sent.
2. Gate: Jev judges whether the text refers to something specific and depends on a
   detail it does not state.
3. Retrieval: the 20 nearest blocks are judged for relevance, concurrently with the gate.
4. Selection: outdated blocks are down-weighted, the rest packed to the token budget.

| Outcome | Meaning | Default outputs |
|---|---|---|
| `suppress` | No relevant context. | none |
| `attach` | Relevant context. | context file |
| `surface` | Strong match. | context file |

Every event is logged to `~/.vice/decisions.jsonl` with its outcome and reason.

| Reason | Meaning |
|---|---|
| `strong_match`, `relevant_context` | Context found. |
| `gate_no` | The text needs no context. |
| `no_relevant_context` | No block states the needed detail. |
| `unsettled_gate_weak_match` | Gate inconclusive, no strong match. |
| `pregate_*` | Rejected locally (`too_short`, `probable_secret`, ...). |
| `gate_unavailable`, `fanout_unavailable` | TypeSafe timed out or failed. |

## Files

`~/.vice/`, or `$VICE_HOME`:

| Path | Contents |
|---|---|
| `config.toml` | Settings. |
| `context.json` | Latest non-empty decision. |
| `decisions.jsonl` | One line per event. |
| `index/` | Embeddings. Rebuilt by `vice sync`. |
| `models/` | The embedding model (about 90 MB), pinned to one version. Downloaded again if deleted. |
| `logs/` | Service output. |

## Sources

- Markdown is split by heading and paragraph into blocks of about 120 tokens, each
  prefixed with the document title and heading path.
- Block date, in order of precedence: frontmatter `updated`, `modified`, `date`,
  `created`; `YYYY-MM-DD` in the file name; file mtime.
- Obsidian: `[[links]]` are reduced to their text; embeds, `%%comments%%`, `.obsidian/`
  and `.trash/` are skipped.
- The service re-reads changed sources every `resync_s` seconds. `recall` checks on every
  call.
