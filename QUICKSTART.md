# Open and run the fine-resolution pilot

## Open the completed dashboard

From the repository folder on a Mac:

```bash
git pull
open outputs/two_markets/dashboard.html
```

Or download the HTML and double-click it. It is self-contained: no server or
news API is required. GitHub's normal file preview does not run HTML scripts.
Check the **Fine-resolution price detection** workflow and
`outputs/two_markets/fine/generating_commit.txt` for the completed build.

## Rebuild the charts

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[parquet,dev]'
python -m pytest -q
python -m polymarket_context.fine
open outputs/two_markets/dashboard.html
```

The filtered real trades are already committed. You do not need to download the
full Hugging Face dataset again. Default observations are 30 seconds; optionally:

```bash
python -m polymarket_context.fine --bin-seconds 15
```

Finer bins can have less evidence. The detector does not fill missing prices or
accept poorly supported observations merely to generate more markers. Bins are
execution summaries, not executable buying quotes.

## Read the dashboard

The default line is the share-weighted median execution price. Toggle the
share-weighted average or every recorded fill in the legend. Use the match/detail
buttons to zoom into the relevant period, or **Full history** for the whole
contract. Use the dropdown for all supported changes, unusual-only changes, or
short-horizon alerts.

Click any marker or table row. The detail panel shows the exact detection time,
reference horizons, signed changes, variation, coverage, transaction support and
robust scores. One time can trigger multiple horizons; subsequent times remain
separate markers. Neither a marker nor a score establishes a separate news event.

The source panel contains existing manually scoped candidates only. Unverified
sources are not promoted into C. No-source means no match is established, not
that nothing relevant happened. New retrieval jobs are planned, not executed.

## Files

New detection outputs are in `outputs/two_markets/fine/`: `bars.csv.gz`,
`diagnostics.csv.gz`, `alerts.jsonl`, `alerts.csv`, `news_groups.jsonl`,
`search_jobs.jsonl`, `legacy_context_links.jsonl` and `summary.json`.
The older five-minute chart remains in `dashboard_legacy.html`.
The parent `bars.csv`, `episodes.jsonl` and `pilot_status.json` still describe the
legacy version, not the fine detector. This separation preserves old provenance.

## Rebuild everything, including D-C

```bash
python -m polymarket_context.rebuild
```

This calls the existing real-data/manual-news seed pipeline and then the fine
chart builder. It overwrites derived outputs; keep reviews and verified imports
in separate files. Running the old `seed` or `pilot` commands alone can restore
the legacy dashboard; run `fine` afterward.

The conservative D-C export still uses its original earlier five-minute price
features. The exploratory D/C_candidate export remains explicitly not
training-eligible. Changing the chart does not silently change the training data.

For genuinely audited news, follow `docs/VERIFICATION.md`, then run:

```bash
python -m polymarket_context.pilot --stage dc --verified-documents verified_documents.jsonl
python -m polymarket_context.fine
```

The second command does not mutate D-C. Read `docs/FINE_DETECTION.md` for all
thresholds, formulas, missingness checks and accuracy limitations.
