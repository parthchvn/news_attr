# Recovering repeated HTML records and rejected FOMC layouts

This supersedes the raw-HTML document-identity description in the initial source policy. No original capture is deleted or backdated.

## What the user audit exposed

104 cycles each contained at least one error. 206 accepted records represented only two events (March 18 and April 29, 2026), each with one distinct extracted text. Passing validation applies to accepted records only, not completeness of collection. An error count of 206 is a number of parsing failures, not an HTTP 206 status.

The old identity included the entire HTML hash. A changed page wrapper therefore produced another information record even with identical extracted statement text. The old parser also required the named supporters paragraph. The official June 17 and July 29, 2026 statements use a vote tally before the policy text rather than that paragraph. Merely removing all validation would be the wrong repair.

## v3 changes

- Accept the observed vote-tally layout only with a release header, tally, policy-decision paragraph, sufficient statement content, and explicit end boundary. Keep the original named-voter extraction stable for legacy validation; dissent remains in the text.
- Identify unique content by source URL, release header and exact extracted-text hash. Raw HTML changes alone do not create information records. Different releases or genuinely changed text remain distinct.
- Preserve every new fetched response in `observations.jsonl`, including raw snapshot/hash, receipt/processing clocks, failures, and canonical content ID. An A-to-B-to-A sequence remains visible there, though A is only one unique content version.
- Keep `information.jsonl` append-only. `information_unique.jsonl` is a derived view of the earliest accepted record for each content identity; `version_aliases.jsonl` maps all old IDs to it. Original availability is preserved exactly, not moved to the publisher's date. No historical parse failure is silently promoted at its earlier receipt time.
- Distinguish unique documents, original information-record count, selected URLs, unchanged content, latest-cycle errors and accumulated historical errors. A feed returning zero matching statements is explicitly not a successful populated capture.

## Safe local recovery

Stop the collector with Control+C before updating or auditing. One writer per directory; no concurrent audit. Preserve the entire directory first:

```bash
cd /Users/parth/news_attr
tar -czf "primary-forward-backup-$(date +%Y%m%d-%H%M%S).tar.gz" runs/primary-forward &&
git pull --ff-only &&
source .venv/bin/activate &&
python -m pytest -q

python -m polymarket_context.primary_audit --input runs/primary-forward
```

The last command validates all original records, writes audit.json, and creates the unique/alias views without editing the source log or raw files. With the reported run and unchanged release headers, expect 206 original records, 2 unique content versions, and 204 redundant records. Invalid data prevents refreshing the unique view; inspect errors without deleting evidence.

Next run two single cycles against the SAME directory:

```bash
python -m polymarket_context.primary --plan configs/primary_forward.json --output runs/primary-forward &&
python -m polymarket_context.primary --plan configs/primary_forward.json --output runs/primary-forward
python -m json.tool runs/primary-forward/status.json
python -m polymarket_context.primary_audit --input runs/primary-forward
```

A successful latest cycle has status=complete, errors=[], and selected_statements>0. An unchanged second pass has records_added=0 and unchanged_documents equal to the number of successfully checked unchanged statements. A real content change is allowed to add a version. `documents` now counts UNIQUE source/text/header versions; `information_records` retains the original append-log count. Do not expect old cycles_with_errors to reset after repair. Look at latest_cycle_status/errors for the repaired run.

The first repaired pass may capture previously rejected statements. Their usable_at is their new capture/processing time, not the earlier failed attempt or original release date. This patch does not automatically reconstruct historic eligibility from raw files.

Resume --watch only after a clean bounded check. DNS/network failures are still logged; this patch cannot guarantee the local connection or future publisher layouts. Several hours of polling unchanged old statements is not several hours of new announcements. No market trades/books or D-C rows are created by this collector.

## Tests and real check

Synthetic regressions cover identical text with changed HTML, source identity, content revisions, legacy 103-record deduplication, timestamp preservation, retained dissent, malformed/truncated layouts, partial successes, DNS failures, and unchanged original files. The `Primary feed recovery check` workflow additionally fetches the actual official feed twice and saves complete snapshots and audit results. It is bounded, not a deployed continuous service. Actual success and counts must come from its run/status, not this document.

Official format evidence:
https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617a.htm
https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm
