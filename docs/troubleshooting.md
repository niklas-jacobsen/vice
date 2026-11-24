# Troubleshooting

```bash
vice status
```

```bash
tail -n 5 ~/.vice/decisions.jsonl
```

## "no configuration … Run `vice setup` first"

Run `vice setup`.

## "unknown key(s) … in [section]"

The message lists the allowed keys. See [Configuration](configuration.md).

## "no TypeSafe API key found"

Run `vice key set`. The launchd service does not see `TYPESAFE_API_KEY` from your shell.

## "cannot reach TypeSafe"

Check the network and key. If the pinned Jev model has been retired, upgrade vice.

## No relevant information

`vice ask --json "..."` shows the `reason`:

| Reason | Fix |
|---|---|
| `gate_no` | The text names nothing specific; expected for general prompts. |
| `no_relevant_context` | Check the file is in a source and not excluded, then `vice sync`. |
| `gate_unavailable`, `fanout_unavailable` | TypeSafe did not answer in time. Retry, or raise `gate_timeout_ms`. |

## An outdated fact is returned

Recency comes from the document date. A recently edited old file without a frontmatter
or file-name date takes its mtime; add `date: YYYY-MM-DD`. Contradictions worded very
differently can also go undetected (6.8% on the test set).

## A new file is not found

The service re-reads sources every `resync_s` seconds. `vice sync` indexes immediately.

## The service does not start

```bash
vice logs
```

Usually a missing key, invalid `config.toml` or missing source folder.

## The agent cannot read or edit a note

The read guard refuses files vice indexes. Set `guard = false` on that source, or
exclude the path. See [Integrations](integrations.md#read-guard).

## Rebuild the index

```bash
rm -rf ~/.vice/index
```

```bash
vice sync
```

## Reporting a problem

Include `vice status` and the relevant `decisions.jsonl` line. That line contains event
and block text; redact before posting.
