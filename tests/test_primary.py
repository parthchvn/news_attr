from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import pytest
from polymarket_context.primary import capture, eligible_at, feed_urls, stamp, statement_text, validate_record

URL='https://www.federalreserve.gov/newsevents/pressreleases/monetary20250507a.htm'
RAW=b'<p>For release at 2:00 p.m. EDT</p><p>SYNTHETIC statement for a software test.</p><p>Voting for the monetary policy action were A and B.</p><p>For media inquiries, contact us.</p>'
PLAN={'selection_basis':'source_schedule','release_urls':[URL]}
def fetch(url): return RAW, {'status':200, 'final_url':url}

def test_capture_no_backdate_and_no_equal_time(tmp_path):
    status=capture(PLAN,tmp_path,fetch)
    assert status['documents']==1 and status['empirical_delta_news'] is None
    r=json.loads((tmp_path/'information.jsonl').read_text())
    assert not eligible_at(r,r['usable_at'],tmp_path)
    later=(stamp(r['usable_at'])+timedelta(seconds=1)).isoformat()
    assert eligible_at(r,later,tmp_path)
    assert not eligible_at(r,'2025-05-08T00:00:00Z',tmp_path)
    assert r['historical_usable_at'] is None and r['market_ids']==[]

def test_repeated_capture_preserves_earliest_version(tmp_path):
    capture(PLAN,tmp_path,fetch)
    first=(tmp_path/'information.jsonl').read_bytes()
    capture(PLAN,tmp_path,fetch)
    assert (tmp_path/'information.jsonl').read_bytes()==first
    assert len((tmp_path/'cycles.jsonl').read_text().splitlines())==2

def test_new_content_creates_a_new_version(tmp_path):
    capture(PLAN,tmp_path,fetch)
    capture(PLAN,tmp_path,lambda u:(RAW.replace(b'A and B',b'A, B and C'),{'status':200}))
    rows=[json.loads(x) for x in (tmp_path/'information.jsonl').read_text().splitlines()]
    assert len(rows)==2 and rows[0]['document_id']!=rows[1]['document_id']
    assert rows[0]['information_event_id']==rows[1]['information_event_id']

@pytest.mark.parametrize('field,value',[('usable_at','2025-05-07T18:00:00Z'),('verified_text','Invented text'),('discovery_mode','spike')])
def test_tampered_record_rejected(tmp_path,field,value):
    capture(PLAN,tmp_path,fetch)
    r=json.loads((tmp_path/'information.jsonl').read_text());r[field]=value
    with pytest.raises(ValueError):validate_record(r,tmp_path)

def test_failure_recorded_without_dummy_information(tmp_path):
    result=capture(PLAN,tmp_path,lambda u:(_ for _ in ()).throw(OSError('offline')))
    assert result['errors'] and result['documents']==0
    assert not (tmp_path/'information.jsonl').exists()

def test_unknown_layout_fails_closed():
    with pytest.raises(ValueError):statement_text(b'<p>breaking headline</p>')

def test_source_plan_excludes_spike_selection(tmp_path):
    with pytest.raises(ValueError):capture({**PLAN,'selection_basis':'spike'},tmp_path,fetch)

def test_feed_filter_is_title_based_not_price_based():
    raw=f'<rss><channel><item><title>Federal Reserve issues FOMC statement</title><link>{URL}</link></item><item><title>Other press release</title><link>{URL}</link></item></channel></rss>'.encode()
    assert feed_urls(raw)==[URL]
