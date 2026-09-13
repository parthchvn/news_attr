"""D-C export with explicit execution proxies and no hindsight labels in C."""
from __future__ import annotations
from collections import defaultdict
from bisect import bisect_left
import gzip
import hashlib
import json
from pathlib import Path
import math
import pandas as pd
from .news import aware_time, verified_available_at, keyword_relevance, canonical_url


def participant_fills(frame: pd.DataFrame) -> tuple[pd.DataFrame,dict]:
    """Exclude known exchange summary legs, not all smart-contract wallets."""
    df = frame.copy()
    excluded = pd.Series(False,index=df.index)
    exchanges = {str(v).lower() for v in df.get('contract',[]) if pd.notna(v)}
    exchanges.add('0x'+'0'*40)
    for col in ('maker','taker'):
        if col in df:
            excluded |= df[col].astype(str).str.lower().isin(exchanges)
    return df[~excluded].copy(),{'exchange_summary_rows_removed':int(excluded.sum()),
        'filter_rule':'maker or taker is one of the observed exchange contracts or zero address',
        'human_bot_classification':'not_available'}


def decisions_from_fills(trades: pd.DataFrame) -> pd.DataFrame:
    """Taker/transaction/market/token/direction bundles, not inferred order decisions."""
    required = {'transaction_hash','taker','taker_direction','nonusdc_side','market_id',
                'timestamp','price_observed','price_outcome1','token_amount','usd_amount'}
    if required-set(trades):
        raise ValueError('D-C needs raw trades.parquet columns: '+str(sorted(required-set(trades))))
    df,_ = participant_fills(trades)
    if df.empty:
        raise ValueError('No participant fills available for D-C export')
    for col in ('transaction_hash','taker'):
        if df[col].isna().any() or df[col].astype(str).str.strip().eq('').any():
            raise ValueError('Missing '+col+'; cannot construct execution identities')
    if not df.taker_direction.isin(['BUY','SELL']).all():
        raise ValueError('Unknown taker_direction')
    if (df.groupby('transaction_hash').timestamp.nunique()>1).any():
        raise ValueError('One transaction has conflicting timestamps')
    df['taker'] = df.taker.str.lower()
    df['weighted_price'] = df.price_observed*df.token_amount
    df['weighted_outcome1'] = df.price_outcome1*df.token_amount
    keys = ['transaction_hash','market_id','taker','nonusdc_side','taker_direction']
    d = df.groupby(keys,sort=True).agg(timestamp=('timestamp','min'),shares=('token_amount','sum'),
        recorded_notional_usd=('usd_amount','sum'),weighted_price=('weighted_price','sum'),
        weighted_outcome1=('weighted_outcome1','sum'),fill_count=('token_amount','size')).reset_index()
    d['execution_price'] = d.weighted_price/d.shares
    d['outcome1_equivalent_price'] = d.weighted_outcome1/d.shares
    d['direction_outcome1'] = d.taker_direction
    no = d.nonusdc_side.eq('token2')
    d.loc[no,'direction_outcome1'] = d.loc[no,'taker_direction'].map({'BUY':'SELL','SELL':'BUY'})
    d['decision_id'] = d.apply(lambda r: hashlib.sha256('|'.join(str(r[k]) for k in keys).encode()).hexdigest()[:24],axis=1)
    return d.drop(columns=['weighted_price','weighted_outcome1']).sort_values(['timestamp','decision_id'],kind='stable').reset_index(drop=True)


def eligible_news(documents: list[dict], market: dict, cutoff: pd.Timestamp,
                  *, strict: bool, lookback_hours: int=72, limit: int=8) -> list[dict]:
    """No episode membership, subsequent returns or resolution input."""
    output = []
    for d in documents:
        if strict:
            modes = set(d.get('discovery_modes',[]))
            if not modes.intersection({'calendar','independent_manual'}):
                continue
            available = verified_available_at(d)
            if keyword_relevance(d,market,verified_only=True)!=1.0:
                continue
            text = d.get('verified_text','')
        else:
            available = aware_time(d.get('published_at_claimed'))
            if keyword_relevance(d,market)!=1.0:
                continue
            text = d.get('title','')
        if available is None or not cutoff-pd.Timedelta(hours=lookback_hours)<=available<cutoff:
            continue
        output.append({'document_id':d['document_id'],'url':canonical_url(d['url']),
            'available_at' if strict else 'published_at_claimed':available.isoformat(),
            'text':text,'timestamp_verified':strict,'discovery_modes':d.get('discovery_modes',[]),
            **({'verification_evidence':d['verification_evidence']} if strict else
               {'warning':'Research candidate only: publication/text version not verified; selection may use later spikes.'})})
    field = 'available_at' if strict else 'published_at_claimed'
    output.sort(key=lambda d:(d[field],d['document_id']),reverse=True)
    seen,result = set(),[]
    for d in output:
        if d['url'] not in seen:
            result.append(d);seen.add(d['url'])
        if len(result)>=limit:
            break
    return result


class NewsIndex:
    """Precompute relevance once; as-of lookup is O(log n + returned items)."""
    def __init__(self, documents: list[dict], market: dict, strict: bool):
        self.strict = strict
        entries = []
        for d in documents:
            if strict:
                if not set(d.get('discovery_modes',[])).intersection({'calendar','independent_manual'}):
                    continue
                t = verified_available_at(d)
                relevance = keyword_relevance(d,market,verified_only=True)
            else:
                t = aware_time(d.get('published_at_claimed'))
                relevance = keyword_relevance(d,market)
            if t is not None and relevance==1.0:
                item = eligible_news([d],market,t+pd.Timedelta(nanoseconds=1),strict=strict)
                if item:
                    entries.append((t,d['document_id'],item[0]))
        entries.sort(key=lambda x:(x[0],x[1]))
        self.times = [x[0] for x in entries]
        self.items = [x[2] for x in entries]

    def at(self, cutoff: pd.Timestamp, hours: int, limit: int) -> list[dict]:
        i = bisect_left(self.times,cutoff)-1
        lower = cutoff-pd.Timedelta(hours=hours)
        result,seen = [],set()
        while i>=0 and self.times[i]>=lower and len(result)<limit:
            item = self.items[i]
            if item['url'] not in seen:
                result.append(item);seen.add(item['url'])
            i -= 1
        return result


