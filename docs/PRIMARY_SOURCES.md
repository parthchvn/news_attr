# Source policy and version contract

The new adapter supports Federal Reserve FOMC statement HTML only. Unknown layouts fail closed. It is not a generic news verifier, court parser or BLS vintage service.

## Forward capture (implemented)

Run `python -m polymarket_context.primary --plan configs/primary_forward.json --output runs/primary-forward --watch` on an operator-managed machine. One process owns each output directory; do not run concurrent writers. Keep durable storage, synchronized host clocks, process supervision and market collection running separately. No daemon has been deployed by adding this command. A single GitHub Actions smoke cycle is not continuous collection.

The plan is recorded before requests. The official feed selects statement links mechanically, without prices or target labels. Responses are stored by SHA-256. Extracted text is a deterministic HTML/entity/whitespace normalization of source paragraphs, not an LLM summary. The parser extracts through the voting paragraphs and records its version. Updates produce new document versions; identical captures retain their first stored availability.

`usable_at = features_ready_at >= received_at >= request_started_at`. Only `usable_at < cutoff` qualifies. Hashes certify stored bytes and their transformation under a trusted collector clock, not the publisher's actual first dissemination time. They are integrity checks, not a cryptographic attestation against a dishonest collector. Downstream embeddings or other transformations must carry their own later readiness time; HTML receipt does not prove those features were available.

The record's `xvi.information.v1` fields include document/event IDs, source URL, plan and raw hashes, request/receipt/processing times, usable_at, availability_basis, exact extracted text and text hash, and extractor version. `validate_record` re-reads snapshots, re-extracts text and checks the recorded plan/time chain. `eligible_at` adds the strict cutoff check. Source-to-market relevance requires a separately frozen mapping; the smoke record deliberately has `market_ids=[]`.

Output: plans.jsonl, cycles.jsonl, information.jsonl, status.json, raw/<sha>.bin. Preserve the entire directory. Failures and unsupported layouts are errors, never dummy information. Feed polling is a snapshot observation, not proof of complete coverage. Downtime and missing feed items can reduce recall. Negative execution labels require separate market-coverage certification.

## Historical reconstruction (not automated)

An official schedule and old dated page do not prove today's exact text existed then. An acceptable historical policy requires source-specific evidence about versions, corrections and availability, with conservative uncertainty and independently defined selection. The current adapter never assigns historical_usable_at, even to an old official page. docs/VERIFICATION.md remains applicable to manually audited historical information; it is not relaxed by this change.

Verification is once per unique version, reused by many as-of joins, not once per execution. All models and controls must follow the same availability policy.

## Planned canonical handoff

A future integration will validate forward versions, map them to the frozen market cohort, and pass document/event IDs, hashes, usable_at and feature readiness into the canonical as-of builder. That integration and the news-value evaluator are **not implemented here**. Do not silently import unassigned monetary-policy sources into the sports D-C export or relabel spike candidates.

## Smoke-test interpretation

configs/primary_smoke.json selects May 7, 2025 solely as an adapter test. A record captured now is usable only after the current capture, not for May 2025 trades. A passing smoke run adds no matched historical opportunities and no empirical news delta. Workflow artifacts retain snapshots/status, including source errors. No continuous collection is claimed.
