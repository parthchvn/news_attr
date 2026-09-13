# Working two-market run

The filtered trades are already committed: **86,687 raw Inter fills** and **32,496 raw Ronaldo fills**. One zero-share Inter row is rejected in normalization. The source revision and actual counts are in `data/selected/extraction_manifest.json`.

## Open the completed result

Open `outputs/two_markets/dashboard.html` locally after cloning/downloading the repository. It embeds Plotly. GitHub's normal file view does not run HTML. Inspect `outputs/two_markets/pilot_status.json` for actual news/link/D-C counts.

## Reproduce without a news API

```bash
git clone https://github.com/parthchvn/news_attr.git
cd news_attr
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[parquet,dev]'
python -m pytest -q
python -m polymarket_context.seed
```

This rebuilds derived outputs from the already-filtered real trades and eight inspected source records in `context/seed_documents.jsonl`. It overwrites generated outputs; keep your review/verified import files separately. No full HF download or paid API is needed. Rebuilding also establishes local absolute-path provenance before running other CLI stages.

## What is complete, and what is not

Price reconstruction and D-C market/history features have run on real data. **Automatic RSS retrieval failed on all 42 requests in the first run**. The actual result therefore uses a small, manually sourced fallback, not a claim of complete automatic news coverage. The original failures are preserved in the recovery artifact/output when available.

There are five Inter-related records (UEFA previews/reports and a Reuters lineup announcement) and three Ronaldo-related records (Reuters, Field Level Media and an AP eyewitness report). Sources have URLs, publisher date claims, explicit date uncertainty and manual discovery provenance. Repeated coverage shares an information-event ID; it is not independent evidence of multiple catalysts.

Only three of these sources have an explicitly recovered publication clock. Date-only sources remain retrospective chart annotations, not pre-trade inputs. Completed-match reports remain aftermath; final scores are never backdated into C. The sources were selected around known episodes and their text versions are not independently archived, so **none is promoted to strict C.news**.

The first detector is intentionally conservative about trade gaps. It flags ten complete-window movement episodes in this snapshot, not every economically important change. Three are Inter episodes, seven Ronaldo episodes. Not every episode receives a candidate explanation.

## D-C files

`dc.jsonl.gz` contains **D** (grouped taker executions) and **C** (strict earlier completed-price bins, selected-market actor history and verified news only). This pilot has market/history C but no verified news.

`dc_candidate.jsonl.gz` contains the same D with **C_candidate**, including eligible earlier publisher-time news candidates. Every row has `training_eligible: false`: this is a review dataset, not leakage-audited training data. The point is to make the first version useful without disguising uncertainty.

`decision_news_candidates.jsonl.gz` is the normalized decision-to-candidate join. `documents.jsonl` and `attribution_links.jsonl` retain article provenance and retrospective episode associations.

## Context-attribution steps

1. Inspect a price-movement marker and its source cards. Separate pre-window candidates, ambiguous dates and aftermath; do not assign a cause just because it sounds plausible.
2. Open the original source. For sports, compare lineups, goals and contemporaneous video reports with the contract's precise rules. Game-clock minutes are not UTC news-publication times.
3. Record a review label and alternatives. A source that explains the event retrospectively is still not necessarily usable before a trade.
4. Recover a defensible earlier text version and availability time. Keep source selection independent of the target action for training. Follow `docs/VERIFICATION.md`; do not relabel spike-selected sources to pass the gate.
5. Import genuinely audited documents with `python -m polymarket_context.pilot --stage dc --verified-documents verified_documents.jsonl` after a local rebuild. Inspect the coverage manifest rather than assuming all trades received news.

For new automatic collection, the configurable RSS and optional Tavily adapters remain in `collect.py`. The RSS source failed in the hosted run; a provider with working historical coverage is required to automate beyond this inspected seed. The seed runner makes no claim to have fixed that provider failure. X is not connected by this code.

Wallet activity is not automatically human behavior; a fill may execute an earlier submitted order. Grouping is an executed-action proxy, not an identification of the trader's true reasoning or original decision time.
