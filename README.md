# Ambient

Zero-UI ambient memory retrieval. It watches the clipboard, a drop folder and a command
palette, and decides without any window whether an event calls for notes you wrote
earlier, and which ones.

**Jev makes judgments, code makes decisions.** TypeSafe's Jev answers small typed
questions with probabilities. Every threshold, branch and side effect is ordinary code.
No generative model is involved anywhere.

## Status

| Part | State |
|---|---|
| Pipeline, listeners, CLI | Built. 42 tests pass, using a scripted stand-in for Jev. |
| Golden dataset and harness | Built. 1,500 notes, 300 events, split 50/50 into calibration and test. |
| Pre-filter experiment | Run. Results below and in `reports/prefilter.json`. |
| Jev latency, calibration, end-to-end numbers | **Not run.** They need a `TYPESAFE_API_KEY`. |

Until calibration runs, the pipeline uses TypeSafe's documented starting thresholds
(0.7 / 0.3), and nothing is known about Jev's accuracy or latency on this task.

## Pipeline

```
event ─► pre-gate (code) ─┬─► Noul gate ───────────────────────────┐
                          └─► pre-filter ─► speculative fan-out ───┤
                                                                   ▼
            decision (code) ◄─ knapsack ◄─ conflict resolution ◄─ calibrate
```

| Stage | File | What it does |
|---|---|---|
| Pre-gate | `pregate.py` | Length bounds, de-duplication, and secret masking. Credential-like text never leaves the machine. |
| Noul gate | `gate.py` | Two Nouls: does the event name something particular, and does it depend on a detail it does not state? Code combines them and bands the result into yes / no / unsettled. 100 ms budget; a slow or failed gate suppresses. |
| Pre-filter | `retrieve.py` | MiniLM embeddings fused with BM25, exact NumPy search, Top-20. |
| Fan-out | `fanout.py` | One request, sent before the gate answers: a relevance question per candidate, plus a conflict question per similar pair. Cancelled if the gate says no. |
| Calibration | `calibrate.py` | Logistic model over the gate Nouls; isotonic map for relevance. Fitted values live in `config/calibration.json`. |
| Conflict resolution | `conflict.py` | Jev says whether two notes disagree; code knows which is newer. The older note's value halves every 14 days of gap and it is dropped once it falls under the relevance floor. |
| Packing | `pack.py` | Exact 0/1 knapsack over the token budget. |
| Decision | `decide.py` | A truth table mapping gate status and packed context to `SUPPRESS`, `ATTACH` or `SURFACE`. |

All wording sent to Jev is in `questions.py`. All numbers are in `config.py`,
`config/pipeline.toml`, or the fitted `config/calibration.json`.

## Pre-filter results

Calibration split, 90 events that need retrieval, 1,500 notes. Recall is of the notes each
event requires.

| Embedder | Fusion | Recall@12 | Recall@20 | Query embed p95 |
|---|---|---|---|---|
| all-MiniLM-L6-v2 | dense + BM25 | 0.939 | **0.989** | 3.9 ms |
| all-MiniLM-L6-v2 | dense only | 0.928 | 0.972 | 3.9 ms |
| nomic-embed-text-v1.5 | dense + BM25 | 0.922 | 0.983 | 23.1 ms |
| potion-base-8M (static) | dense + BM25 | 0.828 | 0.989 | 0.08 ms |
| bge-small-en-v1.5 | dense + BM25 | 0.867 | 0.917 | 6.7 ms |

Vector stores, 12 nearest of 100,000 vectors: NumPy brute force 3.5 ms p95 and exact;
hnswlib 1.2 ms but 0.82 recall at default settings; LanceDB 56 ms unindexed. `sqlite-vec`
could not be tested: this Python's `sqlite3` is built without extension loading.

Chosen: MiniLM, BM25 fusion, NumPy, K = 20. K = 20 is provisional until fan-out latency
is measured.

## Running it

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[eval]"
cp .env.example .env          # then add TYPESAFE_API_KEY
pytest -q
```

Evaluation, in order:

```bash
python -m ambient.eval.dataset     # regenerate the golden set (seeded)
python -m ambient.eval.prefilter   # local only
python -m ambient.eval.latency     # Jev round-trip times: is the gate under 100 ms?
python -m ambient.eval.calibrate   # fit calibrators and thresholds on the calibration split
python -m ambient.eval.e2e         # held-out test split, live, plus ablations
```

The three Jev scripts send the synthetic golden data only. Together they use on the order
of 3 million input tokens, about $0.15 at $0.042 per million.

The daemon:

```bash
ambient run --notify               # clipboard + ./drop folder + palette socket
ambient palette "when does Atlas ship?"
ambient once "when does Atlas ship?"
```

`ambient run` defaults to the golden notes. Pass `--notes your.jsonl` (one
`{"id", "text", "ts"}` object per line) for real ones. Spans go to `traces/spans.jsonl`.

## What the harness reports

- **Gate:** precision-recall curve, average precision, calibration error, share of events
  left unsettled, and the false-positive intrusion rate.
- **Relevance:** the same for Noul, Score and Choice wordings asked side by side, and for
  one request against one request per candidate.
- **End to end:** intrusion rate, miss rate, context precision and recall against the
  required notes, how often a superseded fact leaks into the context, and p50 / p95 per stage.
- **Ablations:** no conflict resolution, uncalibrated default thresholds, tighter token budgets.

## Known limits

- The golden data is synthetic and templated. Real clipboard traffic will be messier.
- Some labels are debatable: "Priya is the lead on Atlas" is marked irrelevant to "what
  does Priya do here?".
- Golden notes average 14 tokens, so the default 400-token budget never binds. The e2e
  ablations tighten it to exercise the knapsack.
- Listeners are macOS only. The clipboard listener skips entries a password manager
  marks as concealed.
