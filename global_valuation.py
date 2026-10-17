"""Source-fed global-equity context; never substitute illustrative observations."""
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.request import Request, urlopen
import html
import json
import math
import statistics

ETF_URL='https://www.ishares.com/us/products/239600/ishares-msci-acwi-etf'
WB_URL='https://api.worldbank.org/v2/country/WLD/indicator/CM.MKT.LCAP.GD.ZS?format=json&per_page=100'
WB_PAGE='https://data.worldbank.org/indicator/CM.MKT.LCAP.GD.ZS?locations=1W'

class Fundamentals(HTMLParser):
    def __init__(self):
        super().__init__(); self.points=None
    def handle_starttag(self,tag,attrs):
        for name,value in attrs:
            if name=='componentprops' and value and 'fundamentalsAndRisk' in value:
                try:
                    obj=json.loads(value.replace('\\"','"'))
                    if obj.get('componentId')=='fundamentalsAndRisk':self.points=obj['dataPoints']
                except (ValueError,KeyError):pass

def parse_etf(raw):
    parser=Fundamentals();parser.feed(raw)
    if not parser.points:raise ValueError('Missing fundamentals')
    result={}
    for key,name in [('pe','priceEarnings'),('pb','priceBook')]:
        point=parser.points[name];value=float(point['formattedValue'].replace(',',''))
        date=datetime.strptime(point['formattedAsOfDate'],'%b %d, %Y').date()
        if not math.isfinite(value) or value<=0 or date>datetime.now(timezone.utc).date():raise ValueError('Invalid observation')
        result[key]=dict(value=value,period=date.isoformat())
    return result

def parse_world(raw):
    meta,rows=json.loads(raw)
    if int(meta['pages'])!=1:raise ValueError('Incomplete World Bank response')
    points={}
    for r in rows:
        if r.get('countryiso3code')!='WLD' or r.get('indicator',{}).get('id')!='CM.MKT.LCAP.GD.ZS':raise ValueError('Wrong series')
        if r['value'] is None:continue
        year=int(r['date']);value=float(r['value'])
        if not math.isfinite(value) or value<=0 or year>=datetime.now(timezone.utc).year:raise ValueError('Invalid annual observation')
        if year in points and points[year]!=value:raise ValueError('Conflicting annual observations')
        points[year]=value
    if not points:raise ValueError('No observations')
    latest=max(points); history=[dict(year=y,value=points[y]) for y in sorted(points) if y>=latest-29]
    return history

