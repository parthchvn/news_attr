from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .news import dump_jsonl


def create_demo(output: Path) -> Path:
    """Invented reproducible fixture; never represented as real market data."""
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f'Demo directory already exists: {output}')
    output.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(20260913)
    start=pd.Timestamp('2025-01-01T00:00:00Z')
    records=[]
    markets=[
        {'market_id':'SYNTHETIC_A','question':'SYNTHETIC: Will Country A introduce the proposed tariff?',
         'outcome1_label':'Yes','outcome2_label':'No','search_queries':['Country A proposed tariff announcement'],
         'required_term_groups':[['Country A'],['tariff','tariffs']]},
        {'market_id':'SYNTHETIC_B','question':'SYNTHETIC: Will City B approve the transit plan?',
         'outcome1_label':'Yes','outcome2_label':'No','search_queries':['City B transit plan vote'],
         'required_term_groups':[['City B'],['transit']]}]
    for market in markets:
        for i in range(864):
            if 700<=i<710:
                continue
            if market['market_id']=='SYNTHETIC_A':
                latent=.35+(.16 if i>=360 else 0)-(.10 if i>=600 else 0)
            else:
                latent=.58
                if 360<=i<366:
                    latent+=.09 if i%2==0 else -.09
                if i>=600:
                    latent+=.14
            for j in range(4):
                t=start+pd.Timedelta(minutes=5*i,seconds=10+j*55)
                side='token1' if j%2==0 else 'token2'
                p1=float(np.clip(latent+rng.normal(0,.0015),.01,.99))
                observed=p1 if side=='token1' else 1-p1
                shares=float(rng.uniform(20,150))
                records.append({'market_id':market['market_id'],'timestamp':int(t.timestamp()),
                    'price':observed,'token_amount':shares,'usd_amount':observed*shares,'nonusdc_side':side,
                    'transaction_hash':f'{market["market_id"]}-{i}-{j}','log_index':0,'contract':'synthetic_contract'})
    pd.DataFrame(records).to_csv(output/'synthetic_trades.csv',index=False)
    config={'synthetic':True,'data_path':'synthetic_trades.csv','input_kind':'trades',
        'output_dir':'results','write_parquet':False,'markets':markets,
        'detector':{'bin_minutes':5,'horizon_minutes':15,'baseline_hours':24,'min_baseline_bins':24,
                    'jump_pp':3,'rv_pp':3,'z_threshold':4,'scale_floor_pp':.5,'merge_minutes':30},
        'news':{'lookback_hours':24,'post_hours':2,'max_episodes_per_market':10,'max_results_per_query':10,'max_requests':20}}
    path=output/'config.json';path.write_text(json.dumps(config,indent=2))
    docs=[]
    for name,text in [('A','Country A announces the proposed tariff'),('B','City B issues an update on the transit plan')]:
        for label,timestamp in [('before','2025-01-02T05:35:00Z'),('inside','2025-01-02T06:06:00Z'),('after','2025-01-02T06:40:00Z')]:
            docs.append({'document_id':f'SYNTHETIC_{name}_{label}','url':f'https://example.invalid/synthetic/{name}/{label}',
                'title':f'SYNTHETIC {label}: {text}','snippet':f'Invented test article: {text}. This is not a historical source.',
                'published_at_claimed':timestamp,'timestamp_status':'synthetic_fixture','verified_available_at':None,
                'verification_evidence':'','verified_text':''})
    dump_jsonl(output/'synthetic_news.jsonl',docs)
    return path
