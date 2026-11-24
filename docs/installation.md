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

### Homebrew

```bash
brew install niklas-jacobsen/tap/vice-ai
```

Then run `vice setup` as below. Start the service with either `vice start` or
`brew services start vice-ai`, not both.

Source plugins installed with `vice plugin install` live in `~/.vice/plugins`, outside the
Homebrew folder, and survive `brew upgrade`. See [Sources](sources.md#installing-a-source-type).

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

Plugins live in `~/.vice/plugins`. `vice plugin remove <name>` removes one; the command
below deletes all of them with the rest of the state.

```bash
rm -rf ~/.vice
```

```bash
pip uninstall vice-ai
```

For Homebrew, `brew uninstall vice-ai`.
