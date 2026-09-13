"""Deterministic detection/causality tests; not a real-world precision benchmark."""
from dataclasses import replace
import json

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

from polymarket_context.fine import (FineConfig, weighted_median, make_fine_bars,
    past_baseline, detect_fine, news_groups, known_context)
from polymarket_context.fine_report import gap_line, safe_json


def bars(prices, seconds=30):
    p = np.array(prices, dtype=float)
    times = pd.date_range('2025-05-31T18:00Z', periods=len(p), freq=f'{seconds}s')
    return pd.DataFrame({'market_id':'507300','bin_end':times,
        'price':p,'median_price':p,'supported':True,'transaction_count':3,'shares':100.,
        'fill_count':3,'low':p,'high':p,'recorded_notional_usd':100*p,
        'first_fill_at':times-pd.Timedelta(seconds=seconds-1),
        'last_fill_at':times-pd.Timedelta(seconds=1)})


def test_flat_market_has_no_alerts():
    m, a = detect_fine(bars([.4]*200), FineConfig())
    assert not a and m.candidate.sum()==0


def test_known_step_is_not_delayed_by_fifteen_minute_horizon():
    b = bars([.4]*100+[.48]*10)
    _, a = detect_fine(b, FineConfig())
    assert a[0]['detected_at'] == b.iloc[100].bin_end.isoformat()
    assert a[0]['tier']=='unusual_change'
    assert 30 in a[0]['horizons_seconds']


def test_warmup_keeps_size_evidence_but_does_not_claim_z_detection():
    _, a = detect_fine(bars([.4,.45,.45]), FineConfig())
    assert a and all(x['tier']=='supported_change' for x in a)
    assert a[0]['baseline_note']=='insufficient_history_size_only'


def test_tail_change_below_one_percentage_point_is_detected():
    b = bars([.008]*100+[.004]*5)
    _, a = detect_fine(b, FineConfig())
    assert a and a[0]['tier']=='unusual_change'
    assert 'tail_log_odds' in a[0]['signals'][0]['signals']
    assert abs(a[0]['signals'][0]['change_pp']) < 1


def test_single_transaction_bin_cannot_become_supported_alert():
    b = bars([.4]*100+[.7]+[.4]*5)
    b.loc[100,['supported','transaction_count']]=[False,1]
    _, a = detect_fine(b, FineConfig())
    assert not a


def test_reversal_produces_two_alerts_not_one_merged_dot():
    b = bars([.4]*100+[.5,.4]+[.4]*4)
    _, a = detect_fine(b, FineConfig())
    selected = [x for x in a if x['detected_at'] in [b.iloc[100].bin_end.isoformat(), b.iloc[101].bin_end.isoformat()]]
    assert len(selected)==2
    assert selected[0]['signals'][0]['change_pp']>0
    assert selected[1]['signals'][0]['change_pp']<0


def test_horizon_records_combine_without_losing_individual_horizons():
    _, a = detect_fine(bars([.4]*100+[.5]*5), FineConfig())
    ids = [(x['market_id'],x['detected_at']) for x in a]
    assert len(ids)==len(set(ids))
    assert any(len(x['signals'])>1 for x in a)


def test_no_return_across_long_unobserved_period():
    b = bars([.4]*100+[.8]*3)
    b.loc[100:,'bin_end'] += pd.Timedelta(days=1)
    _, a = detect_fine(b, FineConfig())
    assert not a


def test_partial_window_keeps_measured_endpoint_change_not_fake_variation():
    cfg = replace(FineConfig(), horizons_seconds=(60,), min_coverage=.6)
    b = bars([.4,.4,.5]).drop(index=1)
    m, a = detect_fine(b,cfg)
    assert len(a)==1
    assert a[0]['signals'][0]['coverage']==pytest.approx(2/3)
    assert a[0]['signals'][0]['variation_pp'] is None
    assert a[0]['signals'][0]['change_pp']==pytest.approx(10)


def test_future_changes_leave_all_earlier_alerts_and_diagnostics_unchanged():
    rng=np.random.default_rng(3)
    b = bars(.4+np.cumsum(rng.normal(0,.005,220)))
    cfg=replace(FineConfig(), min_baseline_samples=8)
    m1,a1=detect_fine(b.iloc[:170],cfg)
    b.loc[170:,'median_price']=.95
    m2,a2=detect_fine(b,cfg)
    cutoff=b.iloc[169].bin_end
    assert a1==[a for a in a2 if pd.Timestamp(a['detected_at'])<=cutoff]
    cols=['market_id','bin_end','horizon_seconds']
    assert_frame_equal(m1.sort_values(cols).reset_index(drop=True),
        m2[m2.bin_end<=cutoff].sort_values(cols).reset_index(drop=True))


def test_baseline_excludes_entire_current_price_window():
    cfg=replace(FineConfig(), min_baseline_samples=3)
    idx=pd.date_range('2025-01-01T00:00Z',periods=20,freq='30s')
    metric=pd.Series(np.arange(20,dtype=float), index=idx)
    baseline=past_baseline(metric,60,cfg,.15)
    # At t=300s, history ends by t-60-30=210s, so values 0..7 only.
    assert baseline.loc[idx[10],'center']==pytest.approx(3.5)
    metric.loc[idx[8]:]=1e6
    assert past_baseline(metric,60,cfg,.15).loc[idx[10],'center']==pytest.approx(3.5)


