# Privacy

## Local

- Sources, embeddings and search. The embedding model is downloaded once from Hugging Face (a fixed version, into
  `~/.vice/models`), which sends nothing about you or your sources, then runs offline.
- `~/.vice/` (configuration, decision log, context file), mode `0700`.
- The API key, in the Keychain. Never written to a file or the service definition.

## Sent to TypeSafe

Per prompt (with the hook installed), `recall` or `vice ask` that passes local checks,
two concurrent requests to `api.typesafe.ai`:

1. The query text, up to 2,000 characters.
2. The query text and about 20 candidate blocks, each with its document title and heading.

Blocks are sent even for queries the gate rejects. With the hook, this is every prompt
you send the agent.

TypeSafe's handling of request data is governed by its
[privacy policy](https://typesafe.ai/legal/privacy-policy) and
[DPA](https://typesafe.ai/legal/data-processing).

## Not sent

- Queries rejected locally: under 8 characters, bare numbers or colour codes, single
  high-entropy tokens.
- Credential patterns in query text, replaced with `[REDACTED]`: private keys, AWS keys,
  `sk-`/`ghp_`/`xox…` tokens, JWTs, `password: …` assignments, Luhn-valid card numbers.

Redaction applies to query text, not to sources. Keep sensitive folders out with
`exclude`.

## Other destinations

- `command` and `webhook` outputs receive blocks.
- The hook, MCP `recall` and `vice ask` return blocks to the caller.

## Defaults

Outputs: context file. Tracing off; spans contain timings and decisions, not text.
