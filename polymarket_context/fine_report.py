"""Offline, fine-resolution review UI. Price detail and source evidence stay distinct."""
from __future__ import annotations
import html
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs


def gap_line(group: pd.DataFrame, seconds: int, column: str) -> tuple[list, list]:
    """Insert a null after each missing-bin boundary; never draw through a gap."""
    x, y, previous = [], [], None
    for row in group.itertuples():
        time = row.bin_end
        if previous is not None and (time-previous).total_seconds() > seconds:
            x.append((previous+pd.Timedelta(seconds=seconds)).isoformat())
            y.append(None)
        x.append(time.isoformat())
        y.append(float(getattr(row, column)))
        previous = time
    return x, y


def safe_json(value) -> str:
    # Prevent a publisher headline or market question from terminating script tags.
    return json.dumps(value, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&','\\u0026')


def write_report(bars, trades, alerts, groups, links, documents, config, cfg, summary, output: Path) -> None:
    pieces = ['<!doctype html><!-- fine-v2-entry --><html><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>XVI | Fine price movements</title><style>',
        'body{font:16px system-ui;max-width:1350px;margin:28px auto;padding:0 20px;line-height:1.55}',
        'h1{font-size:32px}h2{margin-top:48px}.notice,.card{border:1px solid;border-radius:8px;padding:16px;margin:18px 0}',
        'button,select{font:inherit;padding:8px;margin:4px;cursor:pointer}table{border-collapse:collapse;width:100%;font-size:14px}',
        'td,th{text-align:left;padding:8px;border-bottom:1px solid}a{overflow-wrap:anywhere}.tablebox{max-height:360px;overflow:auto}',
        '.muted{font-size:14px}code{overflow-wrap:anywhere}.selected{scroll-margin-top:20px}</style>',
        '<script>'+get_plotlyjs()+'</script></head><body>',
        '<h1>XVI | Fine price movements</h1>',
        f'<p><b>{cfg.bin_seconds}-second observations</b> · individual alerts · UTC · execution prices, not buy quotes</p>',
        '<div class="notice"><b>Two separate marker categories.</b> ',
        'Supported changes pass size and data-support checks. Unusual changes additionally pass a past-only robust abnormality rule. ',
        'Neither category is a proven news shock or an independently validated causal event. Multiple markers may describe one evolving move.</div>',
        '<p>The default line is a share-weighted median of executions within each bin, used by the detector. ',
        'The original-style weighted average and every individual fill are available in the legend. ',
        'No empty bins are filled or interpolated. A raw fill timestamp is not an order-submission timestamp.</p>']
    for i, market in enumerate(config['markets']):
        mid = market['market_id']
        bb = bars[bars.market_id.eq(mid)].sort_values('bin_end')
        tt = trades[trades.market_id.eq(mid)]
        aa = [a for a in alerts if a['market_id']==mid]
        cc = summary['markets'][mid]
        figures = go.Figure()
        x, y = gap_line(bb, cfg.bin_seconds, 'median_price')
        figures.add_scatter(x=x, y=y, mode='lines+markers', marker={'size':2},
            line={'width':1}, connectgaps=False, name=f'{cfg.bin_seconds}s weighted median (detector)',
            hovertemplate='%{x}<br>Median execution: $%{y:.4f}<extra></extra>')
        x, y = gap_line(bb, cfg.bin_seconds, 'price')
        figures.add_scatter(x=x, y=y, mode='lines', line={'width':1}, connectgaps=False,
            name=f'{cfg.bin_seconds}s share-weighted average', visible='legendonly',
            hovertemplate='%{x}<br>Average execution: $%{y:.4f}<extra></extra>')
        figures.add_scatter(x=tt.timestamp.map(lambda t:t.isoformat()).tolist(),
            y=tt.price_outcome1.to_numpy(), mode='markers', marker={'size':3, 'opacity':.4},
            name='Every recorded fill (Yes equivalent)', visible='legendonly',
            hovertemplate='%{x}<br>Individual execution: $%{y:.4f}<extra></extra>')
        for tier, label, symbol in [('supported_change','Supported size changes','circle-open'),
                                     ('unusual_change','Unusual changes (past-only score)','diamond')]:
            selected = [a for a in aa if a['tier']==tier]
            figures.add_scatter(x=[a['detected_at'] for a in selected], y=[a['median_price'] for a in selected],
                mode='markers', name=label, marker={'size':9,'symbol':symbol},
                customdata=[a['alert_id'] for a in selected],
                hovertemplate='%{x}<br>$%{y:.4f}<br>Click for horizons and evidence<extra></extra>')
        windows = [w for w in config.get('review_windows',[]) if w['market_id']==mid]
        xr = [windows[0]['start'],windows[0]['end']] if windows else [bb.bin_end.min().isoformat(),bb.bin_end.max().isoformat()]
        figures.update_layout(height=550, margin={'t':20,'b':115},
            xaxis={'title':'UTC bin end (observations in the preceding bin)', 'range':xr},
            yaxis={'title':f'{market["outcome1_label"]}-equivalent execution price per share',
                   'tickprefix':'$', 'range':[0,1]},
            legend={'orientation':'h','y':-.22}, dragmode='zoom')
        pieces.append(f'<section><h2>{html.escape(market["question"])}</h2>')
        pieces.append(f'<p>{cc["valid_fills"]:,} valid fills · {cc["observed_bins"]:,} observed bins · '
            f'<b>{cc["individual_alert_times"]:,} individual alert times</b> across the full history '
            f'({cc["unusual_alert_times"]:,} unusual, {cc["supported_size_only_times"]:,} size-only). '
            f'Legacy view: {cc["legacy_episode_dots"]} episode dots.</p>')
        pieces.append(f'<div id="controls-{i}"><button data-all="{i}">Full history</button>')
        for j,w in enumerate(windows):
            pieces.append(f'<button data-window="{i}:{j}">{html.escape(w["label"])}</button>')
        pieces.append(f'<select id="filter-{i}" aria-label="Alert filter"><option value="all">All supported alerts</option>'
            '<option value="unusual">Unusual only</option><option value="short">30–60s horizon alerts</option></select></div>')
        pieces.append(figures.to_html(full_html=False,include_plotlyjs=False,div_id=f'fine-{i}'))
        pieces.append(f'<p id="visible-{i}"></p><div class="card selected" id="selection-{i}">'
            'Click an alert marker or a row below. The panel will show every triggering horizon and existing source candidates.</div>'
            f'<div class="tablebox"><table><thead><tr><th>UTC</th><th>Price</th><th>Tier</th><th>Horizons (seconds)</th></tr></thead>'
            f'<tbody id="rows-{i}"></tbody></table></div></section>')
    payload = {
        'markets': config['markets'], 'alerts': alerts, 'groups':groups, 'links':links,
        'documents':documents, 'review_windows':config.get('review_windows',[]), 'summary':summary}
    pieces.append('<script>const DATA='+safe_json(payload)+';</script>')
    pieces.append(r'''<script>
function esc(x){return String(x??'unknown').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmt(x){return x==null?'not available':Number(x).toFixed(2);}
const A=new Map(DATA.alerts.map(a=>[a.alert_id,a]));
const DOC=new Map(DATA.documents.map(d=>[d.document_id,d]));
function selectAlert(i,id){
 const a=A.get(id); if(!a)return;
 let t='<h3>'+esc(a.detected_at)+' — '+esc(a.tier)+'</h3>';
 t+='<p>Median: $'+Number(a.median_price).toFixed(4)+'; average: $'+Number(a.price).toFixed(4)+
 '; '+a.transaction_count+' distinct transactions in this bin, '+a.corroborating_transactions+' corroborating the median level. Baseline: '+esc(a.baseline_note)+'.</p>';
 t+='<table><tr><th>Horizon</th><th>Net change (pp)</th><th>Variation (pp)</th><th>Coverage</th><th>Net / variation score</th><th>Signals</th></tr>';
 a.signals.forEach(s=>{t+='<tr><td>'+s.horizon_seconds+'s</td><td>'+fmt(s.change_pp)+'</td><td>'+fmt(s.variation_pp)+
 '</td><td>'+fmt(s.coverage*100)+'%</td><td>'+fmt(s.jump_z)+' / '+fmt(s.variation_z)+
 '</td><td>'+esc(s.signals.join(', '))+'</td></tr>';});t+='</table>';
 t+='<p class="muted">Each horizon compares observed bins. Scores are heuristic, not p-values. '
 +'Overlapping horizons and successive alerts are not independent events. Window starts at '+esc(a.window_start)+'.</p>';
 const ll=DATA.links.filter(l=>l.alert_id===id);
 if(!ll.length){t+='<p><b>No source match has been established for this alert.</b> A news retrieval job is planned, not executed.</p>';}
 else{t+='<h4>Existing manual source candidates — not new attribution</h4><p>These sources were previously linked to a broad, overlapping legacy window. Their versions remain unverified; they are not promoted into strict C.</p>';
 ll.forEach(l=>{const d=DOC.get(l.document_id);if(!d)return;const u=String(d.url||'');
 const title=/^https?:\/\//i.test(u)?'<a target="_blank" rel="noopener noreferrer" href="'+esc(u)+'">'+esc(d.title)+'</a>':esc(d.title);
 t+='<p>'+title+'<br>'+esc(d.snippet)+'<br><small>Claimed publication: '+esc(d.published_at_claimed||d.publication_date_claimed)+
 ' · '+esc(l.temporal_role)+' · unverified</small></p>';});}
 document.getElementById('selection-'+i).innerHTML=t;
}
function allowed(i){let mode=document.getElementById('filter-'+i).value;
 return DATA.alerts.filter(a=>a.market_id===DATA.markets[i].market_id &&
 (mode==='all'||mode==='unusual'&&a.tier==='unusual_change'||mode==='short'&&a.horizons_seconds.some(h=>h<=60)));}
function table(i){let plot=document.getElementById('fine-'+i),range=plot.layout.xaxis.range;
 let aa=allowed(i).filter(a=>!range||Date.parse(a.detected_at)>=Date.parse(range[0])&&Date.parse(a.detected_at)<=Date.parse(range[1]));
 document.getElementById('visible-'+i).textContent=aa.length+' matching alert timestamps in the visible time range. Table shows first '+Math.min(100,aa.length)+'. All markers remain available; zoom to inspect.';
 let body=document.getElementById('rows-'+i);body.innerHTML='';
 aa.slice(0,100).forEach(a=>{let tr=document.createElement('tr');tr.style.cursor='pointer';
 tr.innerHTML='<td>'+esc(a.detected_at)+'</td><td>$'+a.median_price.toFixed(4)+'</td><td>'+esc(a.tier)+'</td><td>'+a.horizons_seconds.join(', ')+'</td>';
 tr.onclick=()=>{selectAlert(i,a.alert_id);document.getElementById('selection-'+i).scrollIntoView({behavior:'smooth',block:'nearest'});};body.appendChild(tr);});}
DATA.markets.forEach((m,i)=>{let plot=document.getElementById('fine-'+i);
 plot.on('plotly_click',e=>{let id=e.points[0]?.customdata;if(A.has(id))selectAlert(i,id);});
 plot.on('plotly_relayout',()=>table(i));
 document.getElementById('filter-'+i).onchange=()=>{let aa=allowed(i);
 ['supported_change','unusual_change'].forEach((tier,j)=>{let v=aa.filter(a=>a.tier===tier);
 Plotly.restyle(plot,{x:[v.map(a=>a.detected_at)],y:[v.map(a=>a.median_price)],customdata:[v.map(a=>a.alert_id)]},[3+j]);});table(i);};
 document.querySelector('[data-all="'+i+'"]').onclick=()=>Plotly.relayout(plot,{'xaxis.autorange':true});
 const windows=DATA.review_windows.filter(w=>w.market_id===m.market_id);
 windows.forEach((w,j)=>{document.querySelector('[data-window="'+i+':'+j+'"]').onclick=()=>Plotly.relayout(plot,{'xaxis.range':[w.start,w.end],'xaxis.autorange':false});});
 table(i);
});
</script>''')
    pieces.append('<h2>What changed and what did not</h2><p>All qualifying timestamps are displayed. '
        f'News grouping only joins nearby alerts within {cfg.news_merge_seconds}s, with a maximum '
        f'{cfg.news_max_span_seconds}s first-to-last detection span. It never removes markers. '
        'New search jobs are an explicit queue; no provider was called in this build. '
        'Existing conservative D–C exports are unchanged and still use their legacy price-context features. '
        'Do not attach retrospectively selected source text to earlier decisions.</p>'
        '<p>Use <code>fine/alerts.jsonl</code> for exact trigger records and <code>fine/diagnostics.csv.gz</code> '
        'for eligible and rejected windows. Read <code>docs/FINE_DETECTION.md</code> for formulas, '
        'defaults, missingness handling and test limitations. Higher temporal resolution does not prove higher causal accuracy.</p></body></html>')
    output.write_text('\n'.join(pieces), encoding='utf-8')
