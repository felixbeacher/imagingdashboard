#!/usr/bin/env python3
"""Populate Felix Beacher's supplied ai.html with traceable public data.

Python 3.10+; standard library only. No API key or generative model required.

    python ai_update_data.py
    python ai_update_data.py --template ai.html --output ai.generated.html
    python ai_update_data.py --offline
    python ai_update_data.py --template ai.template.html --output ai.html

Default: read ai.html beside this script, write ai.generated.html beside it.
Keep the original template. To publish as ai.html, use a separate template file.
If input and output coincide, the first run creates ai.template.html and later
runs reuse it. Existing template backups are never overwritten automatically.
Place styles.css next to the output for the original theme. A fallback theme is
embedded when that stylesheet is absent. Chart.js requires an internet connection.

Coverage: FDA's periodically updated, non-exhaustive AI list (US authorisations),
Federal Reserve target-range upper bound and BLS medical CPI via FRED (US), ECB
deposit facility rate (euro area), and filtered industry RSS news. Other metrics
remain explicitly unavailable. US and euro-area data are labelled subsets or
benchmarks, never regional totals. No modality/revenue shares are inferred.

Rates use each month's last available observation, not a monthly average. CPI
YoY uses the same month one year earlier. FDA counts deduplicate submission IDs;
LLZ counts are AI-listed radiology 510(k) submissions with primary code LLZ,
not all LLZ devices or all AI clearances. The annual chart includes all listed
radiology marketing-authorisation pathways. Current-year/list-lag limitations
are displayed. News geography is a conservative title/summary keyword filter,
not proof of market authorisation or comprehensive regional coverage.

Source failures use previously validated responses only, retain their original
retrieval date and display a cached-data warning. With no cache, unavailable is
shown, never zero. --offline forces this fallback; --fail-on-source-error returns
exit code 2 after writing a usable page if any source was not refreshed.
"""
from __future__ import annotations

import argparse
import calendar
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import html
from html.parser import HTMLParser
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit
import xml.etree.ElementTree as ET

LOG = logging.getLogger('ai_dashboard')
FDA_URL = 'https://www.fda.gov/medical-devices/artificial-intelligence-enabled-medical-devices/list-artificial-intelligence-enabled-medical-devices'
SOURCES = {
    'fda': ('FDA AI-enabled medical device list', FDA_URL, FDA_URL),
    'us_rate': ('Federal Reserve via FRED — target range upper limit',
                'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU',
                'https://fred.stlouisfed.org/series/DFEDTARU'),
    'us_cpi': ('BLS via FRED — medical care CPI, seasonally adjusted',
               'https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIMEDSL',
               'https://fred.stlouisfed.org/series/CPIMEDSL'),
    'ecb': ('ECB — deposit facility rate',
            'https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV?format=csvdata',
            'https://data.ecb.europa.eu/data/datasets/FM/FM.D.U2.EUR.4F.KR.DFR.LEV'),
    'radiology_news': ('Radiology Business', 'https://radiologybusiness.com/rss.xml', 'https://radiologybusiness.com'),
    'auntminnie': ('AuntMinnie', 'https://www.auntminnie.com/rss/rss.aspx', 'https://www.auntminnie.com'),
    'fda_news': ('FDA press releases', 'https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml', 'https://www.fda.gov/news-events/fda-newsroom/press-announcements'),
}
REGIONS = {'global': 'Global', 'northAmerica': 'North America', 'europe': 'Europe',
           'asia': 'Asia', 'middleEast': 'Middle East', 'southAmerica': 'South America'}
REGION_WORDS = {
 'northAmerica': r'\b(united states|u\.s\.|usa|fda|canada|canadian|mexic\w*)\b',
 'europe': r'\b(europe\w*|united kingdom|uk|nhs|brit\w*|german\w*|franc\w*|french|ital\w*|spain|spanish|swed\w*|netherlands|dutch|mhra|ce mark\w*)\b',
 'asia': r'\b(asia\w*|china|chinese|japan\w*|india\w*|korea\w*|singapore|taiwan\w*|indonesia\w*)\b',
 'middleEast': r'\b(middle east|saudi\w*|uae|united arab emirates|dubai|israel\w*|qatar\w*|kuwait\w*|bahrain\w*|oman|jordan\w*)\b',
 'southAmerica': r'\b(south america\w*|brazil\w*|brasil\w*|argentin\w*|chile\w*|chilean|colombia\w*|peru\w*|uruguay\w*|ecuador\w*)\b',
}
AI_RE = re.compile(r'\b(ai|artificial intelligence|machine learning|deep learning|algorithm\w*)\b', re.I)
IMAGING_RE = re.compile(r'\b(radiolog\w*|imaging|mri|ct|ultrasound|mammogra\w*|x[- ]?ray|scan\w*)\b', re.I)