def test_baseline_expires_across_a_gap():
    cfg=replace(FineConfig(), min_baseline_samples=3, baseline_hours=1)
    idx=pd.date_range('2025-01-01T00:00Z',periods=10,freq='30s').append(pd.DatetimeIndex(['2025-01-01T04:00Z']))
    metric=pd.Series(np.arange(len(idx),dtype=float), index=idx)
    base=past_baseline(metric,30,cfg,.15)
    assert pd.isna(base.iloc[-1]['center'])


def test_logit_zero_one_clipping_is_finite():
    m,a=detect_fine(bars([0.]*100+[1.]*4), FineConfig())
    assert np.isfinite(m.log_odds_change.dropna()).all()
    json.dumps(a,allow_nan=False)


def test_new_markets_do_not_change_existing_market_alerts():
    b=bars([.4]*100+[.5]*5)
    _,a=detect_fine(b,FineConfig())
    other=b.copy();other['market_id']='2446852';other['median_price']=.2
    _,combined=detect_fine(pd.concat([b,other]),FineConfig())
    assert a==[r for r in combined if r['market_id']=='507300']


def test_fifteen_second_configuration_detects_a_step():
    b=bars([.4]*100+[.5]*10,seconds=15)
    _,a=detect_fine(b,replace(FineConfig(),bin_seconds=15))
    assert a[0]['detected_at']==b.iloc[100].bin_end.isoformat()


@pytest.mark.parametrize('changes',[
    {'bin_seconds':0},{'bin_seconds':7},{'min_transactions':True},
    {'horizons_seconds':(60,30)},{'horizons_seconds':()},
    {'min_coverage':1.2},{'logit_clip':0},{'min_change_pp':float('nan')}])
def test_bad_configuration_rejected(changes):
    with pytest.raises(ValueError):replace(FineConfig(),**changes)


def test_weighted_median_rejects_small_extreme_price_print():
    assert weighted_median(np.array([.4,.4,.99]), np.array([100,100,1]))==.4


def test_bins_count_distinct_transactions_and_do_not_fill_gaps():
    t=pd.DataFrame({'market_id':'507300',
      'timestamp':pd.to_datetime(['2025-01-01T00:00:01Z','2025-01-01T00:00:02Z','2025-01-01T00:01:01Z']),
      'price_outcome1':[.4,.41,.5], 'token_amount':[10,20,30], 'usd_amount':[4,8.2,15],
      'transaction_hash':['same','same','other']})
    b=make_fine_bars(t,FineConfig())
    assert len(b)==2 and b.iloc[0].transaction_count==1
    assert not b.supported.any()
    assert b.iloc[0].price==pytest.approx((4+8.2)/30)
    assert b.iloc[1].bin_end==pd.Timestamp('2025-01-01T00:01:30Z')


def test_grouping_preserves_markers_and_caps_chained_cluster_span():
    _,a=detect_fine(bars([.4]*100+list(np.tile([.5,.4],40))),FineConfig())
    cfg=FineConfig()
    groups=news_groups(a,cfg)
    assert sum(len(g['alert_ids']) for g in groups)==len(a)
    assert len(groups)>1
    for g in groups:
        assert (pd.Timestamp(g['last_detection'])-pd.Timestamp(g['first_detection'])).total_seconds()<=cfg.news_max_span_seconds


def test_news_ordering_is_recomputed_for_each_fine_alert():
    _,aa=detect_fine(bars([.4]*100+[.5,.4]), FineConfig())
    first=aa[0]
    e={'episode_id':'e','market_id':'507300','window_start':first['window_start'],'window_end':aa[-1]['detected_at']}
    l={'episode_id':'e','document_id':'d','published_at_claimed':first['detected_at']}
    linked=known_context(aa,[e],[l])
    assert linked[0]['temporal_role']=='after_detection'
    assert not linked[0]['training_eligible']


def test_no_hindsight_sources_carried_to_unrelated_windows():
    _,aa=detect_fine(bars([.4]*100+[.5]), FineConfig())
    e={'episode_id':'e','market_id':'507300','window_start':'2024-01-01T00:00Z','window_end':'2024-01-02T00:00Z'}
    assert not known_context(aa,[e],[{'episode_id':'e','document_id':'d'}])


def test_plot_lines_break_over_missing_bins_and_escape_untrusted_text():
    b=bars([.4,.5,.6]).drop(index=1)
    x,y=gap_line(b,30,'median_price')
    assert y==[.4,None,.6]
    assert '</script>' not in safe_json({'title':'</script><img>'})


def test_one_large_extreme_trade_needs_independent_price_corroboration():
    t=pd.DataFrame({'market_id':'507300',
      'timestamp':pd.to_datetime(['2025-01-01T00:00:01Z','2025-01-01T00:00:02Z','2025-01-01T00:00:03Z']),
      'price_outcome1':[.4,.4,.9], 'token_amount':[10,10,1000], 'usd_amount':[4,4,900],
      'transaction_hash':['a','b','c']})
    b=make_fine_bars(t,FineConfig())
    assert b.iloc[0].median_price==.9
    assert b.iloc[0].transaction_count==3
    assert b.iloc[0].corroborating_transactions==1
    assert not b.iloc[0].supported
