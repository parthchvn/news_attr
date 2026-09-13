from __future__ import annotations
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl,urlencode,urlsplit,urlunsplit
import pandas as pd
import requests


def dump_jsonl(path: Path,rows: list[dict]) -> None:
    with path.open('w',encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row,ensure_ascii=False,sort_keys=True,allow_nan=False)+'\n')


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def aware_time(value: Any) -> pd.Timestamp | None:
    if value is None or value=='':
        return None
    try:
        parsed=pd.Timestamp(value)
        if pd.isna(parsed) or parsed.tzinfo is None:
            return None
        return parsed.tz_convert('UTC')
    except (ValueError,TypeError):
        return None


def canonical_url(url: str) -> str:
    p=urlsplit(url)
    if p.scheme not in {'http','https'} or not p.netloc:
        raise ValueError('Document URLs must use HTTP(S).')
    query=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True)
           if not k.lower().startswith('utm_') and k.lower() not in {'fbclid','gclid'}]
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path,urlencode(query),''))


def verified_available_at(doc: dict) -> pd.Timestamp | None:
    """Requires an audited text version, not a search provider's date estimate."""
    t=aware_time(doc.get('verified_available_at'))
    if (doc.get('timestamp_status')!='verified' or not doc.get('verification_evidence')
            or not doc.get('verified_text') or t is None):
        return None
    return t


def keyword_relevance(doc: dict,market: dict,*,verified_only: bool=False) -> float:
    text=(doc.get('verified_text','') if verified_only else f"{doc.get('title','')} {doc.get('snippet','')}").casefold()
    groups=market.get('required_term_groups',[])
    if not groups:
        return 0.0
    hits=[any(re.search(r'(?<!\w)'+re.escape(str(term).casefold())+r'(?!\w)',text)
              for term in alternatives) for alternatives in groups]
    return sum(hits)/len(hits)


def prepare_search_jobs(episodes: list[dict],config: dict) -> list[dict]:
    settings=config.get('news',{})
    back,post=settings.get('lookback_hours',24),settings.get('post_hours',2)
    if back<=0 or post<0:
        raise ValueError('lookback_hours must be positive; post_hours nonnegative.')
    jobs=[]
    for market in config['markets']:
        candidates=[e for e in episodes if e['market_id']==str(market['market_id'])]
        selected=sorted(candidates,key=lambda e:(-e['score'],e['episode_id']))[:settings.get('max_episodes_per_market',10)]
        for event in selected:
            start=pd.Timestamp(event['window_start'])-pd.Timedelta(hours=back)
            end=pd.Timestamp(event['window_end'])+pd.Timedelta(hours=post)
            for query in market.get('search_queries',[])[:2]:
                jobs.append({'episode_id':event['episode_id'],'market_id':event['market_id'],
                    'query':query,'window_start':start.isoformat(),'window_end':end.isoformat(),
                    'start_date':(start.normalize()-pd.Timedelta(days=1)).date().isoformat(),
                    'end_date':(end.normalize()+pd.Timedelta(days=1)).date().isoformat()})
    return jobs


def _request_tavily(payload: dict,key: str) -> dict:
    for attempt in range(3):
        response=requests.post('https://api.tavily.com/search',json=payload,
            headers={'Authorization':f'Bearer {key}'},timeout=45)
        if response.status_code in {429,500,502,503,504} and attempt<2:
            time.sleep(2**attempt);continue
        response.raise_for_status()
        result=response.json()
        if not isinstance(result,dict) or not isinstance(result.get('results'),list):
            raise ValueError('Unexpected Tavily response schema.')
        return result
    raise RuntimeError('Search retries exhausted.')