def js_json(value):
    """Safe JSON in an HTML script element, including hostile RSS strings."""
    return json.dumps(value, ensure_ascii=True, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as out:
            out.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
    def handle_data(self, value):
        self.parts.append(value)


def plain(value):
    p = TextParser()
    p.feed(value)
    return ' '.join(' '.join(p.parts).split())


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell = [], [], None
    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row = []
        if tag in ('th', 'td'): self.cell = []
    def handle_data(self, value):
        if self.cell is not None: self.cell.append(value)
    def handle_endtag(self, tag):
        if tag in ('th', 'td') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        if tag == 'tr' and self.row: self.rows.append(self.row)


def parse_fda(raw, today):
    parser = TableParser()
    parser.feed(raw)
    headers = ['Date of Final Decision', 'Submission Number', 'Device', 'Company', 'Panel (Lead)', 'Primary Product Code']
    if headers not in parser.rows:
        raise ValueError('FDA table columns changed or page is not a device list')
    records = {}
    for row in parser.rows[parser.rows.index(headers) + 1:]:
        if len(row) != 6: continue
        try: decision = datetime.strptime(row[0], '%m/%d/%Y').date()
        except ValueError: continue
        submission = row[1].strip().upper()
        if not re.fullmatch(r'(?:K\d{6}|DEN\d{6}|P\d{6}(?:/S\d+)?)', submission):
            raise ValueError('Unexpected FDA submission identifier')
        if decision <= today:
            records[submission] = {'date': decision.isoformat(), 'submission': submission,
                                   'panel': row[4], 'code': row[5]}
    if not records: raise ValueError('FDA list has no usable rows')
    radiology = [r for r in records.values() if r['panel'].casefold() == 'radiology']
    if not radiology: raise ValueError('FDA list has no radiology rows')
    return {'records': radiology, 'latest': max(r['date'] for r in records.values())}


def parse_series(raw, key, today):
    rows = csv.DictReader(io.StringIO(raw.lstrip('\ufeff')))
    cols = ('TIME_PERIOD', 'OBS_VALUE') if key == 'ecb' else ('observation_date', 'DFEDTARU' if key == 'us_rate' else 'CPIMEDSL')
    if not rows.fieldnames or any(c not in rows.fieldnames for c in cols):
        raise ValueError('Time-series CSV schema changed')
    result = {}
    for row in rows:
        try:
            day = date.fromisoformat(row[cols[0]])
            value = float(row[cols[1]])
        except (ValueError, TypeError): continue
        if not math.isfinite(value): continue
        if key == 'us_cpi' and value <= 0: raise ValueError('Invalid CPI value')
        if key != 'us_cpi' and not -20 <= value <= 100: raise ValueError('Invalid policy rate')
        if day <= today: result[day.isoformat()] = value
    if not result: raise ValueError('No valid historical observations')
    return dict(sorted(result.items()))


def safe_url(value):
    try:
        u = urlsplit(value.strip())
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
            return None
        return urlunsplit((u.scheme, u.netloc, u.path, u.query, ''))
    except ValueError: return None


def parse_news(raw, today, days=90):
    if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():
        raise ValueError('Unsupported XML declarations')
    root = ET.fromstring(raw)
    if root.tag.split('}')[-1] not in ('rss', 'feed'):
        raise ValueError('Response is not RSS or Atom')
    items = []
    for item in root.iter():
        if item.tag.split('}')[-1] not in ('item', 'entry'): continue
        fields = {}
        for child in item:
            name = child.tag.split('}')[-1]
            if name == 'link' and child.attrib.get('rel', 'alternate') != 'alternate': continue
            fields[name] = child.attrib.get('href') if name == 'link' and child.attrib.get('href') else ''.join(child.itertext())
        title = plain(fields.get('title', ''))
        summary = plain(fields.get('description', fields.get('summary', fields.get('content', ''))))
        link = safe_url(fields.get('link', ''))
        text = title + ' ' + summary
        if not link or not title or not AI_RE.search(text) or not IMAGING_RE.search(text): continue

        published = fields.get('pubDate', fields.get('published', fields.get('updated', '')))
        try:
            try:
                dt = parsedate_to_datetime(published)
            except (ValueError, TypeError):
                dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
            
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            day = dt.astimezone(timezone.utc).date()
        except (ValueError, TypeError, OverflowError):
            continue

        if not today - timedelta(days=days) <= day <= today: continue
        regions = [k for k, pattern in REGION_WORDS.items() if re.search(pattern, text, re.I)]
        items.append({'title': title[:500], 'url': link, 'date': day.isoformat(), 'regions': regions})
    return items


def parse_source(key, raw, today):
    if key == 'fda': return parse_fda(raw, today)
    if key in ('us_rate', 'us_cpi', 'ecb'): return parse_series(raw, key, today)
    return parse_news(raw, today)


def fetch_source(key, cached, today, timeout=20, offline=False):
    name, endpoint, page = SOURCES[key]
    error = 'Offline mode'
    if not offline:
        for attempt in range(2):
            try:
                request = urllib.request.Request(endpoint, headers={'User-Agent': 'MedicalImagingDashboard/2.0', 'Accept': '*/*'})
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw_bytes = response.read(8_000_001)
                    if len(raw_bytes) > 8_000_000: raise ValueError('Source exceeds 8 MB safety limit')
                    raw = raw_bytes.decode('utf-8-sig')
                data = parse_source(key, raw, today)
                fetched = datetime.now(timezone.utc).isoformat()
                record = {'url': endpoint, 'raw': raw, 'fetched_at': fetched}
                return key, {'name': name, 'url': page, 'status': 'live', 'fetched_at': fetched, 'data': data}, record
            except Exception as exc:
                error = str(exc)
                if attempt == 0: time.sleep(1)
    if isinstance(cached, dict) and cached.get('url') == endpoint:
        try:
            fetched = datetime.fromisoformat(cached['fetched_at'])
            if fetched.tzinfo is None: raise ValueError('Cache timestamp missing timezone')
            data = parse_source(key, cached['raw'], today)
            LOG.warning('%s: using cached response (%s)', key, error)
            return key, {'name': name, 'url': page, 'status': 'cached', 'fetched_at': cached['fetched_at'], 'data': data, 'error': error}, cached
        except (ValueError, TypeError, KeyError): pass
    LOG.warning('%s: unavailable (%s)', key, error)
    return key, {'name': name, 'url': page, 'status': 'unavailable', 'fetched_at': None, 'data': None, 'error': error}, None


def shift_month(day, offset):
    serial = day.year * 12 + day.month - 1 + offset
    year, month = divmod(serial, 12)
    return date(year, month + 1, 1)


def month_series(series, today):
    labels, values = [], []
    for offset in range(-5, 1):
        start = shift_month(today, offset)
        end = min(today, date(start.year, start.month, calendar.monthrange(start.year, start.month)[1]))
        observed = [(d, v) for d, v in series.items() if start.isoformat() <= d <= end.isoformat()]
        labels.append(start.strftime('%b %Y') + (' (to date)' if offset == 0 else ''))
        values.append(max(observed)[1] if observed else None)
    return labels, values


def metric(label, description, value=None, basis='Not available', source=None, observed=None):
    return dict(label=label, description=description, value=value, basis=basis, source=source, observed=observed)


def make_payload(sources, today):
    payload = {'generated_at': datetime.now(timezone.utc).isoformat(), 'regions': {},
               'sources': {k: {p: v for p, v in s.items() if p not in ('data', 'error')} for k, s in sources.items()}}
    news, seen = [], set()
    candidates = []
    for key in ('radiology_news', 'auntminnie', 'fda_news'):
        for item in sources[key]['data'] or []:
            candidates.append(dict(item, source=key))
    for item in sorted(candidates, key=lambda x: x['date'], reverse=True):
        normal_title = re.sub(r'\W+', '', item['title'].casefold())
        if item['url'] in seen or normal_title in seen: continue
        seen.update((item['url'], normal_title))
        news.append(item)
    for key, title in REGIONS.items():
        metrics = [
            metric('Central Bank Policy', 'No single policy rate represents this region. No weighted aggregate has been calculated.'),
            metric('Healthcare Inflation', 'No validated comparable regional healthcare inflation series is configured.'),
            metric('MedTech Index', 'No validated index series is configured. A broad stock-market index is not substituted.'),
            metric('Imaging Demand Backlog', 'No comparable regional imaging waiting-list series is configured. No national figure is presented as a regional total.'),
            metric('Cloud Inference Index', 'No fixed-workload, hardware, location and pricing benchmark is configured.'),
            metric('FDA-listed AI LLZ Clearances', 'US-specific measure; not a clearance count for the selected region.'),
            metric('Radiologist Vacancy Rate', 'No measured regional unfilled-post rate is configured; workforce shortfalls are not substituted.'),
            metric('Reimbursement Adoption', 'No verified hospital billing-utilisation numerator and denominator are configured.'),
            metric('Prospective Clinical Validation', 'No screened literature dataset with prospective-study criteria and a defined regional attribution is configured.'),
        ]
        region = {'name': title, 'metrics': metrics, 'approvals': [], 'years': [], 'rateValues': [], 'months': [],
                  'approvalTitle': 'AI Authorisations & VC Investment — data unavailable',
                  'rateTitle': 'Stock Market Index & Interest Rates — data unavailable',
                  'approvalNote': 'No comparable regional authorisation dataset or verified VC funding series is configured.',
                  'rateNote': 'No comparable regional index and policy-rate pair is configured.',
                  'approvalSource': None, 'rateSource': None,
                  'news': [n for n in news if key == 'global' or key in n['regions']][:9]}
        if key in ('global', 'northAmerica'):
            scope = 'US benchmark; not a global aggregate' if key == 'global' else 'US subset; Canada and Mexico not covered'
            region['summary'] = f'{title}: quantitative coverage is currently limited to US public-source benchmarks. {scope}. News is drawn from English-language feeds; coverage is selective.'
            fda = sources['fda']['data']
            if fda:
                records = fda['records']
                cutoff = date.fromisoformat(fda['latest'])
                last_year = min(cutoff.year, today.year)
                years = list(range(last_year - 5, last_year + 1))
                region['years'] = [str(y) + (f' (through {cutoff:%d %b})' if y == cutoff.year else '') for y in years]
                region['approvals'] = [sum(r['date'].startswith(str(y)) for r in records) for y in years]
                region['approvalTitle'] = 'US FDA-listed Radiology AI Authorisations — US coverage only'
                region['approvalSource'] = 'fda'
                region['approvalNote'] = f'{scope}. Unique submission IDs; all authorisation pathways. Latest decision in the source: {fda["latest"]}. FDA list is non-exhaustive and updated periodically; the last year is partial and may lag today. VC funding is unavailable and is not plotted.'
                count = sum(r['code'] == 'LLZ' and r['submission'].startswith('K') for r in records)
                metrics[5] = metric('US FDA-listed AI LLZ Clearances', 'Radiology 510(k) submissions with primary code LLZ in FDA’s AI list. Not all LLZ clearances and not all AI authorisations. ' + scope + '.', f'{count:,}', 'Cumulative listed submissions', 'fda', fda['latest'])
            rate = sources['us_rate']['data']
            if rate:
                day = max(rate)
                metrics[0] = metric('US Fed Target Range — Upper Limit', scope + '. Upper bound, not effective funds rate or a regional average.', f'{rate[day]:.2f}%', 'Percent per annum', 'us_rate', day)
                region['months'], region['rateValues'] = month_series(rate, today)
                region.update(rateSource='us_rate', rateTitle='US Fed Target Upper Limit — six months', rateNote=scope + '. Last available observation per month; current month is partial. No MedTech index is configured, so no index comparison is plotted.')
            cpi = sources['us_cpi']['data']
            if cpi:
                day = max(cpi)
                prior = shift_month(date.fromisoformat(day), -12).isoformat()
                if prior in cpi:
                    yoy = (cpi[day] / cpi[prior] - 1) * 100
                    metrics[1] = metric('US Medical Care CPI — YoY', 'BLS consumer medical-care prices, seasonally adjusted, via FRED. Not hospital operating-cost inflation. ' + scope + '.', f'{yoy:+.2f}%', 'Change from same month one year earlier', 'us_cpi', day)
        elif key == 'europe':
            region['summary'] = 'Europe: ECB rates cover the euro area only, excluding non-euro-area economies such as the UK. No pan-European AI authorisation, workforce, reimbursement or revenue totals are asserted.'
            rate = sources['ecb']['data']
            if rate:
                day = max(rate)
                metrics[0] = metric('ECB Deposit Facility Rate', 'Euro-area monetary-policy benchmark, not a Europe-wide policy rate.', f'{rate[day]:.2f}%', 'Percent per annum; euro-area coverage', 'ecb', day)
                region['months'], region['rateValues'] = month_series(rate, today)
                region.update(rateSource='ecb', rateTitle='ECB Deposit Facility Rate — euro area only', rateNote='Last available observation per month; current month is partial. No European MedTech index is configured, so no index comparison is plotted.')
        else:
            region['summary'] = f'{title}: no verified quantitative regional aggregation is currently configured. Available headlines are selected by explicit geographic terms; they do not establish comprehensive regional coverage. US and euro-area figures are not substituted.'
        payload['regions'][key] = region
    return payload


FALLBACK_CSS = '''
<style id="ai-fallback-theme">
:root{--border-color:#303e50;--text-main:#e8eef7}*{box-sizing:border-box}body{margin:0;background:#0c1422;color:#e8eef7;font:15px/1.55 system-ui,sans-serif}a{color:#74c8ff}header,main,footer{max-width:1400px;margin:auto;padding:24px}.header-content{display:flex;justify-content:space-between;align-items:center;gap:24px}.nav-tabs{display:flex;gap:16px}.tab-btn.active{color:#fff}.dashboard-grid,.ticker-banner{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:18px}.ticker-banner{grid-template-columns:repeat(5,minmax(0,1fr));margin:20px 0}.card,.ticker-card{padding:20px;border:1px solid #303e50;border-radius:12px;background:#121e30;min-width:0}.col-12{grid-column:span 12}.col-8{grid-column:span 8}.col-6{grid-column:span 6}.col-4{grid-column:span 4}.col-3{grid-column:span 3}h1{font-size:28px}h2{font-size:19px;margin-top:0}.metric-label{font-size:13px;color:#adbbd0}.metric{font-size:25px;font-weight:700}.metric-sub,.metric-desc{font-size:13px;color:#adbbd0}.region-filter-container{margin:0 0 20px}select{background:#15253c;color:white;padding:10px;border-radius:6px}.outlook-factors-grid{display:grid;grid-template-columns:1fr 1fr;gap:24px}canvas{max-height:330px}.footer-disclaimer{font-size:12px;color:#a5b5c9}@media(max-width:900px){.ticker-banner{grid-template-columns:1fr 1fr}.col-8,.col-6,.col-4,.col-3{grid-column:span 12}.header-content{display:block}.nav-tabs{flex-wrap:wrap}}@media(max-width:550px){.ticker-banner,.outlook-factors-grid{grid-template-columns:1fr}}
</style>'''

RUNTIME = r'''
<script id="ai-data" type="application/json">__DATA__</script>
<script id="ai-dashboard-runtime">
(() => {
'use strict';
const payload=JSON.parse(document.getElementById('ai-data').textContent);
const charts={};
const text=(id,value)=>{const el=document.getElementById(id);if(el)el.textContent=value;};
const add=(parent,tag,value)=>{const el=document.createElement(tag);if(value!==undefined)el.textContent=value;parent.appendChild(el);return el;};
function source(parent,key,observed){
 if(!key)return;
 const s=payload.sources[key];if(!s)return;
 const line=add(parent,'div');line.className='metric-desc';
 const a=add(line,'a',s.name);a.href=s.url;a.target='_blank';a.rel='noopener noreferrer';
 add(line,'span',` · ${s.status==='cached'?'CACHED — refresh failed/offline':s.status==='live'?'Retrieved':'Unavailable'}${s.fetched_at?' '+s.fetched_at.slice(0,10):''}${observed?' · Observation: '+observed:''}`);
}
function metric(i,m){
 const box=document.getElementById('ai-metric-'+i);
 if(!box)return;
 box.querySelector('.metric-label').textContent=m.label;
 box.querySelector('.metric').textContent=m.value===null?'Not available':m.value;
 box.querySelector('.metric-sub').textContent=m.basis;
 const desc=box.querySelector('.metric-desc');desc.replaceChildren();add(desc,'span',m.description);source(desc,m.source,m.observed);
}
function plot(id,title,labels,values,note,key){
 const canvas=document.getElementById(id);const card=canvas.closest('.card');
 card.querySelector('h2').textContent=title;
 if(charts[id]){charts[id].destroy();delete charts[id];}
 let caption=card.querySelector('[data-chart-note]');if(!caption){caption=add(card,'p');caption.dataset.chartNote='';caption.className='metric-desc';}
 caption.replaceChildren();add(caption,'span',note);source(caption,key);
 const hasData=values.some(v=>typeof v==='number'&&Number.isFinite(v));
 canvas.hidden=!hasData||typeof Chart==='undefined';
 if(hasData&&typeof Chart!=='undefined'){
 charts[id]=new Chart(canvas.getContext('2d'),{type:'line',data:{labels,datasets:[{label:title,data:values,borderColor:'#38bdf8',backgroundColor:'rgba(56,189,248,.1)',fill:true,tension:0,spanGaps:false}]},options:{responsive:true,plugins:{legend:{display:false}},scales:{y:{title:{display:true,text:id==='macroChart'?'Percent per annum':'Listed authorisations'},beginAtZero:id!=='macroChart'}}}});
 }else if(hasData){add(caption,'p','Chart library could not load. Data are shown below.');}
 // Accessible numeric alternative, also works if the CDN is blocked.
 let table=card.querySelector('[data-chart-table]');if(table)table.remove();
 if(hasData){table=add(card,'table');table.dataset.chartTable='';table.style.width='100%';table.style.fontSize='12px';const tr=add(table,'tr');add(tr,'th','Period');add(tr,'th',id==='macroChart'?'Rate (%)':'Listed authorisations');labels.forEach((label,i)=>{const row=add(table,'tr');add(row,'td',label);add(row,'td',values[i]===null?'Unavailable':String(values[i]));});}
}
function update(regionKey){
 const key=Object.prototype.hasOwnProperty.call(payload.regions,regionKey)?regionKey:'global';
 const r=payload.regions[key];document.getElementById('regionSelect').value=key;
 text('regional-summary-text',r.summary);r.metrics.forEach((m,i)=>metric(i,m));
 const available=r.metrics.filter(m=>m.value!==null).length;
 text('outlook-title',r.name+' — Coverage and Evidence');
 text('outlook-badge',available+' / 9 metric cards populated');
 text('outlook-summary-text','This is a source-coverage summary, not an investment forecast. Missing figures are not zeros. National benchmarks are labelled explicitly. Page built '+payload.generated_at.slice(0,10)+'.');
 text('ai-drivers','Available evidence: '+r.metrics.filter(m=>m.value!==null).map(m=>m.label).join('; ') + (available?'':'No quantitative source coverage for this selection.'));
 text('ai-headwinds','Coverage gaps: '+r.metrics.filter(m=>m.value===null).map(m=>m.label).join('; ')+'.');
 text('highlights-title','Regional Coverage Notes');text('ai-highlights',r.summary);
 plot('approvalsChart',r.approvalTitle,r.years,r.approvals,r.approvalNote,r.approvalSource);
 plot('macroChart',r.rateTitle,r.months,r.rateValues,r.rateNote,r.rateSource);
 const feed=document.getElementById('news-feed-container');feed.replaceChildren();
 add(feed,'p',key==='global'?'Selected imaging-AI headlines from the past 90 days; not a comprehensive market feed.':'Headlines mentioning this geography in the title or summary. Keyword matching is indicative and English-language coverage is incomplete.');
 if(!r.news.length)add(feed,'p','No matching, dated headlines available from the configured feeds. This does not mean no developments occurred.');
 r.news.forEach(n=>{const item=add(feed,'article');item.style.marginBottom='16px';const a=add(item,'a',n.title);a.href=n.url;a.target='_blank';a.rel='noopener noreferrer';source(item,n.source,n.date);});
 const status=document.getElementById('ai-source-status');status.replaceChildren();
 Object.entries(payload.sources).forEach(([key,s])=>{const row=add(status,'li');source(row,key);});
}
const select=document.getElementById('regionSelect');
select.addEventListener('change',()=>{const url=new URL(location.href);url.searchParams.set('region',select.value);try{history.pushState({},'',url);}catch(e){}update(select.value);});
window.addEventListener('popstate',()=>update(new URLSearchParams(location.search).get('region')));
update(new URLSearchParams(location.search).get('region'));
})();
</script>
'''


def render_template(template, payload, fallback_theme=False):
    """Adapt the supplied template without requiring hand edits to ai.html."""
    if 'ai-dashboard-runtime' in template:
        raise ValueError('Input is generated HTML. Supply the original ai.template.html instead.')
    required = ['GLOBAL_SUMMARY_PLACEHOLDER', 'FDA_LLZ_CLEARANCES_PLACEHOLDER', 'NEWS_ITEMS_PLACEHOLDER']
    if any(name not in template for name in required):
        raise ValueError('Input does not match the supplied AI dashboard template')
    # Replace the old hard-coded chart/update script in one operation. The external
    # Chart.js tag is retained and pinned; all rendering reads one embedded object.
    script_re = re.compile(r'<script\b([^>]*)>([\s\S]*?)</script>', re.I)
    count = [0]
    def remove_old(match):
        if 'const regionData' in match.group(2):
            count[0] += 1
            return ''
        return match.group(0)
    output = script_re.sub(remove_old, template)
    if count[0] != 1: raise ValueError('Expected exactly one dashboard initialisation script')
    output = output.replace('https://cdn.jsdelivr.net/npm/chart.js', 'https://cdn.jsdelivr.net/npm/chart.js@4.4.8/dist/chart.umd.min.js')
    counter = [0]
    # Stable matching uses known metric-card opening tags. Inner HTML is left
    # intact; initial placeholders become safe strings and runtime fills metadata.
    def identify(match):
        i=counter[0];counter[0]+=1
        return f'<div class="{match.group(1)}" id="ai-metric-{i}">'
    output = re.sub(r'<div class="(ticker-card|card col-3)">', identify, output)
    if counter[0] != 9: raise ValueError('Expected five ticker and four sector metric cards')
    mapping = {
        'REGIONAL_SUMMARY_PLACEHOLDER': html.escape(payload['regions']['global']['summary']),
        'DRIVERS_CARDS_PLACEHOLDER': '<p id="ai-drivers"></p>',
        'HEADWINDS_CARDS_PLACEHOLDER': '<p id="ai-headwinds"></p>',
        'HIGHLIGHTS_CARDS_PLACEHOLDER': '<p id="ai-highlights"></p>',
        'MODALITY_ANALYSIS_PLACEHOLDER': 'Not available: no validated device-to-modality classification and denominator are configured. No shares are inferred from product names.',
        'MACRO_ANALYSIS_PLACEHOLDER': '',
        'VENDOR_REVENUE_SOURCE_DESCRIPTION_PLACEHOLDER': 'Not available: comparable vendor AI revenue and specialty-level market-share disclosures have not been established. No estimated pie-chart shares are presented.',
        'NEWS_ITEMS_PLACEHOLDER': 'Loading dated, source-linked headlines…',
        'OUTLOOK_BADGE_STYLE_PLACEHOLDER': '',
        'OUTLOOK_PERIOD_PLACEHOLDER': '',
        'OUTLOOK_BADGE_PLACEHOLDER': 'Source coverage',
        'OUTLOOK_SUMMARY_PLACEHOLDER': 'Public-source evidence and explicit coverage gaps.',
        'MEDTECH_INDEX_NAME_PLACEHOLDER': '',
    }
    def replace_placeholder(match):
        return mapping.get(match.group(1), 'Not available')
    output = re.sub(r'<!--\s*([A-Z0-9_]+_PLACEHOLDER)\s*-->', replace_placeholder, output)
    if re.search(r'\b[A-Z0-9_]+_PLACEHOLDER\b', output):
        raise ValueError('Unresolved template placeholders remain')
    for cid in ['modalityChart', 'totalVendorChart', 'cardioVendorChart', 'pulmoVendorChart', 'neuroVendorChart', 'breastVendorChart', 'oncologyVendorChart']:
        output = output.replace(f'<canvas id="{cid}"></canvas>', '<p class="metric-desc">Not available — no validated comparable dataset.</p>')
    output = output.replace('KEY DRIVERS', 'AVAILABLE EVIDENCE').replace('KEY HEADWINDS', 'COVERAGE GAPS')
    output = output.replace('grid-template-columns: repeat(3, 1fr)', 'grid-template-columns: repeat(auto-fit, minmax(220px, 1fr))')
    output = output.replace('While metrics and figures are sourced from public registers, APIs, and market estimates,', 'Available figures are linked to public sources; unsupported metrics are labelled unavailable. Geographic subsets and source limitations are disclosed. However,')
    status = '<section class="card" style="margin-top:24px"><h2>Source status and retrieval dates</h2><ul id="ai-source-status"></ul></section><noscript>This dashboard requires JavaScript. Enable JavaScript to view populated metrics and sources.</noscript>'
    output = output.replace('</main>', status + '\n</main>')
