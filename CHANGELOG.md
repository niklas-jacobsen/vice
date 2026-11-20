# Changelog

## 0.1.1

- Runs the MiniLM embedding model directly with `onnxruntime` and `tokenizers` instead of
  through `fastembed`. The vectors are the same, so existing indexes and the shipped
  calibration stay valid. This removes `py_rust_stemmers`, whose prebuilt library made
  `brew install` end with a `HeaderPadError` while relinking.
- The model is now downloaded to `~/.vice/models` (pinned revision) rather than a
  temporary folder, so it is not fetched again after macOS clears temporary files.
- Counts note tokens with the MiniLM tokenizer instead of `tiktoken`, whose prebuilt
  library has the same Homebrew problem. Counts agree within about 2%, and chunk limits
  are now in the same units as the model's 256-token window. Some chunk boundaries may
  move, so the first `vice sync` after upgrading re-embeds the affected notes.
- `fastembed` and `tiktoken` move to the `eval` extra; they are only needed to compare
  other embedders and to regenerate the test dataset.

## 0.1.0

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
