# Adopted research protocol: incremental predictive value of news

Status: adopted design, **not** a frozen preregistration or a completed experiment. Source ingestion is implemented in this change; opportunity/model/evaluator interfaces below are requirements for subsequent implementation, not existing APIs. See `research_status.json`.

## 1. Target, not causal attribution

For the same held-out actor-market opportunities, compare log scores from a frozen non-text baseline and a controlled news extension. The target is incremental predictive value conditional on prior market state, actor history and timing, not article-induced behavior, individual exposure, total causal effect, optimal action or recovered reasoning.

At cutoff t, predict any eligible execution S in (t,t+h], then original YES/NO BUY/SELL action A conditional on S=1. Joint score:

```
log P(S | C) + S * log P(A | S=1, C)
```

The primary target should specify the first eligible executed-action bundle. If multiple distinguishable bundles have the earliest observed timestamp and cannot be temporally ordered, keep participation and mask the first-action component, with ambiguity counts reported. Never manufacture temporal order by sorting transaction hashes. The separately averaged action score must state its observed-action population. Size/aggressiveness is a separately specified later target.

For release j compute a weighted mean paired log-score difference over its common, coverage-certified opportunities. Average the release means for the release-balanced estimand; report an opportunity-weighted estimate separately. Publish participation and conditional-action components as well as the joint score on its eligible population. A positive score is not an acceptance requirement. With no accepted news or valid held-out experiment, the news increment is unavailable, not zero.

## 2. Sources and market selection

Start with a predeclared class of scheduled FOMC statements, using relevant contracts about later monetary-policy decisions that remain unresolved after each release. Verify actual market availability/liquidity before freezing the cohort. Do not invent contract IDs or choose only releases followed by spikes. BLS releases, court opinions and other official announcements need separate adapters; the Fed adapter does not implement them.

A contract resolved directly by an announcement is a factual-reading/ingestion test, not the primary semantic-generalization experiment. Publish two contrasts: release content beyond market/history/arrival timing; and prose beyond those variables plus structured release facts. Include prior consensus only with its own as-of provenance.

Audit unique source versions once and join them to many opportunities. Work scales with versions, not executions. Official origin alone does not certify an old text version. Current code implements collector-observed availability, not automated historical certification. See docs/PRIMARY_SOURCES.md.

## 3. Opportunities and risk set

Initial proposed grid: one-minute cutoffs with one-minute target intervals, frozen before final evaluation. The eligible actor-market population must be determined from prior information, not the actors that trade afterward. A prior-participation cohort is an explicit limited population, not a representation of all people or proof of human/bot identity. Record which contracts are open, the coverage universe and the risk-set rule at each cutoff.

No eligible execution is a recorded non-execution, not a deliberate decision to hold. Unfilled orders, original submission time and unobserved venues remain outside this target. Missing execution coverage censors the target interval; the mere presence of one trade does not establish completeness or permit a label of no trade elsewhere. First/last timestamps in a filtered Parquet file are not a coverage certificate. With subsampled negatives, retain selection probabilities and design weights. Baseline and news must be evaluated on identical opportunities.

Planned canonical interfaces in parthchvn/Polymarket: prior risk-set construction, coverage-aware opportunity construction, past-only feature generation, split validation, dormant-news gate and paired score reporting. **These are not implemented by this commit.** They will consume normalized execution bundles and explicit coverage. They must not certify unknown data or invent negative labels from gaps.

## 4. Strong shared baseline and dormant identity

Before text, select and freeze the strongest validated realistic non-news model from a recorded candidate set. The existing sports C (one earlier price bar and two actor counters) does not satisfy this requirement. Merely changing its bin width does not fix it.

Required feature families:

- Market levels, multi-horizon returns/variation/activity/signed execution flow, observation age and missingness.
- Actor activity, time since last execution, recent direction/size and positions only when actually observed; no fabricated outside-market portfolio.
- Contract identity, known deadline, clock, scheduled-release and observed-arrival timing.
- Best bid/ask, spread, depth, imbalance and recent changes when actually collected; explicit missingness otherwise.

All inputs and feature transformations must be usable strictly before t, including actual receipt and processing delays for forward replay. No target-window fills, final resolutions, retrospectively selected explanations or post-t responses are model inputs. Market responses before t may enter both models: the estimand is then a conditional predictive increment, not the statement's total causal effect.

Enforce exact dormant identity:

```
q_news(y | x, no_eligible_news) == q_base(y | x)
```

Freeze the baseline and apply a gated correction only when eligible news is present. An independently retrained empty-text model is not equivalent. Fit text transformations and correction parameters on training data, tune on validation, and freeze before untouched test events. Begin with a simple training-period representation rather than outcome-aware rationales. Record memorization/cutoff risks for any pretrained text encoder.

## 5. Splits, controls and uncertainty

Retain transaction hashes as atomic keys AND group all releases, related contracts, and syndicated versions of the same underlying information event together. Time-order train/validation/test and purge overlapping targets near boundaries. Report future prediction for known actors separately from unseen-actor evaluation. Actor, release and target-transaction IDs are split-audit metadata, not news features.

Required controls: timing/arrival metadata without text; structured release facts without prose; matched irrelevant text already available at the cutoff. Preserve the same version and availability policy in controls. Future text is permitted only in a labelled invalid leakage diagnostic, never an admissible placebo.

Report per-release deltas and uncertainty accounting for release- and actor-level dependence. Do not use per-fill IID standard errors. The uncertainty procedure must be specified and tested before the final holdout; it is not implemented here. Many executions joined to one release are not many independent semantic tests. One captured document is an ingestion milestone; a single held-out release yields at most a descriptive event-specific score. Generalization requires multiple independent held-out information events.

## 6. Detector and repository roles

`news_attr`: source adapters, version records, raw provenance, existing sports inspection. `parthchvn/Polymarket`: intended home for market collectors, canonical context/opportunity construction, baseline/extension models and evaluator. Do not duplicate incompatible as-of semantics. The existing reasoning-pipeline gates concern a different question and cannot certify Delta_news.

The detector is diagnostic, not a sample selector. Its overlap correction does not establish sensitivity or semantic relevance. A missed spike must not remove a release or a predetermined opportunity from the experiment. Do not expand detector work before addressing collection, opportunities and the baseline.

This adoption leaves legacy sports D-C intact. It does not deploy continuous collectors, create an opportunity dataset, fit a model, or provide empirical Delta_news. Neither a function nor a README entry proves successful execution: keep implementation, execution and research evidence separate.

## 7. Completion gates

1. Frozen source policy and release-to-market cohort; contracts survive the release; exact versions, clocks and source/market coverage retained.
2. Audited risk-set/opportunity counts, censored intervals, action ambiguity and sampling weights; frozen rows and split manifests.
3. Strong baseline selected and frozen; as-of feature/source checks, identical-row checks and dormant identity tests passing.
4. Prescribed controls, dependent uncertainty, per-release scores and limitations reported on untouched data.

Zero or negative findings are acceptable. An absent estimate is not a finding. The current smoke capture intentionally fetches an old Fed page now and refuses to backdate it: a successful HTTP request cannot establish historical eligibility.

## Source starting points

- Official statement: https://www.federalreserve.gov/newsevents/pressreleases/monetary20250507a.htm
- Official feed directory: https://www.federalreserve.gov/feeds/feeds.htm
- Order lifecycle: https://docs.polymarket.com/concepts/order-lifecycle