def fetch(offline=False):
    result=dict(attempted_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),etf=dict(status='unavailable',source=ETF_URL),buffett=dict(status='unavailable',source=WB_PAGE),cape=dict(status='unavailable'))
    if offline:
        for key in ('etf','buffett'):result[key]['reason']='Offline build; sources were not requested.'
        return result
    for key,url,parser in [('etf',ETF_URL,parse_etf),('buffett',WB_URL,parse_world)]:
        try:
            with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0 (ImagingDashboard source collector)'}),timeout=25) as response:raw=response.read().decode()
            values=parser(raw)
            result[key].update(status='available',retrieved_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
            if key=='etf':result[key].update(values)
            else:
                result[key]['history']=values
                prior=[r['value'] for r in values[:-1]];latest=values[-1]['value']
                if len(prior)>=10:
                    result[key].update(percentile=100*(sum(v<latest for v in prior)+.5*sum(v==latest for v in prior))/len(prior),median=statistics.median(prior),comparison_count=len(prior))
        except Exception as exc:
            result[key].update(reason='Source retrieval or validation failed ('+type(exc).__name__+').')
    return result

def esc(value):return html.escape(str(value),quote=True)

def mini_chart(points,unit):
    lo=0;hi=max(v for _,v in points)*1.15
    def y(v):return 96-v/hi*76
    def x(i):return 42+(i/(len(points)-1)*236 if len(points)>1 else 118)
    out=['<svg viewBox="0 0 300 125" role="img" aria-label="'+esc('; '.join(f'{label}: {value:.2f} {unit}' for label,value in points))+'">']
    for v in (0,hi/2,hi):out.append(f'<line x1="42" x2="278" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#314355"/><text x="36" y="{y(v)+3:.1f}" text-anchor="end" fill="#afc2d3" font-size="9">{v:.1f}</text>')
    if len(points)>1:out.append('<polyline fill="none" stroke="#77ceef" stroke-width="2" points="'+' '.join(f'{x(i):.1f},{y(v):.1f}' for i,(_,v) in enumerate(points))+'"/>')
    for i,(label,v) in enumerate(points):
        out.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.8" fill="#77ceef"><title>{esc(label)}: {v:.2f}</title></circle>')
        if i in (0,len(points)-1):out.append(f'<text x="{x(i):.1f}" y="115" text-anchor="middle" fill="#afc2d3" font-size="9">{esc(label)}</text>')
    return ''.join(out)+'</svg>'

def render(data):
    b=data.get('buffett',{});e=data.get('etf',{});history=b.get('history',[]);rank=b.get('percentile')
    if rank is not None:
        label='Elevated relative to history' if rank>=80 else 'Low relative to history' if rank<=20 else 'Within the historical range'
        latest=history[-1]
        summary=f"The world Buffett Indicator is {latest['value']:.1f}% in {latest['year']}, compared with a median of {b['median']:.1f}% across {b['comparison_count']} earlier available annual observations. It ranks at the {rank:.0f}th historical percentile."
        conclusion='This points to an expensive market on this measure, but does not establish overvaluation on an intrinsic-value basis.' if rank>=80 else 'This points to a comparatively cheap market on this measure, but does not establish undervaluation on an intrinsic-value basis.' if rank<=20 else 'This measure alone does not give a strong undervalued or overvalued signal.'
        arc=math.pi*55
        meter=f'<svg viewBox="0 0 160 110" role="img" aria-label="World Buffett Indicator historical percentile {rank:.0f}"><path d="M25 75 A55 55 0 0 1 135 75" fill="none" stroke="#304451" stroke-width="10"/><path d="M25 75 A55 55 0 0 1 135 75" fill="none" stroke="#e6ba75" stroke-width="10" stroke-dasharray="{arc*rank/100:.1f} {arc:.1f}"/><text x="80" y="68" text-anchor="middle" fill="#f1dfbd" font-size="25">{rank:.0f}</text><text x="80" y="94" text-anchor="middle" fill="#bfcfdb" font-size="10">Historical percentile</text></svg>'
    else:
        label='Assessment unavailable';summary='A sufficiently complete world market-capitalisation/GDP history is not available for this refresh.';conclusion='No global undervalued or overvalued classification has been substituted.';meter='<p class="metric">—</p>'
    output=[f'<div class="ftse-summary"><div><h3>Is the global stock market undervalued or overvalued?</h3><p class="explain">{summary} {conclusion}</p><article class="ftse-view" style="margin-top:14px"><h4>Bear or Austrian School view</h4><p class="explain">This perspective questions whether easy credit and low interest rates have inflated asset prices or encouraged investment that cannot sustain itself. Assess leverage, refinancing exposure and purchasing power alongside earnings multiples. It is an interpretive framework, not a separate measured valuation score.</p></article></div><aside class="ftse-meter"><h3>Global valuation</h3>{meter}<p class="meta">{label}</p><p class="muted-note">World Buffett Indicator · annual observations. A relative-history signal, not a probability or composite fair-value score.</p></aside></div><h3>Global stock-market indicators</h3><p class="meta">Automatically collected on each dashboard refresh. Observation dates differ; annual data are not real-time quotes.</p><div class="ftse-group"><h3>1 · Earnings and asset valuation</h3><div class="mini-charts">']
    for key,title,caption in [('pe','Global-equity P/E','Price paid for earnings helps assess valuation. ACWI fund proxy; the provider excludes negative earnings from the ratio.'),('pb','Global-equity price-to-book','Price relative to book equity provides an asset-value cross-check. The provider excludes negative book values; intangible assets limit comparability.')]:
        content='<p class="meta">Unavailable — '+esc(e.get('reason','No validated observation.'))+'</p>'
        if e.get('status')=='available':
            point=e[key];content=f'<p class="metric">{point["value"]:.2f}×</p>'+mini_chart([(point['period'],point['value'])],'times')+f'<p class="meta">Observation {point["period"]} · latest point only</p>'
        output.append(f'<figure class="mini-figure"><h4>{title}</h4>{content}<figcaption>{caption}</figcaption></figure>')
    output.append('</div><p class="meta">Source: <a href="'+ETF_URL+'">iShares MSCI ACWI ETF fundamentals</a> · developed and emerging-market large/mid-cap equities; a fund proxy, not every listed company. '+('Retrieved '+esc(e['retrieved_at']) if e.get('retrieved_at') else 'Retrieval unavailable.')+'</p></div>')
    content='<p class="meta">Unavailable — '+esc(b.get('reason','No validated observation.'))+'</p>'
    if history:
        latest=history[-1];content=f'<p class="metric">{latest["value"]:.1f}% <span class="meta">· {latest["year"]}</span></p>'+mini_chart([(str(r['year']),r['value']) for r in history],'% of GDP')
    output.append('<div class="ftse-group"><h3>2 · Broad market valuation</h3><div class="mini-charts"><figure class="mini-figure"><h4>Buffett Indicator — world market cap / GDP</h4>'+content+'<figcaption>Listed domestic equity value relative to GDP. A high ratio can flag expensive markets, but changes in listed-company coverage and profits also matter.</figcaption></figure><article class="mini-figure"><h4>Global CAPE</h4><p class="meta">Not available from a verified automated source.</p><p class="explain">CAPE compares price with inflation-adjusted earnings over a long window. A global series needs consistent country coverage and methodology; UK-only illustrations cannot fill this gap.</p></article></div><p class="meta">Source: <a href="'+WB_PAGE+'">World Bank / World Federation of Exchanges</a> · annual world aggregate. '+('Retrieved '+esc(b['retrieved_at']) if b.get('retrieved_at') else 'Retrieval unavailable.')+'</p></div>')
    output.append('<details><summary>Valuation methodology and source status</summary><p class="meta">The meter ranks the latest available annual world market-cap/GDP ratio against earlier available observations in a trailing thirty-calendar-year window, excluding the latest year. At least ten earlier observations are required. Percentile = (lower values + half of equal values) / comparison count × 100. The descriptive bands (low at or below twenty; elevated at or above eighty) are editorial conventions, not validated fair-value thresholds. Missing years are not interpolated. P/E and P/B are supporting context and do not contribute to the meter. No fabricated historical P/E or P/B lines are shown.</p><p class="meta">Collection attempted '+esc(data.get('attempted_at','unknown'))+' · ACWI: '+esc(e.get('status','unavailable'))+' · Buffett Indicator: '+esc(b.get('status','unavailable'))+' · global CAPE: unavailable.</p>')
    if history:output.append('<div class="table-wrap"><table><caption>World market capitalisation / GDP</caption><thead><tr><th>Year</th><th>Ratio (%)</th></tr></thead><tbody>'+''.join(f'<tr><td>{r["year"]}</td><td>{r["value"]:.2f}</td></tr>' for r in reversed(history))+'</tbody></table></div>')
    return ''.join(output)+'</details>'
