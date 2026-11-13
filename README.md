# Ambient

Zero-UI ambient memory retrieval. It watches the clipboard, a drop folder and a command
palette, and decides without any window whether an event calls for notes you wrote
earlier, and which ones.

**Jev makes judgments, code makes decisions.** TypeSafe's Jev answers small typed
questions with probabilities. Every threshold, branch and side effect is ordinary code.
No generative model is involved anywhere.

## Status

Built, calibrated against `jev-1.14.0`, and evaluated on a held-out split. 42 tests pass.
All numbers below are on synthetic data (see "Known limits").

## Results

Held-out test split: 150 events (90 need retrieval, 60 do not), 1,500 notes, live calls to Jev.

| Measure | Result |
|---|---|
| Intrusion rate (acted when nothing was warranted) | 0 of 60 |
| Miss rate (stayed silent when context was needed) | 2 of 90 (2.2%) |
| Context precision / recall against required notes | 0.896 / 0.906 |
| Context exactly right | 77.8% |
| A superseded fact shown alongside or instead of the current one | 6.8% |
| End-to-end latency | 210 ms p50, 404 ms p95 |
| Jev input tokens per event | about 4,500 (roughly $0.0002) |

**The sub-100 ms gate target is not met.** A warm gate request measured 162 ms p50 and
195 ms p95 from this machine, and none of 60 came in under 134 ms (`reports/latency.json`).
The gate budget is therefore 300 ms. Because the gate and the fan-out run concurrently, the
gate adds nothing to end-to-end time when retrieval goes ahead. The p95 of about 400 ms
comes from a second request that checks conflicts between relevant notes that were not
compared speculatively; it ran on 30 of 90 retrievals.

What calibration chose (`reports/calibration.json`, calibration split only):

| Choice | Evidence |
|---|---|
| Relevance primitive: **Choice** | Average precision 0.968, against Noul 0.943 and Score 0.872 |
| Fan-out shape: **one request** | 0.968 against 0.969 for one request per candidate; no meaningful difference |
| Relevance calibration | Calibration error 0.022 raw, 0.005 after isotonic mapping (cross-validated) |
| Gate | Separated the 150 calibration events perfectly; the unsettled band sits in the gap |

Ablations on the test split, replayed from recorded answers:

| Variant | Miss | Context precision | Context recall | Stale fact |
|---|---|---|---|---|
| Full pipeline | 2.2% | 0.896 | 0.906 | 6.8% |
| No conflict resolution | 1.1% | 0.677 | 0.939 | 48.3% |
| Uncalibrated, default 0.7 / 0.3 thresholds | 4.4% | 0.869 | 0.906 | 12.8% |
| Token budget 30 | 2.2% | 0.909 | 0.894 | 5.7% |

Conflict resolution removes most stale facts at a cost of about three points of recall,
from occasionally retiring a note that was still needed.

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
| Noul gate | `gate.py` | Two Nouls: does the event name something particular, and does it depend on a detail it does not state? Code combines them and bands the result into yes / no / unsettled. 300 ms budget (measured p95 is 195 ms); a slow or failed gate suppresses. |
| Pre-filter | `retrieve.py` | MiniLM embeddings fused with BM25, exact NumPy search, Top-20. |
| Fan-out | `fanout.py` | One request, sent before the gate answers: a relevance Choice per candidate, plus a conflict question per similar pair. Cancelled if the gate says no. |
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

Chosen: MiniLM, BM25 fusion, NumPy, K = 20. Fan-out latency grows slowly with K (190 ms
p50 at 12, 204 ms at 20), so the extra recall is worth it.

## Running it

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[eval]"
cp .env.example .env          # then add TYPESAFE_API_KEY (read from this directory, or export it)
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

The three Jev scripts send the synthetic golden data only. One pass of all three uses about
4 million input tokens, roughly $0.17 at $0.042 per million.

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

- The golden data is synthetic and templated, and the gate separated it perfectly. Real
  clipboard traffic will be messier; expect a non-zero intrusion rate and recalibrate on
  real events before trusting these thresholds.
- The test split is 150 events. A 0-of-60 intrusion rate is consistent with a true rate
  of up to about 5%.
- Jev's answers varied slightly between identical live runs (miss rate 2.2% to 3.3%).
- Some labels are debatable: "Priya is the lead on Atlas" is marked irrelevant to "what
  does Priya do here?". Several of Jev's apparent errors are of this kind.
- Golden notes average 14 tokens, so the token budget rarely binds and the knapsack is
  only lightly exercised.
- Listeners are macOS only and have not been run live against a real clipboard. The
  clipboard listener skips entries a password manager marks as concealed.
- Latency was measured from one machine on one network.
