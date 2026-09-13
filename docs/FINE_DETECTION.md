# Fine-resolution detector v2

This is a higher-resolution **execution-price** detector, not an order-book
reconstruction, a causal-news detector, or a calibrated hypothesis test.
It keeps every qualifying alert timestamp visible; it does not replace a match
with two episode dots. Existing conservative D-C files are not silently changed.

## Run

```bash
python -m pip install -e '.[parquet,dev]'
python -m pytest -q
python -m polymarket_context.fine
open outputs/two_markets/dashboard.html

# Optional finer observations; every configured horizon must be divisible by 15.
python -m polymarket_context.fine --bin-seconds 15

# Complete legacy D-C/candidate rebuild, followed by the finer dashboard.
python -m polymarket_context.rebuild
```

The default config is `config.two_markets.json`. The command uses the committed
119,183-row raw extract, with the existing normalization and participant filter.
The invalid zero-share row is still rejected. Nothing is downloaded from a news
provider. Raw source hashes and actual per-market counts are recorded in
`outputs/two_markets/fine/summary.json`.

## Price observations and support

Default bins are **30 seconds**, not five minutes. They are left-closed,
right-open intervals `[t-30s,t)` labelled by their end `t`. All times are UTC.
Only observed bins are stored. No price is carried forward across a gap.

For each bin the export contains the share-weighted average (VWAP), share-weighted
median, low/high executions, shares, distinct transaction count, corroborating
transaction count and first/last fill time. All prices are converted to the
same outcome-1 scale once using the existing normalization.

The detector and default chart use the **weighted median**. Small extreme fills
are less influential than with VWAP. The familiar VWAP and all individual
execution prices are optional legend layers. Neither is a best ask or bid.

Both endpoint bins must have at least **two distinct transactions trading within
0.5 percentage points of that bin's median**, and at least five total shares.
Two logs of the same transaction are not two observations. A single large extreme
trade is not enough even if other trades occur elsewhere in the bin. These are
heuristic price-corroboration checks, not proof of independent traders or truthful
information. They can exclude genuine but poorly supported movements.

## Multiple horizons

Every observed timestamp is checked over **30, 60, 180, 300 and 900 seconds**.
The exact endpoint bin at `t-h` must exist; a stale price is not substituted.
Endpoint change is measured only if at least 60% of the expected bins in the
window were observed. Such partial windows retain their coverage and do not
imply the price was constant in the gaps.

Let `p_t` be the bin's weighted median and `s_h = sqrt(max(1,h/60))`.
A supported candidate has at least one of:

* Net movement: `abs(100*(p_t-p_(t-h))) >= 1.0*s_h` percentage points.
* Near a boundary (either endpoint at or below 0.10, or at or above 0.90):
  absolute movement at least **0.2 percentage points**, and absolute log-odds
  change at least **0.35*s_h**. Prices are clipped to `[0.001,0.999]` only for
  this log-odds computation. The unclipped execution prices remain in the chart.
* Rolling variation at least **1.5*s_h** percentage points, where variation is
  the square root of the sum of squared adjacent-bin changes. **Every step must
  be observed and supported** for variation; no incomplete path is treated as
  a complete volatility measurement.

Tiny numerical tolerances prevent a mathematically exact threshold crossing from
changing with CSV/Parquet floating-point round trips. Thresholds are defaults,
not empirically optimized precision/recall guarantees.

## Two alert tiers, not one misleading confidence score

`supported_change` means the size and data-support conditions passed.
`unusual_change` additionally requires the corresponding robust past-only score
to reach **4**. The reference center is the rolling median; scale is
`(Q75-Q25)/1.349`, floored at 0.15 percentage points or 0.05 log-odds units.
At least 30 eligible reference observations in the last 24 hours are required.

