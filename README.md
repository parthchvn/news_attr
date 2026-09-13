# XVI — Polymarket price movements, news attribution and D–C

A reproducible pilot for **507300** (Inter Milan to win the UEFA Champions League)
and **2446852** (Ronaldo to cry at the World Cup), using the committed real trade
extract from SII-WANGZJ/Polymarket_data.

## Fine-resolution update — start here

The default dashboard now shows **30-second execution-price observations and every
individual supported alert**, not three merged dots. It checks 30-second,
1-minute, 3-minute, 5-minute and 15-minute horizons separately. The display has
match-window buttons, full-history navigation, raw-fill/VWAP layers and an
unusual-only filter. Fine outputs are under `outputs/two_markets/fine/`.

```bash
git clone https://github.com/parthchvn/news_attr.git
cd news_attr
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[parquet,dev]'
python -m pytest -q
python -m polymarket_context.fine
open outputs/two_markets/dashboard.html

# Optional finer bins:
python -m polymarket_context.fine --bin-seconds 15
```

For an existing clone, run `git pull` first. Downloaded HTML opens directly in a
browser; GitHub's normal file preview does not execute the dashboard.

Use **`python -m polymarket_context.rebuild`** for a complete legacy D-C/candidate
rebuild followed by the new fine dashboard. The old `seed` command alone still
produces the legacy overview; run `fine` afterward. Old five-minute episode and
D-C files retain their original semantics. Their counts are not the new counts.

The detector uses a share-weighted median, corroboration by multiple transactions,
explicit missingness, boundary-aware changes and past-only robust thresholds.
Supported size changes and statistically unusual candidates are labelled
separately. More markers do not establish more independent news events or higher
causal accuracy. New source searches are queued, **not executed**; strict C/news
and final outcomes are not changed.

Read [the full detection specification](docs/FINE_DETECTION.md),
[the quickstart](QUICKSTART.md), and the actual
[run summary](outputs/two_markets/fine/summary.json). The old overview is preserved
as `outputs/two_markets/dashboard_legacy.html`. The **Fine-resolution price
detection** workflow runs all tests, rebuilds on the real Parquet extract, and
publishes the completed dashboard, diagnostics and generating commit.

## What is in the repository

| Location | Contents |
|---|---|
| `data/selected/` | Filtered real trades, market metadata, pinned source revision and extraction manifest |
| `outputs/two_markets/dashboard.html` | Fine-grained interactive price and context review |
| `outputs/two_markets/fine/` | Fine observations, all alerts, data-quality diagnostics, bounded news groups and planned searches |
| `outputs/two_markets/dashboard_legacy.html` | Original five-minute/merged-episode dashboard |
| `outputs/two_markets/dc.jsonl.gz` | Executed-action D plus strict earlier market/history C; audited news gate |
| `outputs/two_markets/dc_candidate.jsonl.gz` | Exploratory D/C_candidate, explicitly not training-eligible |
| `outputs/two_markets/documents.jsonl` | Existing candidate source records and timestamp uncertainty |
| `outputs/two_markets/pilot_status.json` | Legacy D-C and news coverage, not new fine-alert counts |
| `docs/VERIFICATION.md` | Historical news availability and text-version audit requirements |

## News status

The first hosted RSS run failed on all 42 requests. The inspected pilot uses
**eight manually located source records**, five for Inter and three for Ronaldo,
including UEFA, Reuters, Field Level Media and AP coverage. This is not complete
automatic historical news collection. Only three have a recovered publication
clock; a publisher timestamp alone does not establish the historical text version.
Completed-match reports are aftermath, not pre-goal evidence.

The fine dashboard only carries existing sources into overlapping, previously
scoped windows and recomputes their timing roles. It does not invent explanations
for new alerts. Strict `C.news` remains empty in the current seed build; the
candidate dataset makes potential context inspectable without calling it
leakage-audited training data. Source retrieval code remains available in
`collect.py`, but a working historical provider is needed to automate the new
queue. X is not integrated.

After a full local rebuild, import genuinely audited documents with:

```bash
python -m polymarket_context.pilot --stage dc --verified-documents verified_documents.jsonl
python -m polymarket_context.fine
```

Do not relabel a hindsight-selected source merely to pass the strict-context gate.

## Price and action semantics

Read `trades.parquet`, not maker/taker-expanded `users.parquet`. Map token1 price
to p and token2 to 1-p; `quant.parquet` is already normalized and must not be
inverted again. Outcome labels are checked against metadata. These are completed
execution prices, not reconstructed best asks or bids. No buying quote can be
inferred between trades from this extract alone.

Exact chain logs are deduplicated, invalid zero-share rows rejected and known
exchange summary addresses filtered. This does not audit every possible economic
duplication or distinguish humans from bots.

D is a taker transaction/market/token/direction bundle aggregating fills. C uses
completed price bins strictly before execution, earlier selected-market actor
history and eligible news. Same-timestamp histories are frozen. Own-fill prices
and final resolution stay outside C. A fill can execute an order submitted
earlier; these are pre-fill executed-action proxies, not observed reasoning,
proven individual exposure or reconstructed order-submission decisions. Portfolio
history outside these two markets is missing.

## Re-extraction, tests and provenance

The saved extract avoids scanning the full dataset again. Re-extract only when
needed:

```bash
python scripts/extract_hf.py --output data/selected
# Or use local source files:
python scripts/extract_hf.py --source /path/to/trades.parquet --markets-source /path/to/markets.parquet
```

Remote predicate pushdown can still transfer many GB. The pinned source revision
and hash are recorded in `data/selected/extraction_manifest.json`.

Tests cover normalization, exact-log identity, gaps, strict temporal joins,
future-change invariance, robust fine-window detection, same-time support,
news timing gates and safe report rendering. Software tests do not prove causal
attribution or historical news completeness. Fine detector accuracy still needs
an independently timestamped, held-out event benchmark.

Source schema: https://huggingface.co/datasets/SII-WANGZJ/Polymarket_data

Order lifecycle: https://docs.polymarket.com/concepts/order-lifecycle

Respect source terms. Source records contain links, headlines and short newly
written paraphrases, not full copyrighted article bodies or source images.
No trading, wallet signing, private keys or API secrets are involved.
