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

## Any other system

For a one-off export, write a JSONL file and add a `jsonl` source. No code, no package.
Re-export when the data changes; vice reindexes on the next resync.

For a source that should stay in sync by itself, or that is more than a file, write an
adapter.

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
it. A built-in type wins over a package claiming the same name. Install the package into
the environment vice runs in, then use it:

```toml
[[sources]]
type = "text"
path = "~/notes"
```

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
raise `SourceConfigError`. To check registration, install the package and call
`vice_ai.adapters.build({"type": "...", ...})`.

The example's tests do all of this:

```bash
pip install -e examples/vice-source-text
python -m pytest examples/vice-source-text/tests
```
