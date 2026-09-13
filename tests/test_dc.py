import gzip
import json
import pandas as pd
import pytest
from polymarket_context.core import DetectorConfig,normalize_trades,make_bars,detect_movements,load_trades
from polymarket_context.dc import participant_fills,decisions_from_fills,eligible_news,NewsIndex,export_dc
from polymarket_context.collect import discovery_jobs,parse_rss,retrieve_rss


def market():
    return {'market_id':'m','question':'Will Inter win?','outcome1_label':'Yes',
        'required_term_groups':[['Inter'],['Champions League']],'search_queries':['Inter Champions League']}


def trades():
    return pd.DataFrame({'market_id':['m']*4,'timestamp':[1735689601,1735689602,1735690200,1735690200],
        'price':[.2,.3,.7,.7],'token_amount':[10.]*4,'usd_amount':[2.,3.,7.,7.],
        'nonusdc_side':['token1']*4,'transaction_hash':['a','b','c','c'],'log_index':[0,0,0,1],
        'contract':['exchange']*4,'maker':['mm']*4,'taker':['alice']*4,
        'maker_direction':['SELL']*4,'taker_direction':['BUY']*4})


def doc():
    return {'document_id':'doc','url':'https://example.invalid/source','title':'Inter Champions League','snippet':'',
        'published_at_claimed':'2025-01-01T00:00:00Z','timestamp_status':'verified',
        'verified_available_at':'2025-01-01T00:00:00Z','verified_text':'Inter Champions League fixture text',
        'verification_evidence':'SYNTHETIC TEST ONLY','discovery_modes':['calendar']}


def test_exchange_summary_filter_not_general_contract_filter():
    f=trades();f.loc[0,'taker']='exchange';f.loc[1,'taker']='smart-wallet';r,a=participant_fills(f)
    assert len(r)==3 and a['exchange_summary_rows_removed']==1
    assert 'smart-wallet' in r.taker.values


def test_bundles_keep_transaction_split_group():
    n,_=normalize_trades(trades(),'trades');d=decisions_from_fills(n)
    assert len(d)==3 and d.iloc[-1].fill_count==2 and d.iloc[-1].shares==20


def test_no_token_action_preserved_with_equivalent_direction():
    f=trades();f['nonusdc_side']='token2';n,_=normalize_trades(f,'trades');d=decisions_from_fills(n)
    assert set(d.direction_outcome1)=={'SELL'}
    assert set(d.taker_direction)=={'BUY'}
    assert d.iloc[0].execution_price==pytest.approx(.2)
    assert d.iloc[0].outcome1_equivalent_price==pytest.approx(.8)


def test_spike_only_document_not_strict_context():
    d=doc();d['discovery_modes']=['spike'];cutoff=pd.Timestamp('2025-01-01T00:01:00Z')
    assert eligible_news([d],market(),cutoff,strict=True)==[]
    assert len(eligible_news([d],market(),cutoff,strict=False))==1


def test_date_claim_does_not_promote_current_text():
    d=doc();d['timestamp_status']='feed_claim_unverified'
    assert NewsIndex([d],market(),True).at(pd.Timestamp('2025-01-01T00:01:00Z'),72,8)==[]


def test_news_equal_time_excluded():
    idx=NewsIndex([doc()],market(),True)
    assert not idx.at(pd.Timestamp('2025-01-01T00:00:00Z'),72,8)
    assert idx.at(pd.Timestamp('2025-01-01T00:00:01Z'),72,8)


def test_future_documents_cannot_alter_earlier_context():
    later={**doc(),'document_id':'future','verified_available_at':'2025-01-02T00:00:00Z'};t=pd.Timestamp('2025-01-01T00:01:00Z')
    assert NewsIndex([doc()],market(),True).at(t,72,8)==NewsIndex([doc(),later],market(),True).at(t,72,8)


def test_context_uses_audited_old_text_not_new_headline():
    d=doc();d['verified_text']='Different topic'
    assert not NewsIndex([d],market(),True).at(pd.Timestamp('2025-01-01T00:01:00Z'),72,8)


def test_dc_no_target_price_or_resolution_and_earlier_history(tmp_path):
    n,_=normalize_trades(trades(),'trades');cfg=DetectorConfig(min_baseline_bins=1);bars,_=detect_movements(make_bars(n,cfg),cfg)
    export_dc(n,bars,[doc()],{'markets':[market()],'synthetic':True},tmp_path)
    with gzip.open(tmp_path/'dc.jsonl.gz','rt') as f:
        rows=[json.loads(l) for l in f]
    last=rows[-1]
    assert last['D']['execution_price']==pytest.approx(.7)
    assert last['C']['market_state']['price_outcome1']==pytest.approx(.25)
    assert last['C']['actor_history_in_selected_markets']['observed_prior_bundles']==2
    assert last['C']['market_state']['last_observed_bar_end']<last['C']['cutoff_exclusive']
    assert 'outcome_prices' not in json.dumps(last['C'])
    assert 'execution_price' not in last['C']


def test_all_transactions_same_timestamp_excluded_from_history(tmp_path):
    f=trades();f.loc[3,'transaction_hash']='d';n,_=normalize_trades(f,'trades');cfg=DetectorConfig(min_baseline_bins=1)
    bars,_=detect_movements(make_bars(n,cfg),cfg);export_dc(n,bars,[],{'markets':[market()]},tmp_path)
    with gzip.open(tmp_path/'dc.jsonl.gz','rt') as stream:
        rows=[json.loads(l) for l in stream]
    assert rows[-1]['C']['actor_history_in_selected_markets']['observed_prior_bundles']==2
    assert rows[-2]['C']['actor_history_in_selected_markets']['observed_prior_bundles']==2


def test_calendar_jobs_independent_of_prices():
    bars=pd.DataFrame({'market_id':['m']*2,'bin_end':pd.to_datetime(['2025-01-01','2025-02-01'],utc=True),'price':[.1,.9]})
    config={'markets':[market()]};a=discovery_jobs(bars,[],config);bars['price']=.5
    assert a==discovery_jobs(bars,[],config)
    assert all(j['discovery_mode']=='calendar' for j in a)


def test_rss_parses_claim_but_does_not_verify():
    xml='<rss><channel><item><title>Inter Champions League</title><link>https://example.invalid/a</link><pubDate>Wed, 01 Jan 2025 00:00:00 GMT</pubDate><source url="https://example.invalid">Source</source></item></channel></rss>'
    assert parse_rss(xml)[0]['published_date']=='2025-01-01T00:00:00+00:00'
    with pytest.raises(ValueError):
        parse_rss('<html>error</html>')


def test_rss_budget_and_cache(tmp_path,monkeypatch):
    job={'query':'Inter','start_date':'2025-01-01','end_date':'2025-01-02','market_id':'m','discovery_mode':'calendar'}
    docs,status=retrieve_rss([job],{'news':{'max_requests':0}},tmp_path)
    assert docs==[] and status[0]['status']=='budget_skipped'


def test_compressed_csv_and_datetime_input(tmp_path):
    path=tmp_path/'t.csv.gz';trades().to_csv(path,index=False,compression='gzip')
    assert len(load_trades(path,['m']))==4
    f=trades();f['timestamp']=pd.to_datetime(f.timestamp,unit='s',utc=True)
    n,_=normalize_trades(f,'trades');assert len(n)==4