def retrieve_news(jobs: list[dict],config: dict,cache_dir: Path) -> tuple[list[dict],list[dict]]:
    """Paid-key candidate discovery, cached and budgeted; never date verification."""
    settings=config.get('news',{})
    max_requests=int(settings.get('max_requests',20))
    max_results=int(settings.get('max_results_per_query',10))
    if max_requests<0 or not 1<=max_results<=20:
        raise ValueError('Invalid news request limits.')
    cache_dir.mkdir(parents=True,exist_ok=True)
    key=os.environ.get('TAVILY_API_KEY','')
    docs,status={},[]
    requests_made=0
    for job in jobs:
        payload={'query':job['query'],'topic':'general','search_depth':'basic',
            'start_date':job['start_date'],'end_date':job['end_date'],'max_results':max_results,
            'include_published_date':True,'filter_by_published_date':True,
            'include_answer':False,'include_raw_content':False}
        request_id=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        cached=cache_dir/f'{request_id}.json'
        record={**job,'request_id':request_id}
        try:
            if cached.exists():
                saved=json.loads(cached.read_text())
                result,fetched_at=saved['response'],saved['retrieved_at']
                record['status']='cached'
            else:
                if requests_made>=max_requests:
                    status.append({**record,'status':'budget_skipped'});continue
                if not key:
                    status.append({**record,'status':'missing_api_key'});continue
                requests_made+=1
                result=_request_tavily(payload,key)
                fetched_at=pd.Timestamp.now(tz='UTC').isoformat()
                cached.write_text(json.dumps({'response':result,'retrieved_at':fetched_at},ensure_ascii=False))
                record['status']='ok'
            for item in result['results']:
                try:
                    url=canonical_url(item['url'])
                except (ValueError,KeyError,TypeError):
                    continue
                snippet=item.get('content','') or ''
                title=item.get('title','') or ''
                content_hash=hashlib.sha256((title+'\n'+snippet).encode()).hexdigest()
                doc_id=hashlib.sha256((url+'|'+content_hash).encode()).hexdigest()[:20]
                if doc_id not in docs:
                    docs[doc_id]={'document_id':doc_id,'url':url,'title':title,'snippet':snippet,
                        'source':urlsplit(url).netloc,'content_sha256':content_hash,
                        'published_at_claimed':item.get('published_date'),'retrieved_at':fetched_at,
                        'timestamp_status':'provider_estimate','verified_available_at':None,
                        'verification_evidence':'','verified_text':'','retrieval_request_ids':[]}
                docs[doc_id]['retrieval_request_ids'].append(request_id)
            record['result_count']=len(result['results'])
            status.append(record)
        except (requests.RequestException,ValueError,OSError) as exc:
            status.append({**record,'status':'failed','error_type':type(exc).__name__})
    for doc in docs.values():
        doc['retrieval_request_ids']=sorted(set(doc['retrieval_request_ids']))
    return sorted(docs.values(),key=lambda d:d['document_id']),status


def match_candidates(episodes: list[dict],documents: list[dict],config: dict,reviews: list[dict] | None=None) -> list[dict]:
    """Transparent lexical baseline, not causal confidence or invented explanation."""
    markets={str(m['market_id']):m for m in config['markets']}
    review_map={(r['episode_id'],r['document_id']):r for r in (reviews or [])}
    settings=config.get('news',{})
    back=pd.Timedelta(hours=settings.get('lookback_hours',24))
    post=pd.Timedelta(hours=settings.get('post_hours',2))
    links=[]
    for event in episodes:
        market=markets[event['market_id']]
        start,end=pd.Timestamp(event['window_start']),pd.Timestamp(event['window_end'])
        candidates=[]
        for doc in documents:
            if not doc.get('document_id'):
                raise ValueError('Every imported document needs a stable document_id.')
            relevance=keyword_relevance(doc,market)
            if relevance<1.0:
                continue
            verified=verified_available_at(doc)
            claimed=aware_time(doc.get('published_at_claimed'))
            used_time=verified if verified is not None else claimed
            if used_time is not None and not (start-back<=used_time<=end+post):
                continue
            if used_time is None:
                role,temporal_weight='unknown_time',0.0
            elif used_time<start:
                role,temporal_weight='pre_window',2.0
            elif used_time<=end:
                role,temporal_weight='within_window_timing_ambiguous',1.0
            else:
                role,temporal_weight='after_window',0.0
            review=review_map.get((event['episode_id'],doc['document_id']),{})
            label=review.get('label','unreviewed')
            if label not in {'unreviewed','plausible_context','background','aftermath','rejected'}:
                raise ValueError(f'Unknown review label: {label}')
            candidates.append({'episode_id':event['episode_id'],'market_id':event['market_id'],
                'document_id':doc['document_id'],'url':doc['url'],'title':doc.get('title',''),
                'snippet':doc.get('snippet',''),'published_at_claimed':doc.get('published_at_claimed'),
                'verified_available_at':verified.isoformat() if verified is not None else None,
                'temporal_role':role,'timestamp_verified':verified is not None,
                'rank_score':relevance+temporal_weight+(0.5 if verified is not None else 0),
                'review_label':label,'review_note':review.get('note',''),
                'interpretation':'Candidate association; not evidence of causation or individual exposure.'})
        candidates.sort(key=lambda x:(-x['rank_score'],x['document_id']))
        seen_urls=set()
        for item in candidates:
            url=canonical_url(item['url'])
            if url not in seen_urls:
                links.append(item);seen_urls.add(url)
    return links


def context_asof(documents: list[dict],market: dict,cutoff: str) -> list[dict]:
    """Legacy timestamp helper. The D-C exporter additionally gates discovery provenance."""
    t=aware_time(cutoff)
    if t is None:
        raise ValueError('cutoff must include an explicit timezone.')
    output=[]
    for doc in documents:
        available=verified_available_at(doc)
        if available is not None and available<t and keyword_relevance(doc,market,verified_only=True)==1.0:
            output.append({'document_id':doc['document_id'],'url':doc['url'],
                           'available_at':available.isoformat(),'text':doc['verified_text']})
    return sorted(output,key=lambda x:(x['available_at'],x['document_id']))
