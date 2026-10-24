"""Source-fed global-equity context; never substitute illustrative observations."""
from datetime import datetime, timezone, date
from html.parser import HTMLParser
from urllib.request import Request, urlopen
import html
import json
import math
import statistics
import logging
from pathlib import Path

ETF_URL='https://www.ishares.com/us/products/239600/ishares-msci-acwi-etf'
WB_URL='https://api.worldbank.org/v2/country/WLD/indicator/CM.MKT.LCAP.GD.ZS?format=json&per_page=100'
WB_PAGE='https://data.worldbank.org/indicator/CM.MKT.LCAP.GD.ZS?locations=1W'
HISTORY_PATH=Path(__file__).with_name('valuation-history.json')
HISTORY_SOURCE='iShares MSCI ACWI ETF fundamentals'

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


def validate_history(raw):
    """Accept only dated, sourced observations of this same ETF and methodology."""
    if not isinstance(raw, dict) or raw.get('source') != HISTORY_SOURCE:
        raise ValueError('Wrong valuation history source')
    readings = raw.get('observations')
    if not isinstance(readings, dict) or set(readings) != {'pe', 'pb'}:
        raise ValueError('Incorrect valuation history series')
    result = {}
    for key in ('pe', 'pb'):
        rows = readings[key]
        if not isinstance(rows, list) or len(rows) > 520:
            raise ValueError('Invalid valuation history size')
        parsed = []
        for p in rows:
            if not isinstance(p, dict) or set(p) != {'period', 'value'}:
                raise ValueError('Invalid history observation fields')
            period, value = p['period'], p['value']
            try:
                observed = date.fromisoformat(period)
            except (ValueError, TypeError):
                raise ValueError('Invalid history observation date') from None
            if observed > datetime.now(timezone.utc).date() or not isinstance(value, (int, float)) \
               or isinstance(value, bool) or not math.isfinite(value) or not 0 < value < 1000:
                raise ValueError('Invalid valuation observation')
            parsed.append(dict(period=observed.isoformat(), value=float(value)))
        if [p['period'] for p in parsed] != sorted(set(p['period'] for p in parsed)):
            raise ValueError('Valuation history dates must be unique and increasing')
        result[key] = parsed
    return result


def read_history(path=HISTORY_PATH):
    """Do not claim historical trends when no genuine dated observations are stored."""
    try:
        return validate_history(json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError) as exc:
        logging.warning('Validated ETF valuation history unavailable (%s)', type(exc).__name__)
        return {'pe': [], 'pb': []}


def merge_history(existing, latest):
    """Append new source dates; replace corrections with the same observation date."""
    combined = {}
    for key in ('pe', 'pb'):
        points = {p['period']: p['value'] for p in existing.get(key, [])}
        if key in latest:
            point = latest[key]
            date.fromisoformat(point['period'])
            value = float(point['value'])
            if not math.isfinite(value) or not 0 < value < 1000:
                raise ValueError('Invalid latest valuation')
            points[point['period']] = value
        combined[key] = [{'period': day, 'value': points[day]}
                         for day in sorted(points)][-260:]
    return combined


def write_history(path, observations):
    """Called by a permitted scheduled job; no source data are reconstructed."""
    clean = validate_history({'source': HISTORY_SOURCE, 'observations': observations})
    output = json.dumps({'source': HISTORY_SOURCE, 'observations': clean}, indent=2) + '\n'
    Path(path).write_text(output, encoding='utf-8')


def valuation_trend(points, ratio):
    """Plot only three or more genuine time-spaced observations, with real dates."""
    if len(points) < 3:
        return ''
    from datetime import timedelta
    first = date.fromisoformat(points[0]['period']).toordinal()
    last = date.fromisoformat(points[-1]['period']).toordinal()
    if last <= first:
        return ''
    lows = [p['value'] for p in points]
    low = min(lows); high = max(lows)
    padding = max((high-low)*.15, high*.025)
    low = max(0, low-padding); high += padding
    def x(day): return 48+(date.fromisoformat(day).toordinal()-first)/(last-first)*245
    def y(value): return 101-(value-low)/(high-low)*75
    out = [f'<svg viewBox="0 0 315 143" role="img" aria-label="{esc(ratio)}: verified source observations from {esc(points[0]["period"])} through {esc(points[-1]["period"])}. Source samples are not continuous daily readings.">']
    for value in (low,(low+high)/2,high):
        pos=y(value)
        out.append(f'<line x1="48" x2="293" y1="{pos:.1f}" y2="{pos:.1f}" stroke="#304451"/><text x="42" y="{pos+4:.1f}" font-size="9" text-anchor="end" fill="#bcd3e0">{value:.1f}</text>')
    # Treat gaps longer than roughly two months as discontinuities.
    for previous,current in zip(points,points[1:]):
        a=date.fromisoformat(previous['period']);b=date.fromisoformat(current['period'])
        if (b-a).days<=65:
            out.append(f'<line x1="{x(previous["period"]):.1f}" y1="{y(previous["value"]):.1f}" x2="{x(current["period"]):.1f}" y2="{y(current["value"]):.1f}" stroke="#80d2f1" stroke-width="2.4"/>')
    for point in points:
        cx=x(point['period']);cy=y(point['value'])
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="#80d2f1"><title>{esc(point["period"])}: {point["value"]:.2f}×</title></circle>')
    out.append(f'<text x="48" y="132" font-size="10" fill="#c7d9e6">{esc(points[0]["period"][:7])}</text>')
    out.append(f'<text x="293" y="132" text-anchor="end" font-size="10" fill="#c7d9e6">{esc(points[-1]["period"][:7])}</text>')
    return ''.join(out)+'</svg>'


