"""Fine-resolution execution-price diagnostics. Never infers executable quotes.

Individual alerts are immutable, causal records. News groups are a separate,
retrospective retrieval convenience. The legacy D-C/news exports are untouched.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FineConfig:
    bin_seconds: int = 30
    horizons_seconds: tuple[int, ...] = (30, 60, 180, 300, 900)
    min_change_pp: float = 1.0
    min_tail_change_pp: float = 0.2
    min_log_odds_change: float = 0.35
    min_variation_pp: float = 1.5
    logit_clip: float = 0.001
    min_transactions: int = 2
    min_shares: float = 5.0
    corroboration_pp: float = 0.5
    min_coverage: float = 0.6
    baseline_hours: int = 24
    min_baseline_samples: int = 30
    z_threshold: float = 4.0
    pp_scale_floor: float = 0.15
    logit_scale_floor: float = 0.05
    news_merge_seconds: int = 120
    news_max_span_seconds: int = 600

    def __post_init__(self) -> None:
        ints = ('bin_seconds', 'min_transactions', 'baseline_hours',
                'min_baseline_samples', 'news_merge_seconds', 'news_max_span_seconds')
        for name in ints:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        if not self.horizons_seconds or tuple(sorted(set(self.horizons_seconds))) != tuple(self.horizons_seconds):
            raise ValueError('horizons_seconds must be distinct and increasing')
        for h in self.horizons_seconds:
            if isinstance(h, bool) or not isinstance(h, int) or h < self.bin_seconds or h % self.bin_seconds:
                raise ValueError('Each horizon must be an integer multiple of bin_seconds')
        for name in ('min_change_pp', 'min_tail_change_pp', 'min_log_odds_change',
                     'min_variation_pp', 'min_shares', 'corroboration_pp', 'z_threshold',
                     'pp_scale_floor', 'logit_scale_floor'):
            if not np.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if not 0 < self.min_coverage <= 1 or not 0 < self.logit_clip < 0.5:
            raise ValueError('Invalid coverage or logit clipping parameter')

    @classmethod
    def from_dict(cls, value: dict) -> 'FineConfig':
        value = dict(value)
        if 'horizons_seconds' in value:
            value['horizons_seconds'] = tuple(value['horizons_seconds'])
        return cls(**value)

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()[:12]


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values, kind='stable')
    values, weights = np.asarray(values)[order], np.asarray(weights)[order]
    i = np.searchsorted(weights.cumsum(), weights.sum() / 2, side='left')
    return float(values[min(i, len(values) - 1)])


def make_fine_bars(trades: pd.DataFrame, cfg: FineConfig) -> pd.DataFrame:
    """Only observed bins; missing bins are never forward-filled.

    Multiple logs in one transaction count as ONE support observation. Weighted
    median limits the effect of small extreme fills, but is not a quote estimator.
    """
    needed = {'market_id', 'timestamp', 'price_outcome1', 'token_amount',
              'usd_amount', 'transaction_hash'}
    if needed - set(trades):
        raise ValueError(f'Missing fine-detector fields: {sorted(needed-set(trades))}')
    if trades.empty:
        raise ValueError('No trades supplied')
    if trades.transaction_hash.isna().any() or trades.transaction_hash.astype(str).str.strip().eq('').any():
        raise ValueError('Transaction identities are required for support checks')
    t = trades.copy()
    t['bin_end'] = t.timestamp.dt.floor(f'{cfg.bin_seconds}s') + pd.Timedelta(seconds=cfg.bin_seconds)
    t['weighted_price'] = t.price_outcome1 * t.token_amount
    rows = []
    for (mid, end), g in t.groupby(['market_id', 'bin_end'], sort=True):
        shares = float(g.token_amount.sum())
        median = weighted_median(g.price_outcome1.to_numpy(), g.token_amount.to_numpy())
        near = g.price_outcome1.sub(median).abs().le(cfg.corroboration_pp/100+1e-12)
        rows.append({'market_id': str(mid), 'bin_end': end,
                     'price': float(g.weighted_price.sum() / shares),
                     'median_price': median,
                     'corroborating_transactions': int(g.loc[near, 'transaction_hash'].nunique()),
                     'low': float(g.price_outcome1.min()), 'high': float(g.price_outcome1.max()),
                     'shares': shares, 'recorded_notional_usd': float(g.usd_amount.sum()),
                     'fill_count': len(g), 'transaction_count': int(g.transaction_hash.nunique()),
                     'first_fill_at': g.timestamp.min(), 'last_fill_at': g.timestamp.max()})
    bars = pd.DataFrame(rows)
    bars['supported'] = bars.corroborating_transactions.ge(cfg.min_transactions) & bars.shares.ge(cfg.min_shares)
    return bars


def past_baseline(metric: pd.Series, horizon: int, cfg: FineConfig,
                  floor: float) -> pd.DataFrame:
    """Reference observations end before the EARLIEST target price bin begins.

    A target ending at t uses bins [t-h-b,t-h) and [t-b,t). A historic return
    ending at s is eligible only when s <= t-h-b. Shift its availability by
    h+b, then use a true wall-clock rolling window (not an observation count).
    Evaluate on a union index so statistics expire even during gaps.
    """
    source = metric.dropna().copy()
    source.index = source.index + pd.Timedelta(seconds=horizon + cfg.bin_seconds)
    index = source.index.union(metric.index).sort_values()
    history = source.reindex(index)
    roll = history.rolling(pd.Timedelta(hours=cfg.baseline_hours),
                           min_periods=cfg.min_baseline_samples, closed='both')
    med = roll.median()
    scale = ((roll.quantile(.75) - roll.quantile(.25)) / 1.349).clip(lower=floor)
    return pd.DataFrame({'center': med, 'scale': scale}).reindex(metric.index)


def detect_fine(bars: pd.DataFrame, cfg: FineConfig) -> tuple[pd.DataFrame, list[dict]]:
    """Return all horizon diagnostics and ONE record per candidate timestamp.

    supported_change = size + transaction/share/coverage evidence;
    unusual_change = the above + past-only robust z threshold.
    Neither is a calibrated p-value or a verified information event.
    """
    diagnostics, alerts = [], []
    for mid, group in bars.groupby('market_id', sort=True):
        g = group.sort_values('bin_end').set_index('bin_end')
        p = g.median_price.astype(float)
        lp = np.log(p.clip(cfg.logit_clip, 1-cfg.logit_clip) /
                    (1-p.clip(cfg.logit_clip, 1-cfg.logit_clip)))
        consecutive = p.index.to_series().diff().dt.total_seconds().eq(cfg.bin_seconds)
        step_supported = g.supported & g.supported.shift(1, fill_value=False) & consecutive
        step2 = (p.diff()*100).pow(2).where(step_supported)
        candidates = {}
        for h in cfg.horizons_seconds:
            ref = g.reindex(g.index - pd.Timedelta(seconds=h))
            ref.index = g.index
            n = h//cfg.bin_seconds+1
            coverage = pd.Series(1., index=g.index).rolling(f'{h+cfg.bin_seconds}s').sum()/n
            endpoints = g.supported & ref.supported.fillna(False).astype(bool)
            usable = endpoints & coverage.ge(cfg.min_coverage-1e-9)
            change = (p-ref.median_price)*100
            reference_logit = np.log(ref.median_price.clip(cfg.logit_clip, 1-cfg.logit_clip) /
                                     (1-ref.median_price.clip(cfg.logit_clip, 1-cfg.logit_clip)))
            log_change = lp-reference_logit
            # Variation is evaluated only over fully observed, supported steps.
            rv_count = step2.rolling(f'{h}s').count()
            rv = np.sqrt(step2.rolling(f'{h}s').sum()).where(rv_count.eq(h//cfg.bin_seconds))
            scale_h = np.sqrt(max(1., h/60))
            jump_size = change.abs().ge(cfg.min_change_pp*scale_h-1e-9)
            tail = ((p.le(.1) | p.ge(.9) | ref.median_price.le(.1) | ref.median_price.ge(.9)) &
                    change.abs().ge(cfg.min_tail_change_pp-1e-9) &
                    log_change.abs().ge(cfg.min_log_odds_change*scale_h-1e-12))
            rv_size = rv.ge(cfg.min_variation_pp*scale_h-1e-9)
            zs = {}
            for key, metric, floor in [('jump', change.abs(), cfg.pp_scale_floor),
                                       ('logit', log_change.abs(), cfg.logit_scale_floor),
                                       ('variation', rv, cfg.pp_scale_floor)]:
                baseline = past_baseline(metric.where(usable), h, cfg, floor)
                zs[key] = (metric-baseline.center)/baseline.scale
            candidate = usable & (jump_size | tail | rv_size)
            unusual = candidate & ((jump_size & zs['jump'].ge(cfg.z_threshold)) |
                                    (tail & zs['logit'].ge(cfg.z_threshold)) |
                                    (rv_size & zs['variation'].ge(cfg.z_threshold)))
            d = pd.DataFrame({'market_id': str(mid), 'horizon_seconds': h,
                'change_pp': change, 'log_odds_change': log_change, 'variation_pp': rv,
                'coverage': coverage, 'endpoints_supported': endpoints,
                'eligible': usable, 'jump_z': zs['jump'], 'logit_z': zs['logit'],
                'variation_z': zs['variation'], 'candidate': candidate, 'unusual': unusual}, index=g.index)
            diagnostics.append(d.reset_index())
            for time in g.index[candidate]:
                rec = d.loc[time]
                record = {'horizon_seconds': h,
                    'window_start': (time-pd.Timedelta(seconds=h+cfg.bin_seconds)).isoformat(),
                    'reference_price': float(ref.loc[time, 'median_price']),
                    'change_pp': float(change.loc[time]),
                    'log_odds_change': float(log_change.loc[time]),
                    'variation_pp': float(rv.loc[time]) if pd.notna(rv.loc[time]) else None,
                    'coverage': float(coverage.loc[time]),
                    'signals': [name for name, values in [('net_change', jump_size), ('tail_log_odds', tail),
                                                           ('variation', rv_size)] if values.loc[time]],
                    'jump_z': finite(zs['jump'].loc[time]), 'logit_z': finite(zs['logit'].loc[time]),
                    'variation_z': finite(zs['variation'].loc[time]),
                    'unusual': bool(unusual.loc[time])}
                candidates.setdefault(time, []).append(record)
        for time, signals in sorted(candidates.items()):
            row = g.loc[time]
            alert_id = hashlib.sha256(f'fine-v2|{cfg.fingerprint}|{mid}|{time.isoformat()}'.encode()).hexdigest()[:20]
            alerts.append({'alert_id': alert_id, 'market_id': str(mid), 'detected_at': time.isoformat(),
                'window_start': min(s['window_start'] for s in signals),
                'price': float(row.price), 'median_price': float(row.median_price),
                'transaction_count': int(row.transaction_count),
                'corroborating_transactions': int(row.get('corroborating_transactions', row.transaction_count)),
                'shares': float(row.shares),
                'tier': 'unusual_change' if any(s['unusual'] for s in signals) else 'supported_change',
                'baseline_note': 'past_only_reference' if any(s['jump_z'] is not None for s in signals)
                                 else 'insufficient_history_size_only',
                'horizons_seconds': [s['horizon_seconds'] for s in signals], 'signals': signals,
                'causal_attribution': 'not_established', 'config_fingerprint': cfg.fingerprint})
    return pd.concat(diagnostics, ignore_index=True), alerts


def finite(x: Any) -> float | None:
    return float(x) if pd.notna(x) and np.isfinite(x) else None


def news_groups(alerts: list[dict], cfg: FineConfig) -> list[dict]:
    """Bounded grouping, never suppression of alert markers or causal labelling."""
    groups = []
    by_market = {}
    for a in sorted(alerts, key=lambda a: (a['market_id'], a['detected_at'])):
        mid, time = a['market_id'], pd.Timestamp(a['detected_at'])
        last = by_market.get(mid)
        if (last is None or (time-pd.Timestamp(last['last_detection'])).total_seconds() > cfg.news_merge_seconds
                or (time-pd.Timestamp(last['first_detection'])).total_seconds() > cfg.news_max_span_seconds):
            last = {'group_id': 'group-'+a['alert_id'], 'market_id': mid,
                    'first_detection': a['detected_at'], 'last_detection': a['detected_at'],
                    'window_start': a['window_start'], 'alert_ids': [],
                    'purpose': 'retrieval_deduplication_not_independent_event'}
            groups.append(last)
            by_market[mid] = last
        last['last_detection'] = a['detected_at']
        last['window_start'] = min(last['window_start'], a['window_start'])
        last['alert_ids'].append(a['alert_id'])
    return groups


def known_context(alerts: list[dict], legacy_episodes: list[dict], legacy_links: list[dict]) -> list[dict]:
    """Expose existing source candidates ONLY within their old manual scope.

    This is not a new source retrieval, timestamp audit or causal attribution.
    """
    links_by_episode = {}
    for link in legacy_links:
        links_by_episode.setdefault(link['episode_id'], []).append(link)
    output = []
    for a in alerts:
        seen = set()
        for e in legacy_episodes:
            if e['market_id'] != a['market_id'] or not pd.Timestamp(e['window_start']) <= pd.Timestamp(a['detected_at']) <= pd.Timestamp(e['window_end']):
                continue
            for link in links_by_episode.get(e['episode_id'], []):
                did = link['document_id']
                if did in seen:
                    continue
                seen.add(did)
                pub = link.get('published_at_claimed')
                if link.get('context_type') == 'retrospective_match_report':
                    role = 'aftermath_not_pre_move_evidence'
                elif not pub:
                    role = 'unknown_ordering_date_only'
                else:
                    pt = pd.Timestamp(pub)
                    if pt.tzinfo is None:
                        role = 'unknown_timezone'
                    else:
                        role = ('before_window_claim_only' if pt < pd.Timestamp(a['window_start']) else
                                'after_detection' if pt >= pd.Timestamp(a['detected_at']) else
                                'within_window_ambiguous')
                output.append({'alert_id': a['alert_id'], 'market_id': a['market_id'], 'document_id': did,
                    'legacy_episode_id': e['episode_id'], 'temporal_role': role,
                    'relation': 'existing_manual_scope_overlap_NOT_new_attribution',
                    'training_eligible': False})
    return output


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(''.join(json.dumps(r, ensure_ascii=False, allow_nan=False)+'\n' for r in rows))


def build(config_path: Path, *, bin_seconds: int | None = None,
          data_override: Path | None = None) -> dict:
    from .core import load_trades, normalize_trades
    from .dc import participant_fills
    from .fine_report import write_report

    config_path = config_path.resolve()
    config = json.loads(config_path.read_text())
    root = config_path.parent
    cfg = FineConfig.from_dict(config.get('fine_detector', {}))
    if bin_seconds is not None:
        cfg = replace(cfg, bin_seconds=bin_seconds)
    data_path = (data_override or root/config['data_path']).resolve()
    output = root/config.get('fine_output_dir', 'outputs/two_markets/fine')
    legacy = root/config.get('output_dir', 'outputs/two_markets')
    output.mkdir(parents=True, exist_ok=True)
    ids = [str(m['market_id']) for m in config['markets']]
    metadata = {str(m['id']): m for m in json.loads((root/config['markets_metadata_path']).read_text())}
    for m in config['markets']:
        if metadata[m['market_id']]['answer1'] != m['outcome1_label'] or metadata[m['market_id']]['question'] != m['question']:
            raise ValueError('Metadata mismatch: '+m['market_id'])
    raw = load_trades(data_path, ids)
    raw, participant_audit = participant_fills(raw)
    trades, normalization_audit = normalize_trades(raw, config.get('input_kind', 'trades'))
    print(f'Building {cfg.bin_seconds}-second bars from {len(trades):,} fills', flush=True)
    bars = make_fine_bars(trades, cfg)
    metrics, alerts = detect_fine(bars, cfg)
    groups = news_groups(alerts, cfg)
    legacy_episodes = read_jsonl(legacy/'episodes.jsonl')
    links = known_context(alerts, legacy_episodes, read_jsonl(legacy/'attribution_links.jsonl'))
    documents = read_jsonl(legacy/'documents.jsonl')
    jobs = []
    markets = {m['market_id']: m for m in config['markets']}
    for group in groups:
        for query in markets[group['market_id']].get('search_queries', []):
            jobs.append({'group_id': group['group_id'], 'market_id': group['market_id'],
                'query': query, 'window_start': group['window_start'],
                'search_start': (pd.Timestamp(group['window_start'])-pd.Timedelta(minutes=30)).isoformat(),
                'search_end': (pd.Timestamp(group['last_detection'])+pd.Timedelta(minutes=10)).isoformat(),
                'status': 'planned_not_executed', 'post_window_results_are_aftermath': True})
    write_jsonl(output/'alerts.jsonl', alerts)
    write_jsonl(output/'news_groups.jsonl', groups)
    write_jsonl(output/'search_jobs.jsonl', jobs)
    write_jsonl(output/'legacy_context_links.jsonl', links)
    bars.to_csv(output/'bars.csv.gz', index=False, compression={'method': 'gzip', 'mtime': 0})
    metrics.to_csv(output/'diagnostics.csv.gz', index=False, compression={'method': 'gzip', 'mtime': 0})
    flat = [{k:v for k,v in a.items() if k not in {'signals','horizons_seconds'}} |
            {'horizons_seconds': ','.join(map(str,a['horizons_seconds']))} for a in alerts]
    pd.DataFrame(flat, columns=['alert_id','market_id','detected_at','window_start','price','median_price',
        'transaction_count','corroborating_transactions','shares','tier','baseline_note','causal_attribution','config_fingerprint',
        'horizons_seconds']).to_csv(output/'alerts.csv', index=False)
    summary = {'detector_version': 'fine-v2', 'configuration': asdict(cfg),
        'normalization_audit': normalization_audit, 'participant_audit': participant_audit,
        'source_sha256': hashlib.sha256(data_path.read_bytes()).hexdigest(),
        'source_path': str(data_path.relative_to(root)) if data_path.is_relative_to(root) else data_path.name,
        'markets': {}, 'review_windows': [], 'news_queries_executed': 0,
        'strict_dc_modified': False,
        'interpretation': 'Finer recorded-price diagnostics, not validated causal spikes, quotes or new news.'}
    for mid in ids:
        aa = [a for a in alerts if a['market_id']==mid]
        mm = metrics[metrics.market_id.eq(mid)]
        bb = bars[bars.market_id.eq(mid)]
        old = [e for e in legacy_episodes if e['market_id']==mid]
        total_slots = int((bb.bin_end.max()-bb.bin_end.min()).total_seconds()/cfg.bin_seconds)+1
        summary['markets'][mid] = {
            'valid_fills': int(trades.market_id.eq(mid).sum()), 'observed_bins': len(bb),
            'empty_bins_not_imputed': total_slots-len(bb), 'supported_bins': int(bb.supported.sum()),
            'tested_horizon_windows': int(mm.eligible.sum()), 'individual_alert_times': len(aa),
            'unusual_alert_times': sum(a['tier']=='unusual_change' for a in aa),
            'supported_size_only_times': sum(a['tier']=='supported_change' for a in aa),
            'news_groups': sum(g['market_id']==mid for g in groups),
            'legacy_episode_dots': len(old), 'legacy_alert_bins': sum(e['alert_bins'] for e in old)}
    for window in config.get('review_windows', []):
        start, end = pd.Timestamp(window['start']), pd.Timestamp(window['end'])
        selected = [a for a in alerts if a['market_id']==window['market_id'] and start < pd.Timestamp(a['detected_at']) <= end]
        summary['review_windows'].append({**window, 'individual_alert_times': len(selected),
            'unusual_alert_times': sum(a['tier']=='unusual_change' for a in selected),
            'short_horizon_alert_times': sum(any(h<=60 for h in a['horizons_seconds']) for a in selected)})
    (output/'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False))
    write_report(bars, trades, alerts, groups, links, documents, config, cfg, summary, output/'dashboard.html')
    # Replace the familiar entry point, retaining the old source-review report.
    old_dashboard = legacy/'dashboard.html'
    legacy_copy = legacy/'dashboard_legacy.html'
    if old_dashboard.exists() and 'fine-v2-entry' not in old_dashboard.read_text()[:1000]:
        legacy_copy.write_bytes(old_dashboard.read_bytes())
    # Embed the complete fine dashboard: opens offline even downloaded by itself.
    old_dashboard.parent.mkdir(parents=True, exist_ok=True)
    old_dashboard.write_bytes((output/'dashboard.html').read_bytes())
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, default=Path('config.two_markets.json'))
    p.add_argument('--bin-seconds', type=int, help='Override e.g. 15; every horizon must be divisible by it')
    p.add_argument('--data', type=Path, help='Optional local CSV/CSV.GZ extract')
    a = p.parse_args()
    build(a.config, bin_seconds=a.bin_seconds, data_override=a.data)


if __name__ == '__main__':
    main()
