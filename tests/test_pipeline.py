import numpy as np
import pandas as pd
import pytest
from polymarket_context.core import DetectorConfig,detect_movements,make_bars,normalize_trades
from polymarket_context.demo import create_demo
from polymarket_context.news import aware_time,canonical_url,context_asof,keyword_relevance,match_candidates,prepare_search_jobs,retrieve_news,verified_available_at


def frame(prices=(.3,.7),sides=('token1','token2')):
    return pd.DataFrame({'market_id':['m']*len(prices),'timestamp':[1735689601+i for i in range(len(prices))],
        'price':prices,'token_amount':[10.]*len(prices),'usd_amount':np.array(prices)*10,'nonusdc_side':sides,
        'transaction_hash':[f'tx{i}' for i in range(len(prices))],'log_index':[0]*len(prices)})


def simple_bars(n=100):
    return pd.DataFrame({'market_id':'m','bin_end':pd.date_range('2025-01-01',periods=n,freq='5min',tz='UTC'),
        'price':np.r_[np.repeat(.3,60),np.repeat(.5,n-60)],'observed':True,'thin_bin':False,
        'record_count':4,'recorded_notional_usd':100.,'token_amount':200.,'low':.3,'high':.5})


def cfg():
    return DetectorConfig(min_baseline_bins=8)


def market():
    return {'market_id':'m','question':'Country A tariff?','outcome1_label':'Yes',
        'required_term_groups':[['Country A'],['tariff']],'search_queries':['Country A tariff']}


def episode():
    return {'episode_id':'e','market_id':'m','window_start':'2025-01-01T12:00:00Z','window_end':'2025-01-01T12:15:00Z','score':10}


def document():
    return {'document_id':'d','url':'https://example.invalid/news','title':'Country A tariff',
        'snippet':'Country A tariff announcement','published_at_claimed':'2025-01-01T11:55:00Z'}


def test_raw_normalizes_once():
    result,_=normalize_trades(frame(),'trades')
    assert np.allclose(result.price_outcome1,.3)
    assert np.allclose(result.usd_amount,[3.,7.])


def test_quant_not_inverted():
    result,_=normalize_trades(frame(),'quant')
    assert np.allclose(result.price_outcome1,[.3,.7])


def test_duplicate_log_not_transaction():
    original=frame();original['transaction_hash']='same_tx';original['log_index']=[0,1]
    result,audit=normalize_trades(pd.concat([original,original.iloc[[0]]],ignore_index=True),'trades')
    assert len(result)==2 and audit['duplicate_logs_removed']==1


def test_conflicting_duplicate_fails():
    df=frame();df['transaction_hash']='same'
    with pytest.raises(ValueError,match='Conflicting'):
        normalize_trades(df,'trades')


def test_user_rows_rejected():
    df=frame();df['role']='maker'
    with pytest.raises(ValueError,match='User-level'):
        normalize_trades(df,'quant')


def test_vwap_not_original_cash_divided_by_shares():
    normalized,_=normalize_trades(frame(),'trades');bars=make_bars(normalized,cfg())
    assert bars.price.iloc[0]==pytest.approx(.3)
    assert bars.recorded_notional_usd.iloc[0]==pytest.approx(10)


def test_gaps_not_bridged():
    bars=simple_bars();bars.loc[58:60,'price']=np.nan;bars.loc[58:60,'observed']=False
    computed,_=detect_movements(bars,cfg())
    assert computed.loc[58:63,'displacement_pp'].isna().all()
    assert not computed.loc[58:63,'alert'].any()


def test_alert_and_detection_time():
    bars,events=detect_movements(simple_bars(),cfg())
    assert events
    assert events[0]['detected_at']==bars.loc[60,'bin_end'].isoformat()
    assert events[0]['initial_displacement_pp']==pytest.approx(20.)


def test_future_changes_cannot_change_earlier_alerts():
    first=simple_bars(120);changed=first.copy();changed.loc[90:,'price']=.95
    a,_=detect_movements(first,cfg());b,_=detect_movements(changed,cfg())
    pd.testing.assert_frame_equal(a.loc[:89],b.loc[:89])