The reference strictly excludes the current window, including its first price
bin. For a current horizon h and bin width b, historical metrics ending at s
are eligible only when `s <= t-h-b`. Statistics expire by wall-clock time even
when observations are sparse. There are no centered windows, backwards fills,
future-confirmation filters, final results or later news in the detector.

When there is insufficient history, size candidates are retained but explicitly
NOT labelled statistically unusual. Overlapping horizons are consolidated into
one marker at a timestamp, with **all triggering horizon records retained**.
Successive timestamps remain separate. A single evolving move can trigger many
markers; counts are not counts of independent information events. Scores are
not p-values, probabilities, or multiple-testing-corrected significances.

## Dashboard and exports

`outputs/two_markets/dashboard.html` now opens the fine dashboard directly, with
preset detail windows, full-history navigation, raw fill/VWAP toggles, and filters
for all supported alerts, unusual-only alerts, or short-horizon alerts. It is
self-contained HTML using SVG plotting, including in browsers without WebGL.
Click a marker or table row for per-horizon evidence and existing source links.
The table shows at most 100 rows in the visible range, but markers are not dropped.

Files under `outputs/two_markets/fine/`:

| File | Meaning |
|---|---|
| `bars.csv.gz` | Observed 30-second price/support records; no filled gaps |
| `diagnostics.csv.gz` | Every observed timestamp/horizon, eligible or rejected |
| `alerts.jsonl`, `alerts.csv` | Every supported alert; no time-cluster suppression |
| `news_groups.jsonl` | Bounded grouping for retrieval only |
| `search_jobs.jsonl` | Planned queries; **not executed** by this command |
| `legacy_context_links.jsonl` | Existing candidate sources within their prior manual scope |
| `summary.json` | Config, source hash, coverage and actual counts |
| `dashboard.html` | Same fine view as the familiar parent entry point |

The old report is retained as `outputs/two_markets/dashboard_legacy.html`.
Legacy `bars.csv`, `episodes.jsonl`, `pilot_status.json` and D-C exports retain
v1 semantics; they are not the counts or features for this new detector.
Use the `fine/` files for the new results. The old `seed` or `pilot` command alone
can regenerate the legacy dashboard; run `fine` afterward or use `rebuild`.

## News and D-C safeguards

Only the retrieval layer groups detections: at most 120 seconds between adjacent
alerts and at most 600 seconds from the first to last detection in a group.
The evidence window can start earlier because of the longer horizons. These
limits never remove price markers.

No new historical source collection was performed. Existing news is displayed
only when a fine alert lies within the old manually reviewed episode scope, and
publication ordering is recalculated for the fine window. These associations
remain explicitly unverified and ineligible for training; they are not new
causal attributions. Other alerts have planned search jobs, not invented context.

The original D-C files still contain their original earlier five-minute market
features and timestamp-audited news gate. This update does not replace them with
retrospectively selected context. Joining finer features later must use
`bin_end < decision_timestamp`, never a bin containing the target execution.

## Validation and limits

Tests exercise flat paths, known steps, reversals, tail repricing, unsupported
single-transaction excursions, large uncorroborated prints, sparse windows,
wall-clock expiry, future-change invariance, market isolation, configuration
validation, same-time aggregation, bounded news grouping and safe HTML rendering.
A 15-second synthetic step is also tested. These are software/injected-signal
checks, not a real-match false-positive/false-negative evaluation.

To establish actual event-detection accuracy, build a separately timestamped
match-event/announcement set, assess onset error and missed/extra alerts on held-out
matches, and inspect raw executions around suspected anomalies. Do not tune the
detector to produce a target number of dots. A persistent change is not necessarily
news; an event entirely inside one bin can be lost, and finer bins can have less
support. The data's settlement timestamps do not recover order-submission time
or the exact instant information reached traders.

Primary references for source semantics and implementation mechanics:
- https://huggingface.co/datasets/SII-WANGZJ/Polymarket_data
- https://docs.polymarket.com/concepts/order-lifecycle
- https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.rolling.html
