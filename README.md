# XVI — news attribution and D–C pilot

Two requested contracts: **507300** (Inter Milan to win the UEFA Champions League) and **2446852** (Ronaldo to cry at the World Cup). Contract IDs and outcome labels are checked against source metadata. Screenshot volume/fill/resolution claims are not substituted for measured results.

This repository reconstructs **trade-derived price movements**, collects **candidate information**, and exports **taker execution-bundle D–C records**. It does not infer individual exposure, true order-submission time, human/bot status, reasoning, or causation from adjacent headlines.

## Run

```bash
git clone https://github.com/parthchvn/news_attr.git
cd news_attr
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[parquet,dev]'
python -m pytest -q

# Skip extraction when data/selected/trades.parquet is already in your clone.
python scripts/extract_hf.py --output data/selected
python -m polymarket_context.pilot --stage all
# Open outputs/two_markets/dashboard.html in a browser.
```

For previously generated outputs, use `--overwrite` to rebuild all. This resets derived document/review tables, so keep verified imports and reviews separately. Cached search responses are reused. Do not repeatedly download the full source: use the saved filtered extract.

A local-source alternative avoids HTTP scanning:

```bash
python scripts/extract_hf.py --source /path/to/trades.parquet \
  --markets-source /path/to/markets.parquet --output data/selected
```

The HF reader is pinned to dataset revision `6d3c336c39cf1a2dfe53d702ad2c110ab5bdbfde`. Predicate and column pushdown avoid loading the complete file into pandas, but may still transfer many GB when row groups are not clustered by market ID. A failed/incomplete scan is reported, never called a complete extract.

## Actual results and execution status

GitHub Actions **Extract requested Polymarket markets** runs the bounded remote extraction and commits the small selected dataset on success. **Construct charts and D-C pilot** runs after a successful extraction, or can be started manually under Actions. **Software tests** validates the code, including Parquet handling. Each workflow's success/failure should be checked; the mere existence of source code does not imply real-data completion.

Generated results, when successful:

| Path | Contents |
|---|---|
| `data/selected/extraction_manifest.json` | Pinned revision, actual raw fills/notional/coverage, source hash and extraction status |
| `data/selected/markets.json` | Original metadata, including ex-post fields; audit only, not fed wholesale into C |
| `data/selected/trades.parquet` | Only the requested market IDs, original trade columns |
| `outputs/two_markets/dashboard.html` | Self-contained interactive price chart, alerts and candidate source cards |
| `outputs/two_markets/bars.parquet` | Observed five-minute execution-price bins, gaps and diagnostics |
| `outputs/two_markets/episodes.jsonl` | Movement windows, first detection, peak scores, quality flags |
| `outputs/two_markets/documents.jsonl` | Retrieved headlines/excerpts, source links, timestamps and provenance |
| `outputs/two_markets/attribution_links.jsonl` | Retrospective candidate episode–document associations |
| `outputs/two_markets/dc.jsonl.gz` | D plus conservative as-of C; only audited news is eligible for C.news |
| `outputs/two_markets/decision_news_candidates.jsonl.gz` | Useful but unverified/possibly spike-selected research candidates, explicitly NOT C |
| `outputs/two_markets/decisions.csv.gz` | Grouped taker executions with original token/direction |
| `outputs/two_markets/pilot_status.json` | Actual episode, article, link, decision and news-coverage counts |
| `outputs/two_markets/search_status.jsonl` | Successful, empty, failed, missing-key and budget-skipped requests |

GitHub does not render arbitrary HTML files as a working website. Download `dashboard.html` (or the Actions artifact) and open it locally. Plotly is embedded; no local server is needed.

## 1. Reconstruct prices

Use **trades.parquet**, not the maker/taker-expanded `users.parquet`. Normalize the two outcome tokens onto one axis: token1 price stays `p`; token2 becomes `1-p`. `quant.parquet` is already normalized and must not be inverted again. Outcome labels come from metadata, not a universal token1=Yes assumption.

Filter known exchange-summary/zero-address legs, reject invalid rows, deduplicate exact chain logs, and leave missing prices missing. The filters do not claim to reconcile all economic duplication or identify human traders. Counts and USD are recorded-fill aggregates, not audited economic turnover.

For each contract, five-minute price = `sum(outcome1_price * shares) / sum(shares)`. Original USD notional is preserved separately: mixing both token sides makes `sum(USD)/sum(shares)` the wrong outcome1 price. Never pool parent event IDs or invent historical order-book depth from fills.

The detector uses 15-minute net repricing AND back-and-forth variation, each compared with robust past-only baselines. Initial gates are 3 percentage points and robust z >= 4, with 24-hour baseline, minimum 24 historical bins, and 0.5pp scale floor. Consecutive observed bins are required; gaps are not forward-filled. Alerts within 30 minutes merge into retrospective episodes. These are engineering thresholds, not p-values or proven optimum settings. First detection is observable only at bin close; the coarse onset window is not an exact information-arrival time.

## 2. Retrieve and assess context

Use `python -m polymarket_context.pilot --stage news` after analysis. It combines two retrieval modes:

