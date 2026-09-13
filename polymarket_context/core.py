from __future__ import annotations
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class DetectorConfig:
    bin_minutes: int = 5
    horizon_minutes: int = 15
    baseline_hours: int = 24
    min_baseline_bins: int = 24
    jump_pp: float = 3.0
    rv_pp: float = 3.0
    z_threshold: float = 4.0
    scale_floor_pp: float = 0.5
    merge_minutes: int = 30

    def __post_init__(self) -> None:
        positive = [self.bin_minutes, self.horizon_minutes, self.baseline_hours,
                    self.min_baseline_bins, self.jump_pp, self.rv_pp,
                    self.z_threshold, self.scale_floor_pp]
        if not all(np.isfinite(x) and x > 0 for x in positive):
            raise ValueError('Detector settings must be finite and positive.')
        for field in ('bin_minutes','horizon_minutes','baseline_hours','min_baseline_bins','merge_minutes'):
            if not isinstance(getattr(self, field), int):
                raise ValueError(f'{field} must be an integer.')
        if self.horizon_minutes % self.bin_minutes:
            raise ValueError('horizon_minutes must be a multiple of bin_minutes.')
        if self.min_baseline_bins > self.baseline_hours * 60 // self.bin_minutes:
            raise ValueError('min_baseline_bins exceeds the baseline window.')
        if self.merge_minutes < 0:
            raise ValueError('merge_minutes cannot be negative.')

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_trades(path: str | Path, market_ids: list[str]) -> pd.DataFrame:
    """Read local extracts. Filtering rows does not guarantee few source bytes scanned."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.name.lower().endswith(('.csv','.csv.gz')):
        parts = []
        for frame in pd.read_csv(path, dtype={'market_id':str,'asset_id':str,'transaction_hash':str}, chunksize=250_000):
            parts.append(frame[frame.market_id.isin(market_ids)])
        return pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()
    if path.suffix.lower() == '.parquet' or path.is_dir():
        try:
            return pd.read_parquet(path,engine='pyarrow',filters=[('market_id','in',market_ids)])
        except ImportError as exc:
            raise RuntimeError('Parquet requires pyarrow: pip install pyarrow') from exc
    raise ValueError('Input must be a local CSV, CSV.GZ, Parquet or Parquet directory.')


def normalize_trades(frame: pd.DataFrame, input_kind: str) -> tuple[pd.DataFrame, dict]:
    """Normalize to outcome1 ONCE; preserve original cash notional and price."""
    if input_kind not in {'quant','trades'}:
        raise ValueError("input_kind must be 'quant' or 'trades', not 'users'.")
    if 'user' in frame.columns or 'role' in frame.columns:
        raise ValueError('User-level rows are not trade-level rows; do not double-count maker/taker.')
    needed = {'market_id','timestamp','price','token_amount','usd_amount'}
    if input_kind == 'trades':
        needed.add('nonusdc_side')
    if needed - set(frame):
        raise ValueError(f'Missing columns: {sorted(needed-set(frame))}')
    df = frame.copy()
    audit = {'input_rows':len(df),'input_kind':input_kind,'warnings':[]}
    df['market_id'] = df.market_id.astype(str)
    original_datetimes = pd.api.types.is_datetime64_any_dtype(df.timestamp)
    numeric_time = pd.to_numeric(df.timestamp,errors='coerce') if not original_datetimes else pd.Series(float('nan'),index=df.index)
    numeric = numeric_time.notna()
    parsed = pd.Series(pd.NaT,index=df.index,dtype='datetime64[ns, UTC]')
    parsed.loc[numeric] = pd.to_datetime(numeric_time[numeric],unit='s',utc=True,errors='coerce')
    for ix,val in df.loc[~numeric,'timestamp'].items():
        try:
            t = pd.Timestamp(val)
            if t.tzinfo is not None:
                parsed.loc[ix] = t.tz_convert('UTC')
        except (ValueError,TypeError):
            pass
    df['timestamp'] = parsed
    for col in ('price','token_amount','usd_amount'):
        df[col] = pd.to_numeric(df[col],errors='coerce')
    valid = (df.timestamp.notna() & df.price.between(0,1)
             & np.isfinite(df.token_amount) & df.token_amount.gt(0)
             & np.isfinite(df.usd_amount) & df.usd_amount.ge(0) & df.market_id.ne('nan'))
    if input_kind == 'trades':
        valid &= df.nonusdc_side.isin(['token1','token2'])
    audit['invalid_rows_removed'] = int((~valid).sum())
    df = df[valid].copy()
    df['price_observed'] = df.price
    df['price_outcome1'] = df.price
    if input_kind == 'trades':
        mask = df.nonusdc_side.eq('token2')
        df.loc[mask,'price_outcome1'] = 1-df.loc[mask,'price']
    # One transaction can contain many fills: identify logs, not just tx hashes.
    key = ['transaction_hash','log_index']
    if set(key) <= set(df) and not df[key].isna().any().any():
        if 'contract' in df:
            key = ['contract']+key
        duplicated = df[df.duplicated(key,keep=False)]
        if not duplicated.empty:
            checked = ['market_id','timestamp','price_outcome1','token_amount','usd_amount']
            if (duplicated.groupby(key)[checked].nunique(dropna=False)>1).any().any():
                raise ValueError('Conflicting records share a chain-log ID; inspect the extract.')
        before = len(df)
        df = df.drop_duplicates(key)
        audit['duplicate_logs_removed'] = before-len(df)
    else:
        audit['duplicate_logs_removed'] = 0
        audit['warnings'].append('Missing log identities: no deduplication performed.')
    df = df.sort_values(['market_id','timestamp'],kind='stable').reset_index(drop=True)
    audit['valid_rows'] = len(df)
    audit['warnings'].append('Notional and count are recorded-fill aggregates, not audited economic turnover.')
    if df.empty:
        raise ValueError('No valid rows remain after normalization.')
    return df,audit


def make_bars(trades: pd.DataFrame, config: DetectorConfig) -> pd.DataFrame:
    """Separate contracts; no forward filling or interpolation across empty bins."""
    frames = []
    freq = f'{config.bin_minutes}min'
    for market_id,group in trades.groupby('market_id',sort=True):
        g = group.copy()
        g['weighted_price'] = g.price_outcome1*g.token_amount
        bars = g.resample(freq,on='timestamp',label='right',closed='left').agg(
            weighted_price=('weighted_price','sum'),token_amount=('token_amount','sum'),
            recorded_notional_usd=('usd_amount','sum'),record_count=('price_outcome1','count'),
            low=('price_outcome1','min'),high=('price_outcome1','max'))
        bars['price'] = bars.weighted_price/bars.token_amount.replace(0,np.nan)
        bars['observed'] = bars.record_count.gt(0)
        bars['thin_bin'] = bars.record_count.lt(3)&bars.observed
        bars['market_id'] = market_id
        frames.append(bars.drop(columns='weighted_price').reset_index().rename(columns={'timestamp':'bin_end'}))
    return pd.concat(frames,ignore_index=True)


def _mad(values: np.ndarray) -> float:
    return float(np.nanmedian(np.abs(values-np.nanmedian(values))))


def detect_movements(bars: pd.DataFrame, config: DetectorConfig) -> tuple[pd.DataFrame,list[dict]]:
    """Heuristic alerts, not p-values. Baselines exclude the current return window."""
    k = config.horizon_minutes//config.bin_minutes
    window = config.baseline_hours*60//config.bin_minutes
    all_bars,episodes = [],[]
    for market_id,g in bars.groupby('market_id',sort=True):
        g = g.sort_values('bin_end').copy().reset_index(drop=True)
        delta = g.price.diff()*100
        complete = g.observed.rolling(k+1,min_periods=k+1).sum().eq(k+1)
        g['displacement_pp'] = ((g.price-g.price.shift(k))*100).where(complete)
        g['rv_pp'] = np.sqrt(delta.pow(2).rolling(k,min_periods=k).sum()).where(complete)
        for name,metric in [('jump',g.displacement_pp.abs()),('rv',g.rv_pp)]:
            past = metric.shift(k)
            rolling = past.rolling(window,min_periods=config.min_baseline_bins)
            median = rolling.median()
            scale = (1.4826*rolling.apply(_mad,raw=True)).clip(lower=config.scale_floor_pp)
            g[f'{name}_z'] = (metric-median)/scale
        g['baseline_ready'] = g.jump_z.notna()&g.rv_z.notna()
        g['jump_alert'] = g.displacement_pp.abs().ge(config.jump_pp)&g.jump_z.ge(config.z_threshold)
        g['volatility_alert'] = g.rv_pp.ge(config.rv_pp)&g.rv_z.ge(config.z_threshold)
        g['alert'] = g.jump_alert|g.volatility_alert
        g['score'] = g[['jump_z','rv_z']].max(axis=1)
        flagged = g[g.alert]
        clusters = []
        for ix in flagged.index:
            if not clusters or (g.loc[ix,'bin_end']-g.loc[clusters[-1][-1],'bin_end']).total_seconds()>config.merge_minutes*60:
                clusters.append([ix])
            else:
                clusters[-1].append(ix)
        for indices in clusters:
            first,last = g.loc[indices[0]],g.loc[indices[-1]]
            peak = g.loc[g.loc[indices,'score'].idxmax()]
            identifier = hashlib.sha256(f'{market_id}|{first.bin_end.isoformat()}'.encode()).hexdigest()[:16]
            lower = first.bin_end-pd.Timedelta(minutes=config.horizon_minutes+config.bin_minutes)
            episodes.append({'episode_id':identifier,'market_id':str(market_id),
                'window_start':lower.isoformat(),'detected_at':first.bin_end.isoformat(),
                'window_end':last.bin_end.isoformat(),'peak_at':peak.bin_end.isoformat(),
                'score':float(peak.score),'initial_displacement_pp':float(first.displacement_pp),
                'peak_displacement_pp':float(peak.displacement_pp),'peak_rv_pp':float(peak.rv_pp),
                'marker_price':float(first.price),
                'kind':'jump_and_volatility' if any(g.loc[indices,'jump_alert']) and any(g.loc[indices,'volatility_alert']) else ('jump' if any(g.loc[indices,'jump_alert']) else 'volatility'),
                'alert_bins':len(indices),'timing_note':'Coarse trade-bin window, not an identified information-arrival time.',
                'thin_bins_in_first_window':int(g.loc[max(0,indices[0]-k):indices[0],'thin_bin'].sum())})
        all_bars.append(g)
    return pd.concat(all_bars,ignore_index=True),episodes
