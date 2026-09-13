# Auditing an information item before it enters C

A search/RSS date is a discovery hint, not an audited timestamp for the exact article version. Neither an LLM confidence score nor your finding a compelling explanation proves the document existed before the action.

For each useful candidate, recover the original publisher/post/feed or an authenticated archived version. Record the exact claim text whose availability you can support. Distinguish article publication from later updates, match event time, settlement time, collector receive time, and video upload time. Do not infer seconds from a date-only page; uncertainty must resolve conservatively before eligibility.

Use a JSONL record like the following **illustrative template**. Replace every placeholder with actual evidence; it is deliberately not accepted as a real verified record:

```json
{"document_id":"COPY_EXISTING_DOCUMENT_ID","url":"https://publisher.example/original","title":"SOURCE TITLE","snippet":"","published_at_claimed":null,"timestamp_status":"verified","verified_available_at":"REPLACE_WITH_TIMEZONE_AWARE_ISO_TIMESTAMP","verified_text":"EXACT SHORT AUDITED CLAIM TEXT","verification_evidence":"ARCHIVE OR PRIMARY-SOURCE URL; preserved version/hash; timestamp evidence and reviewer","discovery_modes":["calendar"],"market_ids":["507300"]}
```

Do not relabel `spike` discovery as `calendar` simply to pass the gate. Calendar means it was independently recovered by the fixed-window collection. `independent_manual` means the source selection was genuinely independent of the later target move. A source can be useful for retrospective attribution without qualifying for strict training context.

The runner merges verified fields into the matching document_id. Preserve the import file separately, since `--stage all --overwrite` rebuilds derived tables. Use:

```bash
python -m polymarket_context.pilot --stage dc --verified-documents verified_documents.jsonl
```

Then inspect `dc_manifest.json`: verified-news coverage should reflect actual eligible items. Empty lists are an honest result; do not manufacture timestamps to improve coverage.

For sports, structured live events may precede journalistic coverage. A goal's game-clock minute is not automatically a UTC public-availability timestamp. Use a defensible event/observation time and label uncertainty. A post-match report or later video is aftermath unless independently earlier information is recovered.

Human review categories (`plausible_context`, `background`, `aftermath`, `rejected`) describe candidate relevance to a retrospective episode. They do not certify causation, individual exposure, or strict pre-fill eligibility. Verify these separately.
