# Validation and execution record

The initial GitHub software run at commit 890f6531f6a39181751d0fa80f30e049cf31f7a6 passed 33 tests, including Parquet. Later commits add two exchange-registry tests and three manual-seed tests. Check the latest Actions run for its actual pass count.

Actual HF extraction succeeded and committed raw counts of 86,687 (507300) and 32,496 (2446852). One zero-share Inter record is excluded from price/action normalization. The real chart/D-C stage produced 98,627 taker execution bundles. The original RSS provider failed all 42 requests. Its initial output publication hit a concurrent branch-update error; the retained Actions artifact preserved the computation and failure provenance.

The Publish inspected-context pilot workflow rebuilds from actual trades, adds explicitly unverified inspected sources, retains failed-search provenance, and retries fast-forward publishing. It runs the tests on its generating commit and records that commit in outputs/two_markets/generating_commit.txt.

Coverage spans software contracts, not empirical causal validation: token normalization, cash/share distinction, exact-log deduplication, sparse bins, future invariance, timestamp gates, actor histories, execution grouping, candidate provenance, date-only report scoping and file roundtrips. No synthetic test is described as a finding for these real contracts. Source/request errors and unsearched periods are not silently called absence of news.
