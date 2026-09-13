"""Two-market runner. Run extraction first, then --stage all or each stage."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .__main__ import read_config,analyze,read_run,render
from .core import load_trades,normalize_trades
from .collect import discovery_jobs,collect
from .dc import participant_fills,export_dc
from .news import dump_jsonl,load_jsonl,verified_available_at


def run(config_path: Path,stage: str,overwrite: bool=False,verified_path: Path | None=None) -> dict:
    config,output=read_config(config_path)
    metadata_file=config.get('markets_metadata_path')
    if metadata_file:
        path=config_path.resolve().parent/metadata_file
        if not path.exists():
            raise FileNotFoundError(f'{path}: run scripts/extract_hf.py first')
        metadata={str(m['id']):m for m in json.loads(path.read_text())}
        for m in config['markets']:
            actual=metadata.get(m['market_id'])
            if not actual or actual['question'].casefold()!=m['question'].casefold():
                raise ValueError('Contract metadata does not match configured question: '+m['market_id'])
            if actual['answer1']!=m['outcome1_label'] or actual['answer2']!=m['outcome2_label']:
                raise ValueError('Outcome label mismatch; inspect extracted markets.json')
    if stage in {'all','analyze'}:
        analyze(config,output,overwrite)
    bars,episodes=read_run(config,output)
    if stage in {'all','news'}:
        jobs=discovery_jobs(bars,episodes,config)
        dump_jsonl(output/'search_jobs.jsonl',jobs)
        new,statuses=collect(jobs,config,output/'search_cache')
        merged={d['document_id']:d for d in load_jsonl(output/'documents.jsonl')}
        for d in new:
            old=merged.get(d['document_id'])
            if old:
                for field in ('discovery_modes','market_ids','retrieval_request_ids'):
                    old[field]=sorted(set(old.get(field,[])+d.get(field,[])))
            else:
                merged[d['document_id']]=d
        dump_jsonl(output/'documents.jsonl',list(merged.values()))
        dump_jsonl(output/'search_status.jsonl',statuses)
    if verified_path:
        if not verified_path.exists():
            raise FileNotFoundError(verified_path)
        merged={d['document_id']:d for d in load_jsonl(output/'documents.jsonl')}
        for d in load_jsonl(verified_path):
            if verified_available_at(d) is None:
                raise ValueError('Verified import lacks evidence, exact text or timezone-aware availability')
            old=merged.get(d['document_id'],{})
            merged[d['document_id']]={**old,**d}
        dump_jsonl(output/'documents.jsonl',list(merged.values()))
    documents=load_jsonl(output/'documents.jsonl')
    summary={}
    if stage in {'all','dc'}:
        raw=load_trades(config['data_path'],[m['market_id'] for m in config['markets']])
        raw,_=participant_fills(raw)
        trades,_=normalize_trades(raw,config.get('input_kind','trades'))
        summary=export_dc(trades,bars,documents,config,output)
    render(config,output)
    coverage={mid:{
        'documents':sum(mid in d.get('market_ids',[]) for d in documents),
        'candidate_links':sum(l['market_id']==mid for l in load_jsonl(output/'attribution_links.jsonl')),
        'episodes':sum(e['market_id']==mid for e in episodes)} for mid in [m['market_id'] for m in config['markets']]}
    if not summary and (output/'dc_manifest.json').exists():
        summary=json.loads((output/'dc_manifest.json').read_text())
    status=load_jsonl(output/'search_status.jsonl')
    result={'stage':stage,'coverage':coverage,'dc':summary,
        'search_status_counts':{s:sum(x['status']==s for x in status) for s in sorted({x['status'] for x in status})}}
    (output/'pilot_status.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=Path('config.two_markets.json'))
    p.add_argument('--stage',choices=['all','analyze','news','dc','render'],default='all')
    p.add_argument('--overwrite',action='store_true')
    p.add_argument('--verified-documents',type=Path)
    a=p.parse_args()
    try:
        run(a.config,a.stage,a.overwrite,a.verified_documents)
    except (ValueError,OSError,RuntimeError,ImportError,KeyError) as exc:
        p.exit(2,f'Error: {exc}\n')

if __name__=='__main__':
    main()