def test_contracts_separate():
    first=simple_bars();second=first.copy();second['market_id']='other';second['price']=.9
    _,events=detect_movements(pd.concat([first,second]),cfg())
    assert {e['market_id'] for e in events}=={'m'}


def test_no_dates_or_naive_dates_are_not_verified():
    assert aware_time('2025-01-01') is None
    assert aware_time('2025-01-01T12:00:00') is None
    assert verified_available_at(document()) is None


def test_late_news_label_not_catalyst():
    doc=document();doc['published_at_claimed']='2025-01-01T12:30:00Z'
    links=match_candidates([episode()],[doc],{'markets':[market()]})
    assert links[0]['temporal_role']=='after_window'
    assert links[0]['review_label']=='unreviewed'


def test_asof_strict_and_uses_verified_text():
    doc=document()
    assert not context_asof([doc],market(),'2025-01-01T12:00:00Z')
    doc.update(timestamp_status='verified',verified_available_at='2025-01-01T11:55:00Z',
        verification_evidence='SYNTHETIC archive fixture',verified_text='Country A tariff announcement')
    assert not context_asof([doc],market(),'2025-01-01T11:55:00Z')
    assert len(context_asof([doc],market(),'2025-01-01T11:55:01Z'))==1
    doc['verified_text']='Unrelated past text; current headline was added later.'
    assert not context_asof([doc],market(),'2025-01-01T12:00:00Z')


def test_keyword_groups_not_one_shared_word():
    doc=document();doc.update(title='Country A sports',snippet='Unrelated sports news')
    assert keyword_relevance(doc,market())==.5
    assert not match_candidates([episode()],[doc],{'markets':[market()]})


def test_missing_api_key_explicit(tmp_path,monkeypatch):
    monkeypatch.delenv('TAVILY_API_KEY',raising=False)
    config={'markets':[market()]};jobs=prepare_search_jobs([episode()],config)
    docs,status=retrieve_news(jobs,config,tmp_path/'cache')
    assert not docs and status[0]['status']=='missing_api_key'


def test_provider_mock_cache_and_timestamp_status(tmp_path,monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY','dummy-test-key');calls=[]
    def fake(payload,key):
        calls.append(payload);assert key=='dummy-test-key'
        return {'results':[{'url':'https://example.invalid/a','title':'Country A tariff','content':'Country A tariff announcement','published_date':'2025-01-01T11:55:00Z'}]}
    monkeypatch.setattr('polymarket_context.news._request_tavily',fake)
    config={'markets':[market()]};jobs=prepare_search_jobs([episode()],config)
    docs,status=retrieve_news(jobs,config,tmp_path/'cache')
    again,second=retrieve_news(jobs,config,tmp_path/'cache')
    assert docs==again and len(calls)==1
    assert docs[0]['timestamp_status']=='provider_estimate'
    assert second[0]['status']=='cached'
    assert not context_asof(docs,market(),'2025-01-01T12:00:00Z')
    assert 'dummy-test-key' not in next((tmp_path/'cache').glob('*')).read_text()


def test_safe_urls():
    assert canonical_url('https://site.invalid/a?utm_source=x&id=4#part')=='https://site.invalid/a?id=4'
    with pytest.raises(ValueError):
        canonical_url('javascript:alert(1)')


def test_entire_demo(tmp_path):
    from polymarket_context.__main__ import analyze,read_config,render
    demo_path=tmp_path/'demo';config_path=create_demo(demo_path);config,output=read_config(config_path)
    analyze(config,output);render(config,output,demo_path/'synthetic_news.jsonl')
    assert (output/'dashboard.html').stat().st_size>100_000
    assert 'SYNTHETIC DEMO' in (output/'dashboard.html').read_text()
    assert (output/'attribution_links.jsonl').stat().st_size>0
    with pytest.raises(FileExistsError):
        analyze(config,output)


def test_parquet_roundtrip_optional(tmp_path):
    pytest.importorskip('pyarrow')
    from polymarket_context.core import load_trades
    frame().to_parquet(tmp_path/'data.parquet',index=False)
    assert len(load_trades(tmp_path/'data.parquet',['m']))==2
