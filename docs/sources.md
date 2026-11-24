# Sources

A source is anything vice indexes into blocks. Each `[[sources]]` entry in
`~/.vice/config.toml` has a `type`; the type decides which other keys it accepts. Keys
common to all types (`type`, `name`, `guard`) are in [Configuration](configuration.md#sources).

## Built-in types

| Type | Options | Reads |
|---|---|---|
| `markdown` | `path`, `exclude` | Every `.md` file under `path`. |
| `obsidian` | `path`, `exclude` | Same, plus wikilinks, embeds and comments. |
| `jsonl` | `path` | One file, one block per line. |

`path` is required; `~` is expanded. `exclude` is a list of globs relative to `path`.
Hidden directories and files over 2 MB are skipped.

`jsonl` line format, one object per line:

```json
{"text": "Atlas launches December 2.", "ts": 1760918400, "id": "atlas-1", "source": "crm:42"}
```

`text` and `ts` (Unix seconds) are required. `id` and `source` are optional.

## Managing sources

Edit `[[sources]]` with the commands below, or by hand in
[`config.toml`](configuration.md#sources).

```bash
vice sources types
```

Lists the available types, where each comes from (`built-in` or the package that provides
it) and the options each accepts.

```bash
vice sources add obsidian path=~/Notes 'exclude=["Templates/**"]' --name notes
```

`vice sources add <type> [key=value ...] [--name NAME] [--no-guard]`. Each value is parsed
as TOML when it parses (`exclude=["Templates/**"]`), otherwise taken as a string
(`path=~/Notes`). The entry is validated before anything is written, and comments in
`config.toml` are kept. `vice sync`, or the service's next resync, indexes the new source.

```bash
vice sources remove notes
```

Removes the source by name. Its blocks leave the index on the next sync.

### Installing a source type

Types beyond the built-in ones come from Python packages (plugins).

```bash
vice plugin install vice-source-slack
vice sources types
```

`vice plugin install <spec> [<spec>...]` takes pip requirement specs: a PyPI name,
`name==1.2`, a local path or a git URL. It installs into `~/.vice/plugins/py<major>.<minor>/`
and records the specs in `~/.vice/plugins.toml`. This works the same for Homebrew, pip,
pipx and uv installs and survives `brew upgrade`. It prints the source types the package
added; a package that adds none is rejected. Packages vice already provides are not
duplicated. A plugin that needs a different version of one of vice's dependencies is
refused, with the dependency's name.

| Command | |
|---|---|
| `vice plugin list` | Installed packages, versions, the types each adds, and load errors. |
| `vice plugin remove <name>` | Uninstall a package. |
| `vice plugin install --reinstall` | Rebuild everything in `plugins.toml`. Needed after a Python version change. |

After installing or removing a plugin, restart a running service:

```bash
vice stop && vice start
```

Nothing is installed implicitly. Plugin code runs with your privileges inside the service,
which holds the API key and indexes your sources. Install only packages you trust.

## Any other system

For a one-off export, write a JSONL file and add a `jsonl` source. No code, no package.
Re-export when the data changes; vice reindexes on the next resync.

For a source that should stay in sync by itself, or that is more than a file, write an
adapter and [install it as a plugin](#installing-a-source-type).

## Writing a source adapter

An adapter is a Python class that turns one kind of source into blocks. It ships as its own
package and vice finds it by `type`. The contract is in
[`adapters/base.py`](../src/vice_ai/adapters/base.py). A complete, minimal package is in
[`examples/vice-source-text`](../examples/vice-source-text).

### Contract

Subclass `SourceAdapter`. Set two class attributes:

| Attribute | Meaning |
|---|---|
| `type` | The `type` value in `[[sources]]`. |
| `option_keys` | Keys the entry may have besides `type`, `name`, `guard`. Anything else is rejected before `configure()` runs. |

Required methods:

| Method | Must |
|---|---|
| `configure(options)` | Validate and store the options. Raise `SourceConfigError` on bad input. No I/O that can fail transiently. |
| `fingerprint()` | Return a string that changes whenever `load()` would return different blocks. Runs every `resync_s`, so keep it far cheaper than `load()`: stat calls, an ETag, a cursor. |
| `load()` | Return every block the source currently provides. |

Optional methods:

| Method | Default | Meaning |
|---|---|---|
| `default_name()` | `None` | Name used when the entry has none. `None` makes `name` required. |
| `describe()` | `type` | One line shown by `vice status`. |
| `indexes(path, is_dir)` | `False` | See [Read guard](#read-guard). |

`self.name` and `self.guard` are set for you.

### Registering

In the adapter package's `pyproject.toml`:

```toml
[project.entry-points."vice.sources"]
text = "vice_source_text:TextSource"
```

The entry name is the `type`. vice imports the module only when a configured source uses
it. A built-in type wins over a package claiming the same name. Install the package with
`vice plugin install <path-or-name>`, restart the service if it runs, then use the type:

```toml
[[sources]]
type = "text"
path = "~/notes"
```

Declare `vice-ai` as a dependency of the package. Do not pin vice's own dependencies
tightly: `vice plugin install` refuses a plugin that needs a different version of one of
them.

### Blocks

`load()` returns `Block(id, text, ts, tokens, source)`.

- `id`: stable and unique within the source. Use `block_id(self.name, locator, text)`
  where `locator` is where the text lives (a file path, a message id). The same text at
  the same place must always get the same id, since embeddings are cached by id. Do not
  use a counter or a random value.
- `text`: what the agent will read. One self-contained unit, a few hundred tokens at most.
- `ts`: Unix seconds when the content was written or last changed. For files, the mtime.
  vice uses it to prefer newer blocks when two contradict, so a sync time is wrong.
- `tokens`: an estimate of the size of `text`, used for the token budget.
- `source`: where a person can find the original, such as `Vault/Daily/2026-10-20.md` or
  `slack/#launch/1760918400.0012`. Shown to the agent next to the block.

### Errors

- `SourceConfigError`: the entry is wrong and will stay wrong until edited. Raise it from
  `configure()`. vice refuses to start and prints the message.
- `SourceUnavailable`: the source cannot be read right now (folder missing, network down,
  token expired). Raise it from `fingerprint()` or `load()`. vice skips this source,
  logs the message, and keeps serving the others.

Do not return an empty list for a failure. That removes the source's blocks from the
index.

### Read guard

With `guard = true` (the default), vice stops connected agents from reading indexed files
directly, so they use vice instead. For that it asks each adapter whether a path belongs
to it:

```python
def indexes(self, path: Path, is_dir: bool) -> bool: ...
```

`path` is absolute and resolved. Return `True` for a file the source indexes, or, when
`is_dir`, for a directory whose indexed files a search would read. Sources that are not
local files keep the default.

### Testing

Test the class directly: construct it with options, call `configure` through the
constructor, then `load`, `fingerprint` and `indexes`. Check that ids are stable across
two `load()` calls, that `fingerprint()` changes when the data does, and that bad options
raise `SourceConfigError`. To check registration, install the package with
`vice plugin install ./examples/vice-source-text`, then run `vice sources types` and
`vice plugin list`, or call `vice_ai.adapters.build({"type": "...", ...})`.

The example's tests do all of this:

```bash
pip install -e examples/vice-source-text
python -m pytest examples/vice-source-text/tests
```
