from __future__ import annotations
import html
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
from .news import canonical_url


def build_report(bars: pd.DataFrame,episodes: list[dict],links: list[dict],status: list[dict],config: dict,output: Path) -> None:
    esc=lambda v: html.escape(str(v if v is not None else 'unknown'))
    pieces=['<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>XVI | Market context review</title>',
        '<style>body{font:16px system-ui,sans-serif;max-width:1200px;margin:32px auto;padding:0 22px;line-height:1.5}h1{font-size:32px}h2{margin-top:48px}small{font-size:13px}.notice{border:2px solid;padding:14px;margin:18px 0}.card{border:1px solid;border-radius:8px;padding:16px;margin:15px 0}summary{cursor:pointer;font-weight:600}a{overflow-wrap:anywhere}.snippet{max-width:95ch}</style></head><body>',
        '<h1>XVI | Market context review</h1>']
    if config.get('synthetic',False):
        pieces.append('<div class="notice"><strong>SYNTHETIC DEMO — invented markets, trades, and articles.</strong> Software test only, not empirical evidence.</div>')
    pieces.append('<p>Trade-derived outcome-1 price · UTC · retrospective review</p><div class="notice">Markers identify movement windows, not proven news causes. Publication claims need version/timestamp verification. Gaps mean no observed trades. Notional and counts are recorded-fill aggregates, not audited economic turnover.</div>')
    pieces.append(f'<p>{len(config["markets"])} contracts · {len(episodes)} episodes · {len(links)} candidate links</p>')
    include_js=True
    for i,market in enumerate(config['markets']):
        mid=str(market['market_id'])
        group=bars[bars.market_id.astype(str).eq(mid)]
        events=[e for e in episodes if e['market_id']==mid]
        pieces.append(f'<h2>{esc(market["question"])}</h2><p>Contract {esc(mid)} · outcome 1: {esc(market["outcome1_label"])} · {int(group.record_count.sum()):,} recorded fills · {int((~group.observed).sum()):,} empty bins</p>')
        fig=go.Figure()
        fig.add_scatter(x=group.bin_end,y=group.price,mode='lines',connectgaps=False,name='Share-weighted execution price')
        if events:
            fig.add_scatter(x=[e['detected_at'] for e in events],y=[e['marker_price'] for e in events],
                mode='markers',marker={'size':10,'symbol':'diamond'},customdata=[e['episode_id'] for e in events],
                text=[f'{e["kind"]}: {e["initial_displacement_pp"]:+.2f} pp<br>Click for candidates' for e in events],
                hovertemplate='%{x}<br>%{text}<extra></extra>',name='First detection')
        fig.update_layout(height=430,xaxis_title='UTC bin end',yaxis_title='Outcome-1 equivalent price',
            yaxis={'range':[0,1],'tickformat':'.0%'},margin={'t':30},legend={'orientation':'h'})
        div_id=f'price-{i}'
        pieces.append(fig.to_html(full_html=False,include_plotlyjs=include_js,div_id=div_id));include_js=False
        pieces.append(f'''<script>document.getElementById('{div_id}').on('plotly_click',function(e){{var id=e.points[0].customdata;if(id){{var t=document.getElementById('episode-'+id);if(t){{t.open=true;t.scrollIntoView({{behavior:'smooth'}});}}}}}});</script>''')
        pieces.append('<h3>Movement review</h3>')
        if not events:
            pieces.append('<p>No episode passed the thresholds. Check coverage and warm-up; do not force an attribution.</p>')
        for event in sorted(events,key=lambda e:e['detected_at']):
            candidates=[l for l in links if l['episode_id']==event['episode_id']]
            jobs=[s for s in status if s.get('episode_id')==event['episode_id']]
            coverage=', '.join(sorted({s['status'] for s in jobs})) or 'not searched / not selected'
            pieces.append(f'<details class="card" id="episode-{esc(event["episode_id"])}"><summary>{esc(event["detected_at"])} · {event["initial_displacement_pp"]:+.2f} pp · {esc(event["kind"])} · {len(candidates)} candidates</summary><p>Coarse window: {esc(event["window_start"])} to {esc(event["window_end"])}.<br>Peak rolling variation: {event["peak_rv_pp"]:.2f} pp. Search: {esc(coverage)}.</p>')
            if not candidates:
                pieces.append('<p>No matching candidate recovered. This does not prove no information existed.</p>')
            for link in candidates[:10]:
                url=canonical_url(link['url'])
                pieces.append(f'<div class="card"><a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(link["title"])}</a><p class="snippet">{esc(link["snippet"])}</p><small>Claimed publication: {esc(link["published_at_claimed"])}<br>Role: {esc(link["temporal_role"])} · audited text/time: {link["timestamp_verified"]} · review: {esc(link["review_label"])}<br>Document: {esc(link["document_id"])}</small></div>')
            pieces.append('</details>')
        pieces.append('<details><summary>Activity and volatility diagnostics</summary>')
        volume=go.Figure(go.Bar(x=group.bin_end,y=group.recorded_notional_usd,name='Recorded USDC notional'))
        volume.update_layout(height=300,xaxis_title='UTC bin end',yaxis_title='Recorded notional (USD)',margin={'t':30})
        pieces.append(volume.to_html(full_html=False,include_plotlyjs=False,div_id=f'notional-{i}'))
        rv=go.Figure()
        rv.add_scatter(x=group.bin_end,y=group.rv_pp,name='Rolling variation (pp)',connectgaps=False)
        rv.add_scatter(x=group.bin_end,y=group.displacement_pp.abs(),name='Absolute net movement (pp)',connectgaps=False)
        rv.update_layout(height=300,xaxis_title='UTC bin end',yaxis_title='Percentage points',margin={'t':30},legend={'orientation':'h'})
        pieces.append(rv.to_html(full_html=False,include_plotlyjs=False,div_id=f'volatility-{i}'))
        pieces.append('</details>')
    pieces.append('<h2>Interpretation</h2><p>Lexical relevance and timing only: not semantic entailment, novelty or causal identification. Individual exposure and original order-submission times are not observed. Resolution is not used in the detector or matcher. Strict D-C and unverified research candidates are exported separately.</p></body></html>')
    output.write_text('\n'.join(pieces),encoding='utf-8')
