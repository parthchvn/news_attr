"""Reproduce real prices and D-C with inspected, unverified news candidates.
No paid API or RSS requests. Manual fallback, not a complete news archive.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from itertools import zip_longest
from pathlib import Path
import pandas as pd
from .__main__ import read_config,analyze,read_run
from .core import load_trades,normalize_trades
from .dc import participant_fills,export_dc
from .news import load_jsonl,dump_jsonl,match_candidates,aware_time
from .report import build_report


def match_seed(episodes: list[dict],documents: list[dict],config: dict) -> list[dict]:
    """Restrict date-only sources to explicitly selected retrospective windows."""
    docs={d['document_id']:d for d in documents}
    result=[]
    for link in match_candidates(episodes,documents,config):
        doc=docs[link['document_id']]
        allowed=doc.get('candidate_episode_ids')
        if allowed is not None and link['episode_id'] not in allowed:
            continue
        link['context_type']=doc.get('context_type','candidate')
        link['publication_date_claimed']=doc.get('publication_date_claimed')
        link['source_timing_note']=doc.get('timing_evidence','')
        link['information_event_id']=doc.get('information_event_id')
        if aware_time(doc.get('published_at_claimed')) is None:
            if not allowed:
                continue
            link['temporal_role']='date_only_timing_ambiguous'
            link['rank_score']=1.0
        if doc.get('context_type')=='retrospective_match_report':
            link['temporal_role']='aftermath_report_not_pre_move_evidence'
            link['rank_score']=0.5
        result.append(link)
    return result


def join_candidate_dataset(output: Path) -> dict:
    """One-row D/C_candidate view; never substitutes it for strict C."""
    count=with_news=0
    per_market={}
    with gzip.open(output/'dc.jsonl.gz','rt',encoding='utf-8') as df,gzip.open(output/'decision_news_candidates.jsonl.gz','rt',encoding='utf-8') as nf,gzip.open(output/'dc_candidate.jsonl.gz','wt',encoding='utf-8') as out:
        for dl,nl in zip_longest(df,nf):
            if dl is None or nl is None:
                raise ValueError('Decision and candidate exports have different row counts')
            d,n=json.loads(dl),json.loads(nl)
            if d['decision_id']!=n['decision_id']:
                raise ValueError('Decision and candidate identifiers are misaligned')
            candidates=n['research_candidates_NOT_C']
            context={**d['C'],'news_candidates':candidates}
            context.pop('news',None)
            row={'decision_id':d['decision_id'],'split_group':d['split_group'],'D':d['D'],
                'C_candidate':context,'training_eligible':False,
                'warning':'Exploratory only: source text versions are not verified; documents were selected retrospectively around market events.'}
            out.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
            count+=1;with_news+=bool(candidates)
            mid=d['D']['market_id']
            per_market[mid]=per_market.get(mid,0)+int(bool(candidates))
    return {'rows':count,'rows_with_candidate_news':with_news,'by_market':per_market}


def run(config_path: Path,documents_path: Path,failed_status: Path | None=None) -> dict:
    config,output=read_config(config_path)
    meta_path=config_path.resolve().parent/config['markets_metadata_path']
    metadata={str(m['id']):m for m in json.loads(meta_path.read_text())}
    for m in config['markets']:
        a=metadata[m['market_id']]
        if a['question']!=m['question'] or a['answer1']!=m['outcome1_label'] or a['answer2']!=m['outcome2_label']:
            raise ValueError('Market metadata mismatch: '+m['market_id'])
    source=json.loads((meta_path.parent/'extraction_manifest.json').read_text())
    if source['status']!='complete':
        raise ValueError('The source extract is incomplete')
    documents=load_jsonl(documents_path)
    if not documents:
        raise ValueError('No candidate documents supplied')
    for d in documents:
        if d.get('timestamp_status')=='verified' or d.get('verified_text'):
            raise ValueError('Fallback is for unverified candidates; use audited import for strict news')
    analyze(config,output,overwrite=True)
    bars,episodes=read_run(config,output)
    dump_jsonl(output/'documents.jsonl',documents)
    status=load_jsonl(failed_status) if failed_status else []
    status.append({'status':'manual_fallback_loaded','document_count':len(documents),
        'method':'Inspected publisher pages using web search; original RSS run had 42 HTTP failures.',
        'original_run':'https://github.com/parthchvn/news_attr/actions/runs/34778661460',
        'complete_archive':False})
    dump_jsonl(output/'search_status.jsonl',status)
    links=match_seed(episodes,documents,config)
    dump_jsonl(output/'attribution_links.jsonl',links)
    pd.DataFrame(links).to_parquet(output/'attribution_links.parquet',index=False)
    dump_jsonl(output/'review_template.jsonl',[{'episode_id':l['episode_id'],'document_id':l['document_id'],'label':'unreviewed','note':''} for l in links])
    build_report(bars,episodes,links,status,config,output/'dashboard.html')
    text=(output/'dashboard.html').read_text()
    text=text.replace('<h1>XVI | Market context review</h1>', '<h1>XVI | Market context review</h1><div class="notice"><strong>MANUAL NEWS FALLBACK.</strong> The automated RSS run failed. These inspected source records are a limited candidate corpus, not complete news coverage. Date-only and updated reports are not verified pre-move information. Strict C.news remains empty; C_candidate is for research review only.</div>')
    (output/'dashboard.html').write_text(text)
    raw=load_trades(config['data_path'],[m['market_id'] for m in config['markets']])
    raw,_=participant_fills(raw)
    normalized,audit=normalize_trades(raw,'trades')
    dc=export_dc(normalized,bars,documents,config,output)
    candidate=join_candidate_dataset(output)
    report={'mode':'real_trades_manual_candidate_news_fallback','source_revision':source['revision'],
        'documents':len(documents),'candidate_links':len(links),'dc':dc,'candidate_dataset':candidate,
        'coverage':{m['market_id']:{'valid_fills':int(normalized.market_id.eq(m['market_id']).sum()),
            'episodes':sum(e['market_id']==m['market_id'] for e in episodes),
            'documents':sum(m['market_id'] in d.get('market_ids',[]) for d in documents),
            'candidate_links':sum(l['market_id']==m['market_id'] for l in links),
            'episodes_with_candidates':len({l['episode_id'] for l in links if l['market_id']==m['market_id']})} for m in config['markets']},
        'rss_original_failed_requests':42,'strict_news_version_audit_completed':False,
        'unattributed_episodes':[e['episode_id'] for e in episodes if not any(l['episode_id']==e['episode_id'] for l in links)],
        'candidate_corpus_sha256':hashlib.sha256(documents_path.read_bytes()).hexdigest()}
    (output/'pilot_status.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=Path('config.two_markets.json'))
    p.add_argument('--documents',type=Path,default=Path('context/seed_documents.jsonl'))
    p.add_argument('--failed-search-status',type=Path)
    a=p.parse_args()
    run(a.config,a.documents,a.failed_search_status)

if __name__=='__main__':
    main()
