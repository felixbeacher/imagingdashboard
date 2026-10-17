"""Compact, explicitly illustrative FTSE figures from the user-supplied source."""
import html
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
METRICS = {
    'pe': ('Trailing P/E', '× earnings', 'Price paid for recent earnings helps frame supplier or acquisition valuations; cyclical profits can make a low P/E misleading.'),
    'cape': ('CAPE / Shiller P/E', '× smoothed earnings', 'Smoothed earnings add a longer-term valuation perspective; a broad index is only indirect context for imaging businesses.'),
    'pb': ('Price-to-book', '× book equity', 'Book equity offers an asset-value cross-check for equipment businesses, but captures software and internally developed IP poorly.'),
    'buffett': ('Market capitalisation / GDP', '% of GDP', 'A broad market-size cross-check with limited imaging relevance: international company revenues and domestic GDP cover different economies.')
}


def chart(key, values, labels):
    title, unit, relevance = METRICS[key]
    lo, hi = min(values), max(values)
    pad = max((hi-lo)*.25, .1)
    lo, hi = max(0,lo-pad), hi+pad
    def y(value): return 116-(value-lo)/(hi-lo)*88
    def x(i): return 48+i*288/(len(values)-1)
    points=' '.join(f'{x(i):.1f},{y(v):.1f}' for i,v in enumerate(values))
    svg=[f'<svg viewBox="0 0 360 150" role="img" aria-labelledby="ftse-{key}-title ftse-{key}-desc"><title id="ftse-{key}-title">{title}: supplied illustrative series</title><desc id="ftse-{key}-desc">'+html.escape('; '.join(f'{l}: {v:g} {unit}' for l,v in zip(labels,values)))+'. Not verified market observations.</desc>']
    for value in (lo,(lo+hi)/2,hi):
        svg.append(f'<line x1="48" x2="336" y1="{y(value):.1f}" y2="{y(value):.1f}" stroke="#314355"/><text x="41" y="{y(value)+4:.1f}" text-anchor="end" fill="#afc2d3" font-size="10">{value:.2f}</text>')
    svg.append(f'<polyline points="{points}" fill="none" stroke="#77ceef" stroke-width="2.4"/>')
    for i,(label,value) in enumerate(zip(labels,values)):
        svg.append(f'<circle cx="{x(i):.1f}" cy="{y(value):.1f}" r="3" fill="#77ceef"><title>{html.escape(label)}: {value:g}</title></circle><text x="{x(i):.1f}" y="137" text-anchor="middle" fill="#afc2d3" font-size="10">{html.escape(label)}</text>')
    svg.append('</svg>')
    return f'<figure class="mini-figure"><h4>{title}</h4><p class="reference-label">Source illustration · {unit} · not live</p>'+''.join(svg)+f'<figcaption>{relevance}</figcaption></figure>'


def render_reference():
    data=json.loads((ROOT/'ftse-reference.json').read_text())
    if data['status']!='illustrative_unverified':
        raise ValueError('FTSE source status must be explicit')
    labels=data['labels']
    for key in METRICS:
        values=data['series'][key]
        if len(labels)<2 or len(values)!=len(labels) or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
            raise ValueError('Invalid FTSE reference series')
    score=data['standard_score']
    if not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=100:
        raise ValueError('Invalid illustrative score')
    # Arc fill reproduces the supplied score; it does not calculate a valuation.
    arc=math.pi*65
    meter=f'''<aside class="ftse-meter"><h3>Standard Score</h3><span class="reference-label">Source illustration · not live</span><svg viewBox="0 0 180 130" role="img" aria-label="Illustrative source score {score:g} out of 100, labelled Undervalued; method unverified"><path d="M25 85 A65 65 0 0 1 155 85" fill="none" stroke="#304451" stroke-width="12" stroke-linecap="round"/><path d="M25 85 A65 65 0 0 1 155 85" fill="none" stroke="#82d7b0" stroke-width="12" stroke-linecap="round" stroke-dasharray="{arc*score/100:.2f} {arc:.2f}"/><text x="90" y="76" fill="#d6f4e5" text-anchor="middle" font-size="29" font-weight="700">{score:g}</text><text x="90" y="98" text-anchor="middle" fill="#bfe7d3" font-size="12">Undervalued</text><text x="25" y="111" fill="#afc2d3" font-size="10">0</text><text x="155" y="111" text-anchor="end" fill="#afc2d3" font-size="10">100</text></svg><p class="muted-note">Original page’s label and fixed score. No reproducible weights or thresholds were supplied.</p></aside>'''
    output=['''<div class="ftse-source-notice"><strong>About these FTSE figures.</strong> Reproduced from the supplied page’s fixed 2022–2026 series. Values and the “Undervalued” classification are illustrative and unverified, not refreshed market data or a current investment conclusion.</div><div class="ftse-summary"><div><h3>Dual-Analytical Summary</h3><div class="ftse-dual"><article class="ftse-view"><h4>Institutional View</h4><p class="explain">Compare earnings and asset multiples with consistent historical and peer benchmarks. Lower multiples can support a value case if earnings, cash flow and balance sheets are resilient. The supplied charts alone do not establish a current discount.</p></article><article class="ftse-view"><h4>Resilience counterpoint</h4><p class="explain">Check whether inflation, debt costs or weak cash conversion undermine apparently cheap valuations. For imaging, test supplier stability, service commitments and provider budgets before interpreting a market-level signal.</p></article></div></div>'''+meter+'</div><h3>Standard Mainstream Metrics</h3><p class="explain">Groups are ordered by their usefulness for imaging-sector investment analysis. All four charts use the same supplied five-year window; vertical scales differ.</p>']
    groups=[('1 · Earnings valuation','Most directly transferable to evaluating profitable imaging suppliers and acquisitions.',['pe','cape']),('2 · Asset backing','A supplementary check for equipment businesses; less informative for software-led companies.',['pb']),('3 · Broad market context','Indirect context, with the weakest link to imaging procurement or demand.',['buffett'])]
    for index,(name,desc,keys) in enumerate(groups):
        if index == 1:
            output.append('<div class="ftse-secondary">')
        output.append(f'<div class="ftse-group"><h3>{name}</h3><p class="meta">{desc}</p><div class="mini-charts'+(' single' if len(keys)==1 else '')+'">')
        output.extend(chart(k,data['series'][k],labels) for k in keys)
        output.append('</div></div>')
    output.append('</div>')
    output.append('<details><summary>Source figures and provenance</summary><p class="meta">Imported 17 October 2026 from '+html.escape(data['source_file'])+'. The source labels its market-capitalisation numerator “FTSE Total Market Cap”; its precise coverage is not documented. No US comparisons, historical averages or fair-value thresholds have been carried over as verified facts.</p><div class="table-wrap"><table><caption>Exact illustrative values plotted above</caption><thead><tr><th>Year</th>'+''.join('<th>'+METRICS[k][0]+'</th>' for k in METRICS)+'</tr></thead><tbody>')
    for i,label in enumerate(labels):
        output.append('<tr><th scope="row">'+html.escape(label)+'</th>'+''.join(f'<td>{data["series"][k][i]:g}</td>' for k in METRICS)+'</tr>')
    output.append('</tbody></table></div><p class="meta">Static reference data are kept separate from collected economic observations and Gemini inputs.</p></details>')
    return ''.join(output)