def fetch(offline=False):
    result=dict(attempted_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),etf=dict(status='unavailable',source=ETF_URL),buffett=dict(status='unavailable',source=WB_PAGE))
    result['etf']['history']=read_history()
    if offline:
        for key in ('etf','buffett'):result[key]['reason']='Offline build; sources were not requested.'
        return result
    for key,url,parser in [('etf',ETF_URL,parse_etf),('buffett',WB_URL,parse_world)]:
        try:
            with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0 (ImagingDashboard source collector)'}),timeout=25) as response:raw=response.read().decode()
            values=parser(raw)
            result[key].update(status='available',retrieved_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
            if key=='etf':
                result[key].update(values)
                result[key]['history']=merge_history(result[key]['history'],values)
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


def buffett_gauge(value, median, year):
    """The dial shows market capitalisation as % of GDP, not historical percentile."""
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
           for v in (value, median)):
        raise ValueError('Invalid Buffett Indicator gauge input')
    maximum = max(200, math.ceil(max(value, median) / 50) * 50)
    progress = min(100, value / maximum * 100)
    angle = math.pi * (1 - min(1, median / maximum))
    median_x = 90 + 58 * math.cos(angle)
    median_y = 92 - 58 * math.sin(angle)
    return (
        f'<svg viewBox="0 0 180 133" role="img" '
        f'aria-label="World stock-market value in {int(year)}: {value:.1f}% of GDP; '
        f'scale 0 to {maximum}% of GDP, historical median {median:.1f}%">'
        f'<title>World stock-market value relative to GDP</title>'
        f'<path d="M32 92 A58 58 0 0 1 148 92" fill="none" stroke="#304451" stroke-width="10"/>'
        f'<path d="M32 92 A58 58 0 0 1 148 92" fill="none" stroke="#73c9ef" '
        f'stroke-width="10" pathLength="100" stroke-dasharray="{progress:.2f} 100"/>'
        f'<circle cx="{median_x:.2f}" cy="{median_y:.2f}" r="5" '
        f'fill="#f4c981" stroke="#101c2b" stroke-width="1.5">'
        f'<title>Historical median {median:.1f}% of GDP</title></circle>'
        f'<text x="20" y="113" fill="#c6dbe9" font-size="11">0</text>'
        f'<text x="90" y="22" text-anchor="middle" fill="#c6dbe9" font-size="10">{maximum/2:g}</text>'
        f'<text x="160" y="113" text-anchor="end" fill="#c6dbe9" font-size="11">{maximum:g}</text>'
        f'<text x="90" y="77" text-anchor="middle" fill="#f3f8ff" font-size="23" '
        f'font-weight="700">{value:.1f}%</text>'
        f'<text x="90" y="95" text-anchor="middle" fill="#c6dbe9" font-size="10">of world GDP</text>'
        f'</svg>'
    )

