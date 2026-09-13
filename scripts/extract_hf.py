"""Extract only the requested markets from a pinned SII snapshot.

Run from an internet-enabled environment. Uses DuckDB's HTTP range reads and
Parquet predicate/projection pushdown; this can still transfer many GB when
market_id is not clustered. Never loads the entire source into pandas.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

REPO = 'SII-WANGZJ/Polymarket_data'
REVISION = '6d3c336c39cf1a2dfe53d702ad2c110ab5bdbfde'
IDS = ('507300', '2446852')
COLUMNS = ['timestamp','block_number','transaction_hash','log_index','contract',
           'market_id','condition_id','event_id','maker','taker','price',
           'usd_amount','token_amount','maker_direction','taker_direction',
           'nonusdc_side','asset_id']

def extract(output: str, source: str | None = None,
            markets_source: str | None = None, revision: str = REVISION) -> dict:
    import duckdb
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    base = f'https://huggingface.co/datasets/{REPO}/resolve/{revision}/'
    source = source or base + 'trades.parquet'
    markets_source = markets_source or base + 'markets.parquet'
    status = {'status':'running','dataset':REPO,'revision':revision,
              'market_ids':list(IDS),'source':source,'markets_source':markets_source,
              'started_at':datetime.now(timezone.utc).isoformat(),
              'screenshot_counts_are_unverified':True}
    def write_status():
        (out/'extraction_manifest.json').write_text(json.dumps(status,indent=2,default=str))
    write_status()
    con = duckdb.connect(str(out/'extraction.duckdb'))
    try:
        con.execute("SET memory_limit='2GB'")
        con.execute('SET threads=4')
        if source.startswith('https:') or markets_source.startswith('https:'):
            con.execute('INSTALL httpfs; LOAD httpfs;')
            con.execute('SET http_timeout=120000')
            con.execute('SET http_retries=5')
        # IDs are strings in the documented schema. Do not pool parent event_id.
        con.execute('CREATE OR REPLACE TABLE selected_markets AS SELECT * FROM read_parquet(?) WHERE id IN (?,?)', [markets_source,*IDS])
        markets=con.execute('SELECT * FROM selected_markets ORDER BY id').fetchdf()
        if set(markets['id'].astype(str)) != set(IDS):
            raise ValueError('Requested market IDs are missing from this snapshot: '+str(markets['id'].tolist()))
        markets.to_csv(out/'markets.csv',index=False)
        (out/'markets.json').write_text(markets.to_json(orient='records',date_format='iso',indent=2))
        expected={'507300':'inter','2446852':'ronaldo'}
        for row in markets.to_dict('records'):
            if expected[str(row['id'])] not in str(row['question']).lower():
                raise ValueError('Market question does not match the requested screenshot: '+str(row))
        status['market_metadata_verified']=True
        write_status()
        print('Metadata verified. Filtering remote trades; large range scan may take time.',flush=True)
        cols=','.join('"'+c+'"' for c in COLUMNS)
        con.execute(f'CREATE OR REPLACE TABLE selected_trades AS SELECT {cols} FROM read_parquet(?) WHERE market_id IN (?,?)', [source,*IDS])
        # Stable on-chain ordering; filtering and exact event deduplication are
        # done by the analysis layer, not silently inside this source extract.
        path=str(out/'trades.parquet').replace("'","''")
        con.execute(f"COPY (SELECT * FROM selected_trades ORDER BY timestamp,block_number,transaction_hash,log_index) TO '{path}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        con.execute('SELECT * FROM selected_trades ORDER BY timestamp,block_number,transaction_hash,log_index').fetchdf().to_csv(out/'trades.csv.gz',index=False,compression='gzip')
        summary=con.execute('SELECT market_id,COUNT(*) AS raw_fills,SUM(usd_amount) AS raw_usd_amount,MIN(timestamp) AS first_timestamp,MAX(timestamp) AS last_timestamp FROM selected_trades GROUP BY market_id ORDER BY market_id').fetchdf()
        status['summary']=summary.to_dict('records')
        status['status']='complete' if set(summary.market_id.astype(str))==set(IDS) else 'missing_trades'
        status['sha256_trades_parquet']=hashlib.sha256((out/'trades.parquet').read_bytes()).hexdigest()
        status['completed_at']=datetime.now(timezone.utc).isoformat()
        write_status()
        print(json.dumps(status,indent=2,default=str),flush=True)
        if status['status']!='complete':
            raise ValueError('At least one requested market has no trades in the snapshot')
        return status
    except Exception as exc:
        status.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        write_status()
        raise
    finally:
        con.close()
        db=out/'extraction.duckdb'
        if db.exists(): db.unlink()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',default='data/selected')
    p.add_argument('--source',help='Optional local trades.parquet instead of remote scan')
    p.add_argument('--markets-source',help='Optional local markets.parquet')
    p.add_argument('--revision',default=REVISION)
    a=p.parse_args()
    extract(a.output,a.source,a.markets_source,a.revision)
