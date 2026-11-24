# Integrations

## Claude Code

```bash
vice connect claude-code
```

Adds to `~/.claude/settings.json` (previous version kept as `settings.json.vice-backup`)
and registers the MCP server at user scope:

| Entry | Command | Effect |
|---|---|---|
| `UserPromptSubmit` hook | `vice hook` | Relevant blocks are added to the prompt. |
| `PreToolUse` hook, `Read\|Grep\|Glob\|Bash` | `vice guard` | Reads of files vice indexes are refused. |
| MCP server | `vice mcp` | `recall` for lookups mid-task. |

Re-running replaces vice's entries; `vice connect claude-code --remove` deletes them.
Other hooks are not touched. Restart Claude Code sessions afterwards.

### Prompt hook

Adds relevant blocks to the agent's context before it processes the prompt. Answers come
from the service (`vice start`), about 0.3 s per prompt. Without the service, or when
nothing is relevant or vice fails, it adds nothing and never blocks the prompt. The agent
receives:

```text
Relevant information from the user's sources (vice):
[2026-10-20] Atlas launches December 2.
```

Hook events have trigger `hook`, are logged to `decisions.jsonl` and update
`context.json`. Other outputs do not fire.

### Read guard

Refuses `Read`, `Grep`, `Glob` and `Bash` calls on files vice indexes, and tells the agent
to use `recall` instead. Everything else stays readable: paths outside the sources,
excluded paths, non-Markdown files, and sources with `guard = false`
([Configuration](configuration.md#sources)).

- `Grep` and `Glob` are refused when they search a directory inside a source; searching a
  parent of a source is allowed.
- `Bash` is refused when an argument names an indexed file or a directory inside a source.
  A command that reads a source without naming it is not caught.
- Claude Code requires a `Read` before an `Edit`, so guarded notes cannot be edited by the
  agent. Set `guard = false` on sources the agent should edit.
- On any error the guard allows the call. It adds about 70 ms per guarded tool call.

## MCP

For lookups mid-task, and for clients without prompt hooks.

`vice mcp` is a stdio [MCP](https://modelcontextprotocol.io) server. Requires the `mcp`
extra and an index (`vice sync`). The background service is not required.

One tool, `recall(query)`. It returns one line per block, `[YYYY-MM-DD] text`, or
`No relevant information.`:

```text
[2026-10-20] Atlas launches December 2.
[2026-11-03] Atlas messaging: lead with offline sync; pricing is unchanged.
```

`recall` events have trigger `mcp`, are logged to `decisions.jsonl` and update
`context.json`. Other outputs do not fire.

### Claude Code

```bash
claude mcp add vice -- vice mcp
```

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`, with the path from
`which vice`:

```json
{
  "mcpServers": {
    "vice": {
      "command": "/Users/you/.local/bin/vice",
      "args": ["mcp"]
    }
  }
}
```

macOS may prompt once for Keychain access.

### Other clients

Command `vice`, argument `mcp`. Local stdio clients only.

Tested with the `mcp` 1.x and 2.x reference clients. Not yet tested in Claude Desktop or
Claude Code.

## Command output

Runs a program per matching event with the decision JSON on stdin. Schema:
[Configuration](configuration.md#outputs).

```toml
[outputs.command]
enabled = true
on = ["surface", "attach"]
run = ["/Users/you/bin/vice-hook"]
```

## Webhook output

POSTs the decision JSON.

```toml
[outputs.webhook]
enabled = true
on = ["surface"]
url = "http://127.0.0.1:8787/vice"
```

## Scripts

`vice ask "..."` prints the same blocks as `recall`; `vice ask --json` prints the full
decision. With the service running (`vice start`), answers come from the already loaded
index.
