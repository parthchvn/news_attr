# XVI — Polymarket news attribution and D–C

A working first-version pipeline for **507300** (Inter Milan to win the UEFA Champions League) and **2446852** (Ronaldo to cry at the World Cup).

**Start with [QUICKSTART.md](QUICKSTART.md).** The selected real trades are committed. Completed outputs are published to [`outputs/two_markets`](outputs/two_markets) by the **Publish inspected-context pilot** workflow; check the run and `pilot_status.json` rather than assuming source code implies successful execution.

## Open or reproduce

Clone/download the repository and open `outputs/two_markets/dashboard.html` locally. GitHub's file viewer does not run arbitrary HTML; the downloaded file embeds its plotting library and needs no server.

```bash
git clone https://github.com/parthchvn/news_attr.git
cd news_attr
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[parquet,dev]'
python -m pytest -q
python -m polymarket_context.seed
```

This rebuilds all derived outputs from the already-filtered real trades and the inspected news seed. **No paid API or full HF download is needed.** The rebuild overwrites derived outputs; keep manual review and verified import files separately.

## What this produces

| File under `outputs/two_markets/` | Meaning |
|---|---|
| `dashboard.html` | Interactive prices, movement markers and candidate-source cards |
| `bars.csv`, `bars.parquet` | Five-minute trade-derived prices, activity, gaps and diagnostics |
| `episodes.jsonl` | Coarse movement windows and first detection times |
| `documents.jsonl` | Real source headlines, short paraphrases, URLs and timestamp uncertainty |
| `attribution_links.jsonl` | Retrospective episode-to-document associations, not causal labels |
| `dc.jsonl.gz` | D plus strict earlier market/history C; only audited news may enter C.news |
| `dc_candidate.jsonl.gz` | D plus C_candidate with earlier publisher-time news candidates; every row is explicitly not training-eligible |
| `decision_news_candidates.jsonl.gz` | Normalized candidate-news join, kept separate from strict C |
| `decisions.csv.gz` | Grouped taker executions with original token and BUY/SELL side |
| `pilot_status.json` | Actual coverage, decision counts and strict versus candidate news counts |
| `search_status.jsonl` | Original failed searches and explicit manual-fallback provenance |

## Important status of the news layer

**The first hosted RSS run failed on all 42 requests.** To make the first version inspectable, this run uses **eight manually located and inspected source records**: five for Inter and three for Ronaldo. These are UEFA, Reuters, Field Level Media and AP reports, including syndicated publisher copies. This is not complete automatic historical news collection.

Only three records have a recovered publication clock; date-only sources remain chart annotations. Exact publisher timestamps still do not certify the historical text version. Completed-match reports are aftermath, not pre-goal evidence. All seed documents were selected around known episodes, and **none is silently promoted to strict C.news**. The strict dataset still contains earlier market-state and actor-history context. The candidate dataset makes unverified news inspectable without calling it leakage-audited training data.

Use the seed runner to reproduce these manually scoped links. The older generic `render` command does not apply the seed-specific date-only/episode restrictions. Follow [QUICKSTART.md](QUICKSTART.md) for reviewing and expanding the corpus.

## Price and action semantics

Read `trades.parquet`, not maker/taker-expanded `users.parquet`. Map token1 price to p and token2 to 1-p; `quant.parquet` is already normalized and must not be inverted again. Outcome labels are checked against metadata.

Five-minute price is `sum(outcome1_price * shares) / sum(shares)`. Empty bins remain missing. Original cash notional is retained separately. Exact chain logs are deduplicated, invalid zero-share rows rejected, and known exchange summary addresses filtered. These checks do not claim to audit every possible economic duplication or distinguish humans from bots.

Initial movement gates are a 3-percentage-point net repricing or rolling variation, plus robust past-only z >= 4. The baseline is up to 24 hours, with a minimum warm-up and scale floor. Complete observed windows are required. This detects ten episodes in the selected snapshot (three Inter, seven Ronaldo), not every important move across sparse-trading gaps. Thresholds are engineering heuristics, not p-values.

D is a **taker transaction/market/token/direction bundle**, aggregating multiple fills. C uses completed price bins strictly before the execution timestamp, earlier selected-market actor history and eligible news. Same-timestamp histories are frozen until all contexts in the batch are constructed. Own-fill prices and final resolution stay out of C. The transaction hash is a grouping key for dataset splits.

A fill can execute an order submitted earlier. These are executed-action proxies with pre-fill public context, not observed reasoning, proven individual exposure, or reconstructed order-submission decisions. Portfolio history outside these two markets is missing.

## Extraction and extension

The exact filtered source is in `data/selected/`, with a pinned revision, actual counts and SHA256 in `extraction_manifest.json`. Re-extract only when needed:

```bash
python scripts/extract_hf.py --output data/selected
# Or use already downloaded source files:
python scripts/extract_hf.py --source /path/to/trades.parquet \
  --markets-source /path/to/markets.parquet --output data/selected
```

Remote Parquet projection/predicate pushdown avoids loading the whole source in pandas but can still scan many GB. The saved two-market extract avoids repeating that cost.

The configurable automatic collection code (`collect.py`) includes calendar-first discovery, spike enrichment, request budgets, caching, and optional Tavily support via `TAVILY_API_KEY`. A provider with working historical coverage is required to automate beyond the seed. The seed runner does not pretend the RSS provider failure was fixed. X is not integrated.

After a local rebuild, import genuinely audited sources using:

```bash
python -m polymarket_context.pilot --stage dc --verified-documents verified_documents.jsonl
```

See [the verification protocol](docs/VERIFICATION.md). Audit exact text, availability time and discovery provenance separately from retrospective relevance. Do not relabel a hindsight-selected source merely to pass the strict-context gate.

## Tests and provenance

Tests cover token normalization, exact-log deduplication, gaps, historical-only baselines, future-change invariance, original token/direction preservation, same-time history exclusion, target-price exclusion, RSS handling, timestamp/text gates, date-only seed scoping, Parquet roundtrip and a labeled synthetic smoke test. GitHub Actions runs the committed tests with Parquet dependencies installed. Software tests do not prove news completeness or causal attribution.

Source schema: https://huggingface.co/datasets/SII-WANGZJ/Polymarket_data

Pinned snapshot: https://huggingface.co/datasets/SII-WANGZJ/Polymarket_data/tree/6d3c336c39cf1a2dfe53d702ad2c110ab5bdbfde

Order lifecycle: https://docs.polymarket.com/concepts/order-lifecycle

Respect dataset and publisher terms. Only source links, headlines and short newly written paraphrases are stored; no source images or full copyrighted article bodies are included. No trading, wallet signing, private keys or API secrets are involved.
