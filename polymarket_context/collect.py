"""Calendar-first information collection plus spike-triggered enrichment.
Google RSS is best-effort headline discovery, NOT a historical archive.
"""
from __future__ import annotations
import hashlib
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from email.utils import parsedate_to_datetime
from itertools import zip_longest
from urllib.parse import urlencode,urlsplit
import pandas as pd
import requests
from .news import prepare_search_jobs,retrieve_news,canonical_url


def discovery_jobs(bars: pd.DataFrame,episodes: list[dict],config: dict) -> list[dict]:
    """Calendar windows depend on coverage, never jump size or final outcome."""
    days=int(config.get('news',{}).get('calendar_window_days',14))
    if days<1:
        raise ValueError('calendar_window_days must be positive')
    streams=[]
    for market in config['markets']:
        mid=str(market['market_id'])
        g=bars[bars.market_id.astype(str).eq(mid)]
        if g.empty:
            continue
        start=pd.Timestamp(g.bin_end.min()).normalize()-pd.Timedelta(days=1)
        stop=pd.Timestamp(g.bin_end.max()).normalize()+pd.Timedelta(days=1)
        calendar=[]
        while start<stop:
            end=min(start+pd.Timedelta(days=days),stop)
            for query in market.get('search_queries',[])[:1]:
                calendar.append({'market_id':mid,'episode_id':None,'discovery_mode':'calendar',
                    'query':query,'window_start':start.isoformat(),'window_end':end.isoformat(),
                    'start_date':start.date().isoformat(),'end_date':end.date().isoformat()})
            start=end
        spikes=[{**j,'discovery_mode':'spike'} for j in prepare_search_jobs(
            [e for e in episodes if e['market_id']==mid],{**config,'markets':[market]})]
        streams += [calendar,spikes]
    return [j for batch in zip_longest(*streams) for j in batch if j is not None]


def parse_rss(xml: str) -> list[dict]:
    root=ET.fromstring(xml)
    if root.tag!='rss' or root.find('channel') is None:
        raise ValueError('Response was not a news RSS feed')
    results=[]
    for item in root.findall('./channel/item'):
        title,url=(item.findtext('title') or '').strip(),(item.findtext('link') or '').strip()
        if not title or not url:
            continue
        try:
            url=canonical_url(url)
        except ValueError:
            continue
        pub=item.findtext('pubDate')
        claimed=None
        if pub:
            try:
                dt=parsedate_to_datetime(pub)
                if dt.tzinfo is not None:
                    claimed=pd.Timestamp(dt).tz_convert('UTC').isoformat()
            except (ValueError,TypeError,OverflowError):
                pass
        source=item.find('source')
        results.append({'title':title,'url':url,'published_date':claimed,
            'source':source.text if source is not None else urlsplit(url).netloc,
            'publisher_homepage':source.get('url') if source is not None else None})
    return results


def retrieve_rss(jobs: list[dict],config: dict,cache: Path) -> tuple[list[dict],list[dict]]:
    cache.mkdir(parents=True,exist_ok=True)
    settings=config.get('news',{})
    limit=int(settings.get('max_requests',80))
    if limit<0:
        raise ValueError('max_requests cannot be negative')
    docs,statuses,n={},[],0
    for job in jobs:
        query=f"{job['query']} after:{job['start_date']} before:{job['end_date']}"
        url='https://news.google.com/rss/search?'+urlencode({'q':query,'hl':'en-US','gl':'US','ceid':'US:en'})
        rid=hashlib.sha256(url.encode()).hexdigest()
        path,record=cache/(rid+'.json'),{**job,'request_id':rid,'provider':'google_rss'}
        try:
            if path.exists():
                saved=json.loads(path.read_text());record['status']='cached'
            else:
                if n>=limit:
                    statuses.append({**record,'status':'budget_skipped'});continue
                n+=1
                response=requests.get(url,timeout=(10,30),headers={
                    'User-Agent':'news-attr-research/0.2 (+https://github.com/parthchvn/news_attr)'})
                response.raise_for_status()
                saved={'url':url,'xml':response.text,'retrieved_at':pd.Timestamp.now(tz='UTC').isoformat()}
                parse_rss(saved['xml'])
                path.write_text(json.dumps(saved,ensure_ascii=False))
                record['status']='ok'
                time.sleep(float(settings.get('request_delay_seconds',1.0)))
            results=parse_rss(saved['xml'])
            for item in results:
                content_hash=hashlib.sha256(item['title'].encode()).hexdigest()
                did=hashlib.sha256((item['url']+'|'+content_hash).encode()).hexdigest()[:20]
                if did not in docs:
                    docs[did]={'document_id':did,'url':item['url'],'title':item['title'],'snippet':'',
                        'source':item['source'],'publisher_homepage':item['publisher_homepage'],
                        'content_sha256':content_hash,'published_at_claimed':item['published_date'],
                        'retrieved_at':saved['retrieved_at'],'timestamp_status':'feed_claim_unverified',
                        'verified_available_at':None,'verification_evidence':'','verified_text':'',
                        'retrieval_request_ids':[],'discovery_modes':[],'market_ids':[],
                        'coverage_note':'Best-effort historical RSS search; headline only, not archived article body.'}
                doc=docs[did]
                doc['retrieval_request_ids']=sorted(set(doc['retrieval_request_ids']+[rid]))
                doc['discovery_modes']=sorted(set(doc['discovery_modes']+[job['discovery_mode']]))
                doc['market_ids']=sorted(set(doc['market_ids']+[job['market_id']]))
            statuses.append({**record,'result_count':len(results)})
        except (requests.RequestException,ValueError,ET.ParseError,OSError) as exc:
            statuses.append({**record,'status':'failed','error_type':type(exc).__name__})
    return list(docs.values()),statuses


def collect(jobs: list[dict],config: dict,cache: Path) -> tuple[list[dict],list[dict]]:
    provider=config.get('news',{}).get('provider','google_rss')
    if provider=='google_rss':
        return retrieve_rss(jobs,config,cache/'rss')
    if provider!='tavily':
        raise ValueError('news.provider must be google_rss or tavily')
    docs,statuses=retrieve_news(jobs,config,cache/'tavily')
    by_request={}
    for s in statuses:
        by_request.setdefault(s['request_id'],[]).append(s)
    for d in docs:
        used=[s for rid in d['retrieval_request_ids'] for s in by_request.get(rid,[]) if s['status'] in {'ok','cached'}]
        d['discovery_modes']=sorted({s['discovery_mode'] for s in used})
        d['market_ids']=sorted({s['market_id'] for s in used})
    return docs,statuses