def export_dc(trades: pd.DataFrame, bars: pd.DataFrame, documents: list[dict], config: dict, output: Path) -> dict:
    decisions = decisions_from_fills(trades)
    settings = config.get('dc',{})
    lookback = int(settings.get('news_lookback_hours',72))
    max_items = int(settings.get('max_news_items',8))
    stale_minutes = int(settings.get('max_price_age_minutes',60))
    if min(lookback,max_items,stale_minutes)<1:
        raise ValueError('D-C time windows and news limit must be positive')
    markets = {str(m['market_id']):m for m in config['markets']}
    news_indices = {mid:(NewsIndex(documents,m,True),NewsIndex(documents,m,False)) for mid,m in markets.items()}
    lookup = {}
    for mid,g in bars.groupby('market_id'):
        observed = g[g.observed].sort_values('bin_end')
        lookup[str(mid)] = (list(observed.bin_end),observed.to_dict('records'))
    stats = {'decision_rows':len(decisions),'unit':'taker_transaction_market_token_direction_bundle',
        'strict_rows_with_news':0,'rows_with_research_candidates':0,'news_documents':len(documents),
        'markets':{},'synthetic':config.get('synthetic',False),
        'strict_news_requires':'verified text/time AND calendar or independent_manual discovery',
        'limitation':'Pre-fill public context, not proven pre-submission context or individual exposure. No human/bot filter.'}
    histories = defaultdict(lambda:{'observed_prior_bundles':0,'recorded_prior_notional_usd':0.0})
    output.mkdir(parents=True,exist_ok=True)
    def nullable(x):
        return float(x) if x is not None and math.isfinite(float(x)) else None
    sample = []
    with gzip.open(output/'dc.jsonl.gz','wt',encoding='utf-8') as strict_file, gzip.open(output/'decision_news_candidates.jsonl.gz','wt',encoding='utf-8') as exploratory:
        # All same-timestamp contexts are computed before updating actor histories.
        for stamp,batch in decisions.groupby('timestamp',sort=True):
            for row in batch.to_dict('records'):
                mid,actor = row['market_id'],row['taker']
                times,records = lookup[mid]
                pos = bisect_left(times,stamp)-1
                bar = records[pos] if pos>=0 else None
                age = (stamp-bar['bin_end']).total_seconds() if bar else None
                fresh = age is not None and age<=stale_minutes*60
                state = {'last_observed_bar_end':bar['bin_end'].isoformat() if bar else None,
                    'price_age_seconds':age,'stale_or_missing':not fresh,
                    'price_outcome1':nullable(bar['price']) if fresh else None,
                    'displacement_pp':nullable(bar.get('displacement_pp')) if fresh else None,
                    'rv_pp':nullable(bar.get('rv_pp')) if fresh else None,
                    'prior_bar_record_count':int(bar['record_count']) if fresh else None}
                news = news_indices[mid][0].at(stamp,lookback,max_items)
                candidates = news_indices[mid][1].at(stamp,lookback,max_items)
                decision = {'actor':actor,'actor_role':'taker','execution_timestamp':stamp.isoformat(),
                    'transaction_hash':row['transaction_hash'],'market_id':mid,'token_side':row['nonusdc_side'],
                    'direction':row['taker_direction'],'direction_outcome1_equivalent':row['direction_outcome1'],
                    'shares':float(row['shares']),'recorded_notional_usd':float(row['recorded_notional_usd']),
                    'execution_price':float(row['execution_price']),'fill_count':int(row['fill_count'])}
                context = {'cutoff_exclusive':stamp.isoformat(),'market_id':mid,
                    'question':markets[mid]['question'],'outcome1_label':markets[mid]['outcome1_label'],
                    'market_state':state,'actor_history_in_selected_markets':dict(histories[actor]),
                    'news':news,'news_status':'verified_items_available' if news else 'no_verified_context',
                    'metadata_note':'Configured contract identity; historical rule versions not reconstructed.',
                    'context_semantics':'pre-fill; submission time and individual exposure unobserved'}
                record = {'decision_id':row['decision_id'],'split_group':row['transaction_hash'],'D':decision,'C':context}
                strict_file.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n')
                exploratory.write(json.dumps({'decision_id':row['decision_id'],'research_candidates_NOT_C':candidates},ensure_ascii=False,allow_nan=False)+'\n')
                if len(sample)<5:
                    sample.append(record)
                stats['strict_rows_with_news'] += bool(news)
                stats['rows_with_research_candidates'] += bool(candidates)
                stats['markets'][mid] = stats['markets'].get(mid,0)+1
            for row in batch.to_dict('records'):
                histories[row['taker']]['observed_prior_bundles'] += 1
                histories[row['taker']]['recorded_prior_notional_usd'] += float(row['recorded_notional_usd'])
    decisions.to_csv(output/'decisions.csv.gz',index=False,compression='gzip')
    (output/'dc_sample.json').write_text(json.dumps(sample,indent=2,ensure_ascii=False))
    (output/'dc_manifest.json').write_text(json.dumps(stats,indent=2))
    return stats