- **Calendar discovery:** fixed 14-day windows across each contract's observed history, independent of spike size. This provides ordinary-period context rather than selecting every document by the target movement.
- **Spike enrichment:** deeper searches around the ten strongest episodes per market, from 24 hours before the coarse window to two hours after it.

Default provider is a best-effort **Google News RSS** search, with 80 uncached requests total and a one-second delay. This is a lightweight discovery adapter, not a guaranteed historical archive. It records the headline and publication claim; it does not scrape/paywall-bypass full articles, prove original text availability, or guarantee complete coverage. Cache contains exact RSS responses. Failed, empty and unsearched windows remain distinguishable.

Set `news.provider` to `tavily` and set environment variable `TAVILY_API_KEY` to use the alternative adapter. Charges depend on your provider account; request budgets are explicit. API keys are never committed or cached. Provider dates can be estimated publication/update times and are not automatically accepted as proof of historical availability. X is not integrated into this pilot; historical X access can be added through an authorized archive provider.

Market-specific searches include Inter/Internazionale + Champions League, and Ronaldo + World Cup/Portugal. For Inter, inspect match events, lineups, injuries, draws and results. For Ronaldo, inspect contemporaneous match/appearance reports and timestamped video evidence against the exact contract rules. A current article saying someone cried is not proof that the same evidence existed before a particular trade.

Candidates require all configured keyword groups. Timing is classified as before the coarse window, during it, after it, or unknown. Ranking is a transparent lexical/time heuristic—not semantic entailment, novelty detection, calibrated probability, or causal identification. The dashboard permits no-match episodes and multiple plausible explanations.

Copy `review_template.jsonl` to a separate reviews file, label entries `plausible_context`, `background`, `aftermath`, or `rejected`, then run:

```bash
python -m polymarket_context render --config config.two_markets.json --reviews reviews.jsonl
```

A review label does not automatically make a document safe for C. See `docs/VERIFICATION.md` for timestamp/text auditing.

## 3. Construct D–C

Run `python -m polymarket_context.pilot --stage dc` after news retrieval.

D is a **taker transaction/market/token/direction bundle**. Multiple fills from the same bundle aggregate into execution price, shares and recorded cash amount. We preserve original BUY/SELL and token side, plus a separate outcome1-equivalent direction. The transaction hash is also the split group: never split the same transaction across training/test sets. These are observable executed-action proxies, not reconstructed order-placement decisions. Maker decisions are not inferred.

For each D timestamp t, C uses:

1. The last observed completed price bin with `bin_end < t`, stale/missing flags and backward-looking movement features. No own-fill price, same-timestamp data, or future bar is included.
2. Prior taker bundle counts and recorded notional within the selected two markets. Histories are incomplete portfolio information; they are not balances or known positions.
3. Up to eight relevant, independently collected, timestamp/text-audited news items from the prior 72 hours. The exact verified text—not a later headline/update—is attached.

All bundles at the same timestamp see histories before that timestamp's batch. Final resolution, snapshot outcome_prices, future cumulative market volume and hindsight attribution descriptions stay out of C. Only configured contract identity/labels enter C; historical rule revisions are not reconstructed.

**Default automated retrieval usually leaves C.news empty**, because RSS/search dates are not verified. The program still creates D–C with market/history context, and separately joins pre-timestamp candidate headlines in `decision_news_candidates.jsonl.gz`. Do not silently merge that exploratory file into training inputs. It may contain later text versions and hindsight-selected sources.

To add audited information:

```bash
python -m polymarket_context.pilot --stage dc --verified-documents verified_documents.jsonl
```

Strict eligibility requires `timestamp_status=verified`, an aware `verified_available_at`, exact `verified_text`, verification evidence, and discovery mode `calendar` or `independent_manual`. A document found only because of a later spike remains outside strict C even when its claimed publication time is earlier. Unattributed does not mean no relevant information existed.

## Validation and scope

`python -m pytest -q` tests normalization, exact-log deduplication, gaps, causal-time feature calculations, future-change invariance, source/timestamp gates, same-time history exclusion, RSS handling, the complete synthetic dashboard, and Parquet roundtrip. Synthetic fixtures are labeled; they are not empirical results for these two contracts. Live coverage and real sample sizes are established only by completed run manifests.

This is a first-version research pipeline. Two contracts are not a generalization benchmark. A public-information context cannot establish what an individual trader read, and a fill can execute an order submitted before the observed news. Market/news associations are not proof of causation.

## Sources

- Dataset schema and transformations: https://huggingface.co/datasets/SII-WANGZJ/Polymarket_data
- Pinned snapshot: https://huggingface.co/datasets/SII-WANGZJ/Polymarket_data/tree/6d3c336c39cf1a2dfe53d702ad2c110ab5bdbfde
- Polymarket order lifecycle: https://docs.polymarket.com/concepts/order-lifecycle
- Tavily search/date fields: https://docs.tavily.com/documentation/api-reference/endpoint/search

Respect each data/source provider's terms, copyright and rate limits. Public visibility is not by itself a redistribution license. No trading, wallet signing or private keys are involved.