def render(data):
    b=data.get('buffett',{});e=data.get('etf',{});history=b.get('history',[]);rank=b.get('percentile')
    if rank is not None:
        label='Elevated relative to history' if rank>=80 else 'Low relative to history' if rank<=20 else 'Within the historical range'
        latest=history[-1]
        summary=f"The world stock-market value-to-GDP ratio is {latest['value']:.1f}% in {latest['year']}, compared with a typical past level of {b['median']:.1f}% across {b['comparison_count']} earlier years of data. It is at the {rank:.0f}th percentile of the available history."
        conclusion='This makes shares look expensive compared with the past, but does not prove they are overpriced.' if rank>=80 else 'This makes shares look cheaper compared with the past, but does not prove they are underpriced.' if rank<=20 else 'On its own, this measure does not show clearly whether shares look cheap or expensive.'
        meter=buffett_gauge(latest['value'], b['median'], latest['year'])
    else:
        label='Assessment unavailable';summary='A sufficiently complete world market-capitalisation/GDP history is not available for this refresh.';conclusion='No global undervalued or overvalued classification has been substituted.';meter='<p class="metric">—</p>'
    gauge_note=(f'Blue arc: market value as % of world GDP. Gold dot: historical median {b["median"]:.1f}% of GDP. The scale normally runs from 0 to 200% of GDP, extending if necessary. The {rank:.0f}th historical percentile is a separate ranking, not a percentage of overvaluation.' if rank is not None else 'The dial measures market value as a share of GDP, not a ranking. No dial appears without reliable data.')
    output=[f'<div class="ftse-summary"><div><h3>Do world share prices look high or low?</h3><p class="explain">{summary} {conclusion}</p><article class="ftse-view" style="margin-top:14px"><h4>A cautious view of financial markets (Austrian School)</h4><p class="explain">This viewpoint asks whether cheap borrowing has pushed share prices too high or encouraged projects that may struggle when interest rates rise. For imaging businesses, check debt, the cost of renewing loans and the buying power of budgets. This is a perspective, not a separate score.</p></article></div><aside class="ftse-meter"><h3>World Buffett Indicator · % of GDP</h3>{meter}<p class="meta">{label}</p><p class="muted-note">{gauge_note}</p></aside></div><h3>Global share-market indicators</h3><p class="meta">Checked when the dashboard refreshes. Each figure keeps its own observation date. Annual figures are not live market prices.</p><div class="ftse-group"><h3>1 · Share prices compared with profits and assets</h3><div class="mini-charts">']
    for key,title,caption in [('pe','Global-equity P/E','Share prices compared with company profits in a broad global fund. Loss-making companies are excluded from this ratio.'),('pb','Global-equity price-to-book','Share prices compared with the value of company assets on their balance sheets. Research and software are not always fully reflected in these values.')]:
        content='<p class="meta">Latest reading unavailable — '+esc(e.get('reason','No validated observation.'))+'</p>'
        points=e.get('history',{}).get(key,[])
        if e.get('status')=='available':
            point=e[key]
            content=f'<p class="metric">{point["value"]:.2f}×</p><p class="meta">As published {esc(point["period"])} · refreshed from iShares when the dashboard is rebuilt</p>'
        trend=valuation_trend(points, title) if points else ''
        if trend:
            content+=trend+'<p class="meta">Verified source-date observations collected by this dashboard; missing weeks are not filled.</p>'
        else:
            content+='<p class="meta">Historical trend not yet available. iShares provides a latest dated ratio, not a downloadable multi-year series. This dashboard is collecting real source-date observations at each refresh; a chart will appear once at least three distinct dates are verified.</p>'
        output.append(f'<figure class="mini-figure"><h4>{title}</h4>{content}<figcaption>{caption}</figcaption></figure>')
    output.append('</div><p class="meta">Source: <a href="'+ETF_URL+'">iShares MSCI ACWI ETF fundamentals</a> · developed and emerging-market large/mid-cap equities; a fund proxy, not every listed company. '+('Retrieved '+esc(e['retrieved_at']) if e.get('retrieved_at') else 'Retrieval unavailable.')+'</p></div>')
    content='<p class="meta">Unavailable — '+esc(b.get('reason','No validated observation.'))+'</p>'
    if history:
        latest=history[-1];content=f'<p class="metric">{latest["value"]:.1f}% <span class="meta">· {latest["year"]}</span></p>'+mini_chart([(str(r['year']),r['value']) for r in history],'% of GDP')
    output.append('<div class="ftse-group"><h3>2 · Share prices compared with the world economy</h3><div class="mini-charts single"><figure class="mini-figure"><h4>Buffett Indicator — world market cap / GDP</h4>'+content+'<figcaption>The total value of listed companies compared with world economic output. High readings may suggest expensive shares, but company coverage and profits also matter.</figcaption></figure></div><p class="meta">Source: <a href="'+WB_PAGE+'">World Bank / World Federation of Exchanges</a> · annual world aggregate. '+('Retrieved '+esc(b['retrieved_at']) if b.get('retrieved_at') else 'Retrieval unavailable.')+'</p></div>')
    output.append('<details><summary>Valuation methodology and source status</summary><p class="meta">The meter ranks the latest available annual world market-cap/GDP ratio against earlier available observations in a trailing thirty-calendar-year window, excluding the latest year. At least ten earlier observations are required. Percentile = (lower values + half of equal values) / comparison count × 100. The descriptive bands (low at or below twenty; elevated at or above eighty) are editorial conventions, not validated fair-value thresholds. Missing years are not interpolated. P/E and P/B are supporting context and do not contribute to the meter. ETF history consists only of archived, dated source observations; older values are not inferred from market prices.</p><p class="meta">Collection attempted '+esc(data.get('attempted_at','unknown'))+' · ACWI: '+esc(e.get('status','unavailable'))+' · Buffett Indicator: '+esc(b.get('status','unavailable'))+'</p>')
    if history:output.append('<div class="table-wrap"><table><caption>World market capitalisation / GDP</caption><thead><tr><th>Year</th><th>Ratio (%)</th></tr></thead><tbody>'+''.join(f'<tr><td>{r["year"]}</td><td>{r["value"]:.2f}</td></tr>' for r in reversed(history))+'</tbody></table></div>')
    return ''.join(output)+'</details>'
