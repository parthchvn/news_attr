# Validation record

The development environment ran 32 passing tests and one skipped Parquet test (pyarrow unavailable locally). GitHub's Software tests workflow installs pyarrow and reruns the entire suite on the committed source. Its run result is authoritative for the uploaded code; do not infer it from this development note.

Coverage: raw token normalization; quant not inverted again; cash/share distinction; chain-log deduplication; conflicting logs rejected; users rows rejected; gaps; market separation; first-detection time; future-price invariance; timestamp uncertainty; late-news roles; strict text/time gates; keyword groups; API-key/cache safety; synthetic full dashboard; Parquet roundtrip; exchange summary exclusion; taker bundles; original token/action preservation; spike-only selection exclusion; future-news invariance; same-timestamp histories; target-price exclusion; calendar retrieval independence; RSS schema/budget; CSV.GZ and datetime input.

Software tests do not validate economic turnover, causal attribution, human identity, news completeness or real-data completion. See extraction_manifest.json and pilot_status.json when those real runs finish. Source/request errors and unsearched windows are retained. No actual market result should be described using synthetic test metrics.
