# Evaluation and architecture

For contributors, and for anyone deciding how far to trust vice.

## Pipeline

```
event ─► pre-gate (code) ─┬─► Noul gate ───────────────────────────┐
                          └─► pre-filter ─► speculative fan-out ───┤
                                                                   ▼
            decision (code) ◄─ knapsack ◄─ conflict resolution ◄─ calibrate
```

| Stage | File | What it does |
|---|---|---|
| Pre-gate | `pregate.py` | Length bounds, de-duplication, secret masking. |
| Noul gate | `gate.py` | Two Nouls: does the event name something particular, and does it depend on a detail it does not state? Code combines them and bands the result into yes / no / unsettled. A slow or failed gate suppresses. |
| Pre-filter | `retrieve.py` | MiniLM embeddings fused with BM25, exact NumPy search, Top-20. |
| Fan-out | `fanout.py` | One request, sent before the gate answers: a relevance Choice per candidate, plus a conflict Noul per similar pair. Cancelled if the gate says no. |
| Calibration | `calibrate.py` | Logistic model over the gate Nouls; isotonic map for relevance. |
| Conflict resolution | `conflict.py` | Jev says whether two notes disagree; code knows which is newer. The older note's value halves every 14 days of gap, and it is dropped once below the relevance floor. |
| Packing | `pack.py` | Exact 0/1 knapsack over the token budget. |
| Decision | `decide.py` | A truth table mapping gate status and packed context to `suppress`, `attach` or `surface`. |

All wording sent to Jev is in `questions.py`. All numbers are in `config.py` or the
fitted `default_calibration.json`.

## Results

Held-out test split of a synthetic dataset: 150 events (90 need retrieval, 60 do not)
over 1,500 notes, live calls to `jev-1.14.0`, thresholds fitted on a separate split.

| Measure | Result |
|---|---|
| Intrusion rate (acted when nothing was warranted) | 0 of 60 |
| Miss rate (stayed silent when context was needed) | 2 of 90 (2.2%) |
| Context precision / recall against required notes | 0.896 / 0.906 |
| Context exactly right | 77.8% |
| A superseded fact shown alongside or instead of the current one | 6.8% |
| End-to-end latency | 210 ms p50, 404 ms p95 |
| Jev input tokens per event | about 4,500 (roughly $0.0002) |

**Latency.** The original design target for the gate was 100 ms. A warm gate request
measured 162 ms p50 and 195 ms p95, and none of 60 came in under 134 ms, so the budget is
300 ms. The gate runs concurrently with the fan-out and adds nothing to end-to-end time
when retrieval proceeds. The p95 comes from a second request that checks conflicts
between relevant notes not compared speculatively; it ran on 30 of 90 retrievals.

What calibration chose, on the calibration split only:

| Choice | Evidence |
|---|---|
| Relevance primitive: Choice | Average precision 0.968, against Noul 0.943 and Score 0.872 |
| Fan-out shape: one request | 0.968 against 0.969 for one request per candidate |
| Relevance calibration | Calibration error 0.022 raw, 0.005 after isotonic mapping |
| Gate | Separated the 150 calibration events perfectly |

Ablations on the test split, replayed from recorded answers:

| Variant | Miss | Context precision | Context recall | Stale fact |
|---|---|---|---|---|
| Full pipeline | 2.2% | 0.896 | 0.906 | 6.8% |
| No conflict resolution | 1.1% | 0.677 | 0.939 | 48.3% |
| Uncalibrated, default 0.7 / 0.3 thresholds | 4.4% | 0.869 | 0.906 | 12.8% |

Pre-filter comparison (calibration split, recall of required notes):

| Embedder, with BM25 fusion | Recall@12 | Recall@20 | Query embed p95 |
|---|---|---|---|
| all-MiniLM-L6-v2 | 0.939 | 0.989 | 3.9 ms |
| nomic-embed-text-v1.5 | 0.922 | 0.983 | 23.1 ms |
| potion-base-8M (static) | 0.828 | 0.989 | 0.08 ms |
| bge-small-en-v1.5 | 0.867 | 0.917 | 6.7 ms |

Raw reports are in `reports/`.

## Known limits

- **The data is synthetic and templated**, and the gate separated it perfectly. Real
  clipboard traffic will be messier. Expect a non-zero intrusion rate.
- **Real notes are chunked differently from the test notes.** The test notes are single
  sentences. A real Markdown chunk is a paragraph or several, often holding more than
  one fact, and carries a title prefix. The shipped thresholds have not been validated
  on chunks of that shape.
- The test split is 150 events. 0 of 60 intrusions is consistent with a true rate of up
  to about 5%.
- Jev's answers varied slightly between identical live runs (miss rate 1.1% to 3.3%).
- Some labels are debatable, and several of Jev's apparent errors are of that kind.
- Latency was measured from one machine on one network.
- The clipboard listener has unit coverage only; it has not been run against a live
  clipboard.

## Running the harness

From a checkout, with `TYPESAFE_API_KEY` in a `.env` file at the repository root:

```bash
pip install -e ".[mcp,eval,dev]"
```

```bash
python -m vice_ai.eval.dataset
```

```bash
python -m vice_ai.eval.prefilter
```

```bash
python -m vice_ai.eval.latency
```

```bash
python -m vice_ai.eval.calibrate
```

```bash
python -m vice_ai.eval.e2e
```

`dataset` regenerates the golden set (seeded). `prefilter` is local only. The last three
call Jev with the synthetic data; one pass of all three uses about 4 million input tokens,
roughly $0.17. `calibrate` rewrites `src/vice_ai/default_calibration.json`.

## Recalibrating

The shipped thresholds are tied to `jev-1.14.0`. Loading them with a different pinned
model raises an error instead of silently using stale numbers.

A user can override them by placing a file of the same shape at
`~/.vice/calibration.json`. There is not yet a command that fits one from a user's own
labelled events; that is the most valuable missing piece. The decision log
(`~/.vice/decisions.jsonl`) already records what such a tool would need as input, short
of the labels.
