# XVI — release-first information and decision context

**Research priority: measure the out-of-sample predictive value of timestamp-eligible news, not generate more spike explanations.** The sports price dashboard remains an engineering fixture. It is not evidence that text improves decision prediction.

Start with [RESEARCH.md](RESEARCH.md), [implementation status](research_status.json), and [the source policy](docs/PRIMARY_SOURCES.md).

## Ownership and current status

`news_attr` owns information ingestion, immutable source versions, provenance and retrospective inspection. The existing [parthchvn/Polymarket](https://github.com/parthchvn/Polymarket) toolkit is the intended home of opportunity construction, strong baselines and the new evaluator. **That evaluator is a planned integration, not an implemented or tested feature of this commit.** No second model-training stack is maintained here.

| Component | Status |
|---|---|
| Real sports trades and fine-resolution dashboard | Existing, preserved diagnostic fixture |
| Official FOMC statement capture and forward eligibility validator | Implemented in `polymarket_context/primary.py`; exact snapshots, receipt/processing clocks, hashes, independent source plan |
| Source capture tests and one-cycle smoke workflow | Added; check actual Actions results rather than inferring execution from source code |
| Continuous deployed news AND market collectors | **Not deployed by this change**; a watch command is not a running service |
| Coverage-aware opportunities and strong fitted baseline | **Planned, not completed** |
| Dormant-news identity, split audits and controlled evaluator | **Specified in the protocol, not implemented here** |
| Held-out empirical news increment with dependent uncertainty | **Not measured**; zero accepted historical news is not a zero-effect result |

## Primary-source ingestion

```bash
python -m pip install -e '.[parquet,dev]'
python -m pytest -q

# One real capture: old official statement, observed NOW, never backdated.
python -m polymarket_context.primary --plan configs/primary_smoke.json --output runs/primary-smoke

# Optional operator-run forward process. Keep its host and storage running.
python -m polymarket_context.primary --plan configs/primary_forward.json --output runs/primary-forward --watch
```

Each captured version contains exact extracted statement text, a raw snapshot, two hashes, the recorded source-selection plan, request/receive/processing times and `usable_at`. Eligibility is **`usable_at < cutoff`**. Unsupported layouts and failed requests are recorded, not filled with synthetic content. A capture of a 2025 page today is eligible only after today's capture, never for 2025 trades. It remains unassigned to markets until a cohort/relevance policy is approved.

The official-feed adapter is independent of prices and runs once by default. Polling does not prove complete feed coverage or uninterrupted collection. Original market-book/trade collection stays in the canonical toolkit; it is not duplicated here. No orders, keys, trading, or paid services are used by this adapter.

The **Release-first source capture** workflow runs software tests and one real source capture. It does not start a persistent collector. It retains raw snapshots, status and errors as workflow artifacts; successful captures are also published under `outputs/primary_smoke/`. Consult that directory's status and generating commit for evidence of an actual run.

## Research path

Use scheduled primary-source releases and contracts about **later, still-unresolved policy decisions**. Keep every predetermined release window, including quiet ones. Construct fixed-grid actor-market opportunities from past-known participation and coverage; model participation and conditional action separately. Freeze a strong market/history/timing baseline, then evaluate text on the same opportunities with exact dormant-context identity, event/time/transaction/actor split audits and controls. Details and incomplete acceptance gates are in [RESEARCH.md](RESEARCH.md).

## Existing sports dashboard

Existing files and commands have not been removed or silently reinterpreted:

```bash
open outputs/two_markets/dashboard.html
# Rebuild prices only when needed:
python -m polymarket_context.fine
```

[SPORTS_PILOT.md](SPORTS_PILOT.md) preserves the previous README and its reproduction instructions. [QUICKSTART.md](QUICKSTART.md) describes the sports fixture. Fine detector development is frozen for the research milestone: it does **not** choose eligible releases, prediction opportunities or news-training rows. Legacy D-C files remain execution-only and cannot implement the new estimand without opportunity reconstruction.
