from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import pandas as pd
from .core import DetectorConfig,detect_movements,load_trades,make_bars,normalize_trades
from .news import dump_jsonl,load_jsonl,match_candidates,prepare_search_jobs,retrieve_news
from .report import build_report


def read_config(path: Path) -> tuple[dict,Path]:
    config=json.loads(path.read_text())
    markets=config.get('markets',[])
    ids=[str(m['market_id']) for m in markets]
    if not ids or len(ids)!=len(set(ids)):
        raise ValueError('Provide distinct market_id values, not pooled event IDs.')
    for market in markets:
        market['market_id']=str(market['market_id'])
        if not market.get('question') or not market.get('outcome1_label'):
            raise ValueError('Each contract needs its question and actual outcome1_label.')
        groups=market.get('required_term_groups',[])
        if not groups or any(not isinstance(g,list) or not g or any(not str(t).strip() for t in g) for g in groups):
            raise ValueError('required_term_groups: OR within each group, AND across groups.')
    base=path.resolve().parent
    config['data_path']=str((base/config['data_path']).resolve())
    output=(base/config.get('output_dir','outputs')).resolve()
    config['output_dir']=str(output)
    DetectorConfig(**config.get('detector',{}))
    return config,output


def fingerprint(config: dict) -> str:
    return hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()


def write_tables(bars: pd.DataFrame,episodes: list[dict],output: Path,parquet: bool) -> None:
    bars.to_csv(output/'bars.csv',index=False)
    dump_jsonl(output/'episodes.jsonl',episodes)
    pd.DataFrame(episodes).to_csv(output/'episodes.csv',index=False)
    if parquet:
        try:
            bars.to_parquet(output/'bars.parquet',index=False,engine='pyarrow')
            pd.DataFrame(episodes).to_parquet(output/'episodes.parquet',index=False,engine='pyarrow')
        except ImportError as exc:
            raise RuntimeError('Parquet outputs require pyarrow, or set write_parquet=false.') from exc


def analyze(config: dict,output: Path,overwrite: bool=False) -> None:
    if output.exists() and any(output.iterdir()) and not overwrite:
        raise FileExistsError(f'{output} is not empty. Choose a new output_dir or use --overwrite.')
    output.mkdir(parents=True,exist_ok=True)
    frame=load_trades(config['data_path'],[m['market_id'] for m in config['markets']])
    if frame.empty:
        raise ValueError('No rows for the configured contract IDs.')
    from .dc import participant_fills
    frame,participation_audit=participant_fills(frame)
    normalized,audit=normalize_trades(frame,config.get('input_kind','quant'))
    audit.update(participation_audit)
    absent={m['market_id'] for m in config['markets']}-set(normalized.market_id)
    if absent:
        raise ValueError(f'No valid trades for: {sorted(absent)}')
    detector=DetectorConfig(**config.get('detector',{}))
    bars,episodes=detect_movements(make_bars(normalized,detector),detector)
    write_tables(bars,episodes,output,config.get('write_parquet',True))
    dump_jsonl(output/'search_jobs.jsonl',prepare_search_jobs(episodes,config))
    for name in ('documents','attribution_links','search_status'):
        dump_jsonl(output/(name+'.jsonl'),[])
    manifest={'prototype_version':'0.2.0','synthetic':config.get('synthetic',False),
        'config':config,'config_sha256':fingerprint(config),'audit':audit,
        'normalized_projection_sha256':hashlib.sha256(normalized[
            ['market_id','timestamp','price_outcome1','token_amount','usd_amount']]
            .sort_values(['market_id','timestamp','price_outcome1','token_amount','usd_amount'])
            .to_csv(index=False).encode()).hexdigest(),
        'episode_count':len(episodes),'bar_count':len(bars),
        'coverage':{m['market_id']:{
            'first_bin':str(bars[bars.market_id.eq(m['market_id'])].bin_end.min()),
            'last_bin':str(bars[bars.market_id.eq(m['market_id'])].bin_end.max()),
            'baseline_ready_bins':int(bars[bars.market_id.eq(m['market_id'])].baseline_ready.sum())
        } for m in config['markets']},
        'versions':{p:importlib.metadata.version(p) for p in ['pandas','numpy','plotly','requests']},
        'limitations':[
            'No historical order book, order-submission reconstruction, or human/bot identification.',
            'Same-transaction economic duplication is not independently audited.',
            'No final resolution used. Outcome labels are supplied explicitly and validated by pilot.',
            'Analyze alone produces retrospective episodes, not pre-decision D-C. Pilot adds calendar discovery and strict D-C.',
            'Lexical/time candidate ranking only; no causal inference or automated timestamp verification.']}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    build_report(bars,episodes,[],[],config,output/'dashboard.html')
    print(f'{len(normalized):,} valid records; {len(episodes)} movement episodes.\n{output / "dashboard.html"}')


