# Changelog

## 0.1.0 (unreleased)

First version.

- Pipeline: local pre-gate with secret redaction, a two-question Jev gate, hybrid local
  retrieval, speculative fan-out, calibrated relevance, temporal conflict resolution,
  knapsack packing, and a truth-table decision.
- Note sources: Obsidian vaults, Markdown folders, JSONL files, with a persistent index
  that only re-embeds changed text.
- Event sources: clipboard, drop folders, and `vice ask`, each configurable.
- Outputs: context file, macOS notification, command, webhook.
- MCP server (`vice mcp`) with `recall` and `latest_context` tools.
- `vice setup`, `sync`, `ask`, `run`, `start`, `stop`, `status`, `logs`, `key`.
- API key stored in the macOS Keychain.
- Evaluation harness, golden dataset, and thresholds calibrated against `jev-1.14.0`.

Known limits: macOS only; thresholds fitted on synthetic data; see docs/evaluation.md.
