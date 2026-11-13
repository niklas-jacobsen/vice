# Integrations

vice has no interface of its own. These are the ways to get its context into the tools
you already use.

## Assistants, through MCP

`vice mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server. An
assistant that supports MCP can call it to look things up in your notes. It offers two
tools:

| Tool | What the assistant gets |
|---|---|
| `recall(query)` | Notes vice judges relevant to the query, with superseded versions removed. Empty when nothing on file answers it. |
| `latest_context()` | The context vice most recently produced from your clipboard, a dropped file, or a question. |

The server needs the `mcp` extra, which `pipx install "vice-ai[mcp]"` and the Homebrew
formula both include. Run `vice setup` and `vice sync` first. The background service does
not need to be running for `recall` to work.

Find the full path to vice, which the configurations below need:

```bash
which vice
```

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` and add vice under
`mcpServers`, using the path from `which vice`:

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

Restart Claude Desktop. The first call may show a macOS prompt asking to let Python read
the `vice-ai` Keychain item; allow it.

### Claude Code

```bash
claude mcp add vice -- vice mcp
```

### Other MCP clients

Any client that can launch a local stdio server works the same way: command `vice`,
argument `mcp`.

### What has been tested

The server has been exercised end to end with the reference MCP client library, against
both the 1.x and 2.x lines of the `mcp` package. It has **not** yet been tried inside
Claude Desktop or Claude Code themselves. If the configuration above needs adjusting for
your version, please open an issue.

### ChatGPT and web apps

vice only offers a local server. Assistants that accept only remote, hosted MCP servers,
and any assistant used in a browser tab, cannot reach it. For those, the practical route
today is the command output below: have vice put the context somewhere you can paste from.

## Your own scripts: the command output

vice runs a program of your choice on each match, with the decision as JSON on stdin.

```toml
[outputs.command]
enabled = true
on = ["surface", "attach"]
run = ["/Users/you/bin/vice-hook"]
```

Example: append every match to a running Markdown file.

```bash
#!/bin/sh
# /Users/you/bin/vice-hook
python3 -c '
import json, sys
d = json.load(sys.stdin)
with open("/Users/you/vice-inbox.md", "a") as f:
    f.write("\n## " + d["event"]["text"][:80] + "\n")
    for c in d["context"]:
        f.write("- " + c["text"] + "  (" + c["source"] + ")\n")
'
```

Example: put the context on the clipboard so it can be pasted into any chat window.

```bash
#!/bin/sh
python3 -c 'import json,sys; print("\n".join(c["text"] for c in json.load(sys.stdin)["context"]))' | pbcopy
```

If you use that one with clipboard watching on, vice will see its own output as a new
copy and judge it like any other. Statements of fact are normally judged as not needing
your notes, so nothing further happens, but it costs one extra request each time.

## Local services: the webhook output

```toml
[outputs.webhook]
enabled = true
on = ["surface"]
url = "http://127.0.0.1:8787/vice"
```

vice POSTs the same JSON. Use this to feed a menu-bar app, a launcher extension, or a
home-automation flow.

## Polling: the context file

`~/.vice/context.json` always holds the latest context. Anything that can read a file can
use it; nothing needs to be running besides vice.

## Launchers

Bind a hotkey in Raycast, Alfred, or Shortcuts to:

```bash
vice ask "{query}"
```

Add `--json` if the launcher wants structured output.