def read_run(config: dict,output: Path) -> tuple[pd.DataFrame,list[dict]]:
    manifest=json.loads((output/'manifest.json').read_text())
    if manifest['config_sha256']!=fingerprint(config):
        raise ValueError('Config changed since analyze. Use a new output directory and rerun analyze.')
    bars=pd.read_csv(output/'bars.csv',dtype={'market_id':str})
    bars['bin_end']=pd.to_datetime(bars.bin_end,utc=True)
    return bars,load_jsonl(output/'episodes.jsonl')


def render(config: dict,output: Path,documents_path: Path | None=None,reviews_path: Path | None=None) -> None:
    bars,episodes=read_run(config,output)
    documents=load_jsonl(documents_path or output/'documents.jsonl')
    links=match_candidates(episodes,documents,config,load_jsonl(reviews_path) if reviews_path else [])
    dump_jsonl(output/'attribution_links.jsonl',links)
    if documents_path:
        dump_jsonl(output/'documents.jsonl',documents)
    dump_jsonl(output/'review_template.jsonl',[
        {'episode_id':x['episode_id'],'document_id':x['document_id'],'label':x['review_label'],'note':x['review_note']} for x in links])
    if config.get('write_parquet',True):
        pd.DataFrame(links).to_parquet(output/'attribution_links.parquet',engine='pyarrow',index=False)
    status=load_jsonl(output/'search_status.jsonl')
    build_report(bars,episodes,links,status,config,output/'dashboard.html')
    print(f'{len(documents)} document versions; {len(links)} candidate links.\n{output / "dashboard.html"}')


def main() -> None:
    parser=argparse.ArgumentParser(description='XVI trade-price and candidate-news prototype')
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('analyze','news','render'):
        p=sub.add_parser(name);p.add_argument('--config',type=Path,required=True)
        if name=='analyze':
            p.add_argument('--overwrite',action='store_true')
        if name=='render':
            p.add_argument('--documents',type=Path);p.add_argument('--reviews',type=Path)
    p=sub.add_parser('demo');p.add_argument('--output',type=Path,default=Path('demo'))
    args=parser.parse_args()
    try:
        if args.command=='demo':
            from .demo import create_demo
            path=create_demo(args.output)
            config,output=read_config(path)
            analyze(config,output)
            render(config,output,args.output/'synthetic_news.jsonl')
            return
        config,output=read_config(args.config)
        if args.command=='analyze':
            analyze(config,output,args.overwrite)
        elif args.command=='news':
            _,episodes=read_run(config,output)
            documents,status=retrieve_news(prepare_search_jobs(episodes,config),config,output/'search_cache')
            existing={d['document_id']:d for d in load_jsonl(output/'documents.jsonl')}
            for doc in documents:
                if doc['document_id'] not in existing:
                    existing[doc['document_id']]=doc
            dump_jsonl(output/'documents.jsonl',sorted(existing.values(),key=lambda d:d['document_id']))
            dump_jsonl(output/'search_status.jsonl',status)
            render(config,output)
            failed=sum(s['status'] in {'failed','missing_api_key','budget_skipped'} for s in status)
            print(f'Incomplete/skipped search jobs: {failed}. See search_status.jsonl.')
        else:
            for supplied in (args.documents,args.reviews):
                if supplied is not None and not supplied.exists():
                    raise FileNotFoundError(supplied)
            render(config,output,args.documents,args.reviews)
    except (ValueError,KeyError,OSError,RuntimeError,ImportError) as exc:
        parser.exit(2,f'Error: {exc}\n')

if __name__=='__main__':
    main()
