# Privacy

vice reads private material: your notes, and optionally your clipboard. This page says
exactly what happens to it.

## What stays on your machine

- **Your notes and their embeddings.** Indexing and similarity search run locally. The
  embedding model is downloaded once from Hugging Face (a fixed version, into
  `~/.vice/models`) and then runs offline. That download sends nothing about you or your
  notes.
- **Your configuration, the decision log, and the context file.** All under `~/.vice/`,
  which is readable only by your user.
- **Your API key.** In the macOS Keychain. It is never written to a config file, a log,
  or the background service's definition.

## What is sent to TypeSafe

When an event passes the local checks, vice sends two requests to `api.typesafe.ai`:

1. **The event text** (up to 2,000 characters), with two yes/no questions about it.
2. **The event text again, with about 20 note excerpts**: the chunks most similar to the
   event, each roughly a paragraph, each with its note title and heading.

The second request is sent before the first has answered, to save time. So candidate
excerpts are sent for every event that passes the local checks, including events that
turn out not to need your notes. If that is not acceptable for your notes, do not enable
clipboard watching, and use only `vice ask`.

What TypeSafe does with requests is governed by their terms, not by vice. Read them
before pointing vice at sensitive material.

## What is never sent

- Events stopped by a local check: under 8 characters, a bare number or colour code, a
  duplicate, or a single long random-looking token.
- Text matching credential patterns. These are replaced with `[REDACTED]` before sending:
  private key blocks, AWS access keys, common API key and token formats (`sk-`, `ghp_`,
  `xox…`), JSON Web Tokens, `password: …` style assignments, and card numbers that pass
  a checksum.
- Clipboard entries marked as concealed or transient by a password manager.
- The contents of dropped files that are not plain text. Only the file name is used.

Redaction is pattern matching. It will miss secrets in formats it does not know, and it
does **not** apply to your notes: if a note contains a password, that note can be sent as
a candidate excerpt. Use `exclude` to keep such folders out of the index.

## Other places your data can go

Only where you send it:

- `outputs.webhook` POSTs note excerpts to the URL you configure.
- `outputs.command` hands them to the program you configure.
- The MCP server returns them to the assistant that asks, which then processes them
  under that assistant's own terms.

## Defaults

- Clipboard watching: **off**.
- Drop folder: **off**.
- Outputs: a local file, and a local notification.
- Tracing: **off**. When on, spans record timings and decisions, not note text.

## Removing everything

```bash
vice stop
```

```bash
vice key delete
```

```bash
rm -rf ~/.vice
```
