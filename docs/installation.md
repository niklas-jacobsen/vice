# Installation

## Requirements

- macOS
- Python 3.12+
- A [TypeSafe](https://typesafe.ai) API key

## Install

From a checkout:

```bash
pip install -e ".[mcp]"
```

## Setup

```bash
vice setup
```

Prompts for the API key (stored in the Keychain) and sources, then writes
`~/.vice/config.toml`. An existing file is kept unless `--force` is given.

Non-interactive:

```bash
vice setup --yes --source ~/Documents/Vault
```

Build the index. The first run downloads a 90 MB embedding model.

```bash
vice sync
```

Run the background service, which keeps the index loaded and starts at login:

```bash
vice start
```

Connect Claude Code (prompt hook, read guard and MCP server; see
[Integrations](integrations.md#claude-code)):

```bash
vice connect claude-code
```

Other clients: [Integrations](integrations.md).

## Uninstall

```bash
vice connect claude-code --remove
```

```bash
vice stop
```

```bash
vice key delete
```

```bash
rm -rf ~/.vice
```

```bash
pip uninstall vice-ai
```
