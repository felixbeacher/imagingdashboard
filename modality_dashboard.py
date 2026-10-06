#!/usr/bin/env python3

"""
This file is a shared Python engine for the CT, MRI, PET, and X-ray dashboards
Purpose: Powers the 4 updater scripts to ensure consistent behaviour and simplified maintenance.
Core Functions: 
1. Defines modality metrics
2. validates JSON data (values, dates, sources)
3. fetches WHO equipment-density benchmarks, registered-study activity,
   US financial context, US FDA clearances and RSS headlines
4. populates HTML templates (leaving blank sections where data is unavailable).
"""

from __future__ import annotations
import argparse
import copy
import importlib.util
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('imaging_ai_base', BASE_DIR / 'ai_update_data.py')
ai = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ai)

def measure(key, label, group, unit, description, rule='nonnegative'):
    return dict(key=key, label=label, group=group, unit=unit, description=description, rule=rule)

COMMON = [
    measure('systems_density', 'Reported scanner capacity benchmark', 'Capacity & use', 'systems / million people', 'Sourced equipment density or an explicitly labelled median of country densities. WHO reports availability, not verified operational status. Country samples and observation years are disclosed; a country median is not pooled regional density.'),
    measure('exam_volume', 'Annual examination volume', 'Capacity & use', 'examinations', 'Completed examinations in the stated coverage and year; distinguish examinations from images, sequences and billed procedures.', 'count'),
    measure('imaging_growth', 'Examination volume growth', 'Capacity & use', '% YoY', 'Year-on-year change using comparable institutions, examinations and reporting periods.', 'signed'),
    measure('scan_wait', 'Referral-to-examination wait', 'Clinical access', 'days', 'Median referral-to-examination wait; specify urgency, patient pathway and sample.'),
    measure('reporting_time', 'Reporting turnaround', 'Clinical access', 'hours', 'Median examination-completion to final-report time; distinguish urgent and routine pathways.'),
    measure('staff_vacancy', 'Imaging staff vacancy rate', 'Clinical access', '%', 'Unfilled funded modality-relevant posts divided by all funded posts. State roles and full-time-equivalent basis.', 'percent'),
    measure('prospective_studies', 'Prospective evidence / registered-study activity', 'Evidence & quality', 'studies', ai.TRIAL_DESCRIPTION, 'count'),
    measure('procurement_time', 'Procurement-to-clinical-use time', 'Commercial delivery', 'months', 'Median contract-award to routine clinical-use time, including installation, commissioning and staff training.'),
    measure('contract_awards', 'Disclosed equipment contract awards', 'Commercial delivery', 'contracts', 'Paid equipment procurement awards; deduplicate announcements and state whether one award covers several systems.', 'count'),
    measure('replacement_share', 'Systems beyond stated replacement age', 'Commercial delivery', '%', 'Operational systems older than a stated threshold divided by surveyed systems. Age alone does not establish a need to replace.', 'percent'),
]
CONTEXT = [
    measure('policy_rate', 'Financing rate proxy', '', '%', 'Name the jurisdiction and benchmark. A G7 average is a G7 financing proxy; disclose constituent countries, dates and weighting.', 'signed'),
    measure('inflation', 'Healthcare price inflation proxy', '', '% YoY', 'CPI is a price-pressure proxy, not a hospital input-cost index. State source, country coverage, components and aggregation weights.', 'signed'),
    measure('equity_return', 'US healthcare equity benchmark return', '', '%', 'State benchmark, currency, period and price/total-return basis. XLV covers US healthcare; IHI covers US medical devices. Neither isolates this modality.', 'signed'),
    measure('operating_cost', 'Equipment operating cost per examination', '', 'currency / exam', 'State currency and price year, workload and included service, staff, consumables and energy costs. Specify whether capital depreciation is included.'),
]
CONFIGS = {
 'ct': dict(number=2, name='CT', full='Computed tomography', codes=['JAK'], scope='CT systems with primary FDA product code JAK; excludes separately coded accessories and other regulatory pathways.',
    extra=[measure('dose', 'Typical adult CT dose index', 'Evidence & quality', 'mGy CTDIvol', 'Protocol-specific median CTDIvol; state body region, patient size and diagnostic reference level. This is not effective dose or a cross-modality comparison.'), measure('advanced_share','Advanced CT systems in service','Capacity & use','%','Share of surveyed systems meeting a stated spectral or photon-counting technology definition; deduplicate systems.','percent')],
    segments=['Conventional CT','Spectral / dual-energy CT','Photon-counting CT','Other / unclassified'], applications=['Oncology','Cardiovascular','Neurology','Trauma / emergency','Other / multiple','Unclassified'],
    regex=r'\b(CT|computed tomography|photon.counting|spectral CT)\b'),
 'mri': dict(number=3, name='MRI', full='Magnetic resonance imaging', codes=['LNH'], scope='MR imaging systems with primary FDA product code LNH; excludes separately coded coils, accessories and other regulatory pathways.',
    extra=[measure('scan_duration','Typical examination duration','Evidence & quality','minutes / exam','Median acquisition time for a specified protocol; state anatomy, sequences and whether preparation or room turnover is included.'), measure('repeat_rate','Repeat / incomplete examination rate','Evidence & quality','%','Examinations repeated or incomplete under a stated definition divided by attempted examinations; specify causes and avoid double counting.','percent')],
    segments=['Below 1.5 T','1.5 T','3 T','Above 3 T','Unclassified'], applications=['Neurology','Musculoskeletal','Oncology','Cardiovascular','Other / multiple','Unclassified'],
    regex=r'\b(MRI|magnetic resonance|MR imaging|low.field MRI)\b'),
 'pet': dict(number=4, name='PET', full='Positron emission tomography', codes=['KPS'], scope='Broader emission-tomography benchmark: primary product code KPS includes PET and SPECT. Counts are not PET-only. Radiopharmaceutical approvals are excluded.',
    extra=[measure('tracer_disruption','Tracer-related cancellations','Clinical access','%','Scheduled PET examinations cancelled because of tracer supply divided by scheduled examinations; state tracers and whether rescheduling is included.','percent'), measure('advanced_share','Digital / total-body PET systems','Capacity & use','%','Share of surveyed systems meeting a stated digital or total-body definition; avoid counting a system in both categories.','percent')],
    segments=['Conventional PET/CT','Digital PET/CT','Total-body PET/CT','PET/MRI','Other / unclassified'], applications=['Oncology','Neurology','Cardiology','Other / multiple','Unclassified'],
    regex=r'\b(PET|positron emission|PET/CT|PET/MR|radiotracer)\b'),
 'xray': dict(number=5, name='X-ray', full='Projection radiography & fluoroscopy', codes=['KPR','IZL','MQB','JAA','JAB'], scope='Selected primary product codes: KPR stationary X-ray, IZL mobile X-ray, MQB digital X-ray imagers, JAA/JAB fluoroscopy. This includes some components; it is not an exhaustive X-ray equipment market or an installed-system count. CT, mammography and dental-only codes are excluded.',
    extra=[measure('digital_share','Digital radiography share','Capacity & use','%','Digital general-radiography examinations divided by general-radiography examinations; define direct and computed radiography, and exclude fluoroscopy.','percent'), measure('reject_rate','Rejected image rate','Evidence & quality','%','Rejected acquired radiographs divided by all acquired radiographs in the stated quality audit; this is an image-level measure, not an examination repeat rate.','percent')],
    segments=['Fixed general radiography','Mobile radiography','Fluoroscopy','Other / unclassified'], applications=['Chest','Musculoskeletal','Abdomen','Fluoroscopy procedures','Other / multiple','Unclassified'],
    regex=r'\b(X.ray|radiography|fluoroscopy|radiograph)\b'),
}
for slug, config in CONFIGS.items():
    config['slug'] = slug
    config['metrics'] = COMMON[:3] + config['extra'] + COMMON[3:]
    config['template'] = f"{slug}.html"


def normalise_measure(raw, definition, errors, path):
    result = ai.missing(definition['label'], definition['unit'])
    if not raw or isinstance(raw, dict) and raw.get('value') is None:
        if isinstance(raw, dict): result['reason'] = str(raw.get('reason') or result['reason'])
        return result
    try:
        meta = ai.provenance(raw)
        value, rule = raw.get('value'), definition['rule']
        if not ai.finite_number(value): raise ValueError('value must be finite and numeric')
        if rule != 'signed' and value < 0: raise ValueError('value cannot be negative')
        if rule == 'count' and value != int(value): raise ValueError('counts must be integers')
        if rule == 'percent':
            if not 0 <= value <= 100: raise ValueError('share must be between 0 and 100')
            if not isinstance(raw.get('denominator'), str) or not raw['denominator'].strip(): raise ValueError('share requires a denominator definition')
        unit = str(raw.get('unit') or definition['unit'])
        if unit != definition['unit'] and definition['key'] != 'operating_cost': raise ValueError('unit must match the defined measure')
        result.update(meta, value=value, unit=unit, label=str(raw.get('label') or definition['label']),
                      denominator=str(raw.get('denominator','')), reason='')
        if definition['key'] == 'policy_rate' and 'G7' in str(raw.get('label','')): result['label'] = 'G7 financing proxy'
    except (ValueError, TypeError) as exc:
        errors.append(f'{path}: {exc}')
        result['reason'] = 'The observation did not pass source and definition checks.'
    return result


def normalise_mix(raw, label, unit, categories, errors, path):
    result = ai.missing(label, unit) | {'items': [], 'total': None, 'categories': categories}
    if not raw or isinstance(raw,dict) and not raw.get('items'): return result
    try:
        meta = ai.provenance(raw)
        if raw.get('basis') != 'exclusive_items': raise ValueError('basis must be exclusive_items: one category per system or examination')
        if raw.get('unit') != unit: raise ValueError(f'unit must be {unit}')
        total = raw.get('total')
        if not ai.finite_number(total) or total < 0 or int(total) != total: raise ValueError('total must be a nonnegative integer')
        items, seen = [], set()
        for row in raw['items']:
            label_, value = row['label'], row['value']
            if label_ not in categories or label_ in seen: raise ValueError('unknown or duplicate category')
            if not ai.finite_number(value) or value < 0 or int(value) != value: raise ValueError('category counts must be nonnegative integers')
            seen.add(label_); items.append({'label': label_, 'value': value})
        if sum(x['value'] for x in items) != total: raise ValueError('category counts must sum to total; classify residuals explicitly')
        result.update(meta, items=items, total=total, reason='')
    except (ValueError, TypeError, KeyError) as exc:
        errors.append(f'{path}: {exc}'); result['reason'] = 'The classification did not pass source and exclusivity checks.'
    return result


def normalise_vendors(rows, errors, path):
    result = []
    if not isinstance(rows,list): errors.append(f'{path}: expected list'); return result
    for i,row in enumerate(rows):
        try:
            meta = ai.provenance(row)
            low, high = row.get('revenue_low'),row.get('revenue_high')
            if not ai.finite_number(low) or not ai.finite_number(high) or low < 0 or high < low: raise ValueError('valid revenue bounds required')
            for key in ('vendor','application','currency','revenue_scope'):
                if not isinstance(row.get(key),str) or not row[key].strip(): raise ValueError(f'{key} required')
            result.append(meta | {k:row[k] for k in ('vendor','application','currency','revenue_scope')} | dict(revenue_low=low,revenue_high=high))
        except (ValueError,TypeError) as exc: errors.append(f'{path}[{i}]: {exc}')
    return result


FDA_API = 'https://api.fda.gov/device/510k.json'
SE_CODES = ['SESE','SEKD','SESD','SESK','SESP','SESL']

def api_query(search):
    url = FDA_API + '?' + urllib.parse.urlencode({'search':search,'limit':1})
    try:
        return json.loads(ai.read_url(url)), url
    except urllib.error.HTTPError as exc:
        # Only openFDA's explicit NOT_FOUND is a zero; outages/auth/rate limits are errors.
        if exc.code == 404:
            body = json.loads(exc.read(1_000_000))
            if body.get('error',{}).get('code') == 'NOT_FOUND': return {'meta': {'results': {'total':0}}, 'results': []}, url
        raise


def regulatory_benchmark(config, offline=False):
    label = ('US emission-tomography 510(k) clearances' if config['slug']=='pet' else f"US {config['name']} selected 510(k) clearances")
    notice = config['scope'] + ' US regulatory activity only; not adoption, unique products, installed systems, revenue or global approvals. Counts use decision dates and the openFDA snapshot; recent periods may be incomplete.'
    result = {'metric':ai.missing(label,'clearances'),'series':ai.missing(label,'clearances') | {'points':[]},'retrieved_at':'','notice':notice}
    if offline:
        for field in ('metric','series'): result[field]['reason']='Live sources are disabled in offline mode.'
        return result
    try:
        codes = ' OR '.join(f'product_code:"{x}"' for x in config['codes'])
        decisions = ' OR '.join(f'decision_code:"{x}"' for x in SE_CODES)
        base = f'({codes}) AND ({decisions})'
        initial, source_url = api_query(base)
        snapshot = str(initial.get('meta',{}).get('last_updated',''))[:10]
        endpoint_date = ai.iso_date(snapshot)
        if endpoint_date > date.today(): raise ValueError('source snapshot is in the future')
        # Compute the year and the six-quarter window from the source snapshot, not today's year.
        quarter_index = endpoint_date.year * 4 + (endpoint_date.month-1)//3
        periods=[]
        for offset in range(5,-1,-1):
            y,q = divmod(quarter_index-offset,4)
            start=date(y,q*3+1,1)
            next_y,next_q=divmod(quarter_index-offset+1,4)
            end=min(date(next_y,next_q*3+1,1)-timedelta(days=1), endpoint_date)
            periods.append(dict(start=start.isoformat(),end=end.isoformat(),label=f'{y} Q{q+1}' + ('*' if end==endpoint_date and end != date(next_y,next_q*3+1,1)-timedelta(days=1) else '')))
        def count_period(period):
            search=base + f" AND decision_date:[{period['start'].replace('-','')} TO {period['end'].replace('-','')}]"
            response,_=api_query(search)
            other=response.get('meta',{}).get('last_updated')
            if other and str(other)[:10] != snapshot: raise ValueError('source snapshot changed during refresh; retry later')
            count=response['meta']['results']['total']
            if not isinstance(count,int) or count < 0: raise ValueError('invalid result count')
            return period | {'value':count}
        year_period=dict(start=f'{endpoint_date.year}-01-01',end=snapshot,label='Year to snapshot')
        with ThreadPoolExecutor(max_workers=3) as executor: counts=list(executor.map(count_period,periods+[year_period]))
        meta={'status':'reported','geography':'United States (external benchmark)', 'period':f'{year_period["start"]} to {snapshot}', 'as_of':snapshot, 'source':{'name':'openFDA device 510(k) database','url':source_url}, 'methodology':f"Counts of database entries with primary product codes {', '.join(config['codes'])} and decision codes {', '.join(SE_CODES)}. OR query counts each database entry once. Excludes non-SE decisions and other pathways. Snapshot: {snapshot}. " + config['scope']}
        result['metric'].update(meta,value=counts[-1]['value'],reason='')
        result['series'].update(meta,points=counts[:-1],period=f'{periods[0]["start"]} to {snapshot}',reason='')
        result['retrieved_at']=ai.utc_now()
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logging.warning('%s FDA benchmark unavailable: %s',config['name'],exc)
        for field in ('metric','series'): result[field]['reason']='The openFDA benchmark could not be retrieved or validated; no zero has been inferred.'
    return result


def fetch_news(config, offline=False):
    if offline: return [], ['Live news is disabled in offline mode.']
    def one(item):
        name,url=item
        try:
            # Reuse the RSS/Atom parser but with a modality-specific relevance expression.
            root=ai.ET.fromstring(ai.read_url(url,2_000_000)); rows=[]; ns={'a':'http://www.w3.org/2005/Atom'}
            for node in root.findall('.//item') or root.findall('a:entry',ns):
                title=re.sub(r'<[^>]+>','',node.findtext('title') or node.findtext('a:title',namespaces=ns) or '').strip()
                if not re.search(config['regex'],title,re.I): continue
                link=node.findtext('link') or ''
                if not link:
                    el=node.find('a:link',ns); link=el.get('href','') if el is not None else ''
                if not ai.safe_url(link): continue
                published=''; raw=node.findtext('pubDate') or node.findtext('a:published',namespaces=ns) or node.findtext('a:updated',namespaces=ns)
                if raw:
                    try:
                        dt=ai.parsedate_to_datetime(raw) if ',' in raw else ai.datetime.fromisoformat(raw.replace('Z','+00:00'))
                        if dt.date() <= date.today(): published=dt.date().isoformat()
                    except (ValueError,TypeError): pass
                rows.append(dict(title=title,url=ai.safe_url(link),source=name,published=published))
            return rows,None
        except (OSError,ValueError,ai.ET.ParseError) as exc:
            logging.warning('%s RSS unavailable: %s',name,exc); return [],f'{name}: feed unavailable.'
    rows=[]; failures=[]; seen=set()
    with ThreadPoolExecutor(max_workers=len(ai.RSS_FEEDS)) as executor:
        for items,error in executor.map(one,ai.RSS_FEEDS.items()):
            if error: failures.append(error)
            for item in items:
                if item['url'] not in seen: seen.add(item['url']); rows.append(item)
    return sorted(rows,key=lambda x:x['published'],reverse=True)[:12],failures


def series_input(raw):
    # Empty example/scaffold objects are deliberate absences, not rejected evidence.
    if isinstance(raw, dict) and raw.get('status') == 'unavailable' and not raw.get('points'):
        return None
    return raw


def normalise_trend(raw, label, unit, errors, path, procurement=False):
    raw = series_input(raw)
    if isinstance(raw, dict):
        actual_unit = raw.get('unit') or unit
        reason = None
        if procurement and not re.fullmatch(r'[A-Z]{3} millions', actual_unit):
            reason = 'procurement series requires an explicit currency unit, e.g. GBP millions'
        elif not procurement and actual_unit != unit:
            reason = 'authorisation series unit must be authorisations'
        if reason:
            errors.append(f'{path}: {reason}')
            return ai.missing(label, unit, 'The series did not pass unit checks.') | {'points': []}
    result = ai.normalise_series(raw, label, unit, errors, path)
    if not procurement and any(p['value'] is not None and p['value'] != int(p['value']) for p in result['points']):
        errors.append(f'{path}: authorisation counts must be integers')
        return ai.missing(label, unit, 'The series did not pass count checks.') | {'points': []}
    return result


def editorial_input(raw):
    if isinstance(raw, dict) and not any(raw.get(k) for k in ('summary','drivers','headwinds','highlights')):
        return None
    return raw


def build_dashboard(slug, data_path=None, offline=False):
    config=CONFIGS[slug]; errors=[]; raw=ai.load_curated(data_path,errors)
    if raw and raw.get('modality') != slug:
        errors.append('Curated file modality does not match this dashboard; observations withheld.'); raw={}
    automatic=ai.automatic_observations(slug,offline or raw.get('auto_sources') is False)
    raw=ai.merge_automatic(raw,automatic)
    regions={}
    for key,name in ai.REGIONS.items():
        region=raw.get('regions',{}).get(key,{})
        if not isinstance(region,dict): errors.append(f'{key}: region must be an object'); region={}
        metrics=region.get('metrics',{}); context=region.get('context',{})
        if not isinstance(metrics,dict): errors.append(f'{key}.metrics: expected object'); metrics={}
        if not isinstance(context,dict): errors.append(f'{key}.context: expected object'); context={}
        regions[key]=dict(name=name,
            metrics={d['key']:normalise_measure(metrics.get(d['key']),d,errors,f'{key}.metrics.{d["key"]}') for d in config['metrics']},
            context={d['key']:normalise_measure(context.get(d['key']),d,errors,f'{key}.context.{d["key"]}') for d in CONTEXT},
            authorisations=normalise_trend(region.get('authorisations'),f"Local {config['name']} equipment authorisations",'authorisations',errors,f'{key}.authorisations'),
            funding=normalise_trend(region.get('funding'),f"{config['name']} equipment procurement expenditure",'currency millions',errors,f'{key}.funding',procurement=True),
            modalities=normalise_mix(region.get('modalities'),'Operational system mix','systems',config['segments'],errors,f'{key}.modalities'),
            applications=normalise_mix(region.get('applications'),'Clinical examination mix','examinations',config['applications'],errors,f'{key}.applications'),
            vendors=normalise_vendors(region.get('vendors',[]),errors,f'{key}.vendors'),
            editorial=ai.normalise_editorial(editorial_input(region.get('editorial')),errors,f'{key}.editorial'))
    benchmark=regulatory_benchmark(config,offline)
    news,failures=fetch_news(config,offline)
    return dict(schema_version=1,modality=slug,generated_at=ai.utc_now(),regions=regions,
        definitions={'metrics':config['metrics'],'context':CONTEXT}, fda_benchmark=benchmark,
        news=news,news_notice=f"Global {config['name']} headline feed; it does not change with the region selector. Title matching is selective and is not comprehensive coverage.",news_failures=failures,
        headline_summary={'text':'','label':'','sources':[]},quality_messages=errors,
        data_collection={'automatic_sources':automatic,
            'notice':'Automatic public benchmarks have partial geography and dated source coverage. '
                     'Other clinical and commercial indicators require sourced curated inputs.'})


class ModalityService(ai.DashboardService):
    def __init__(self,slug,template_path=None,data_path=None,offline=False,cache_seconds=900):
        self.slug=slug
        super().__init__(template_path or BASE_DIR / CONFIGS[slug]['template'],data_path,offline,False,cache_seconds)
    def payload(self):
        with self.lock:
            mtime=self.data_path.stat().st_mtime_ns if self.data_path and self.data_path.exists() else None
            if self.cached is None or time.monotonic()-self.cache_time >= self.cache_seconds or mtime != self.data_mtime:
                self.cached=build_dashboard(self.slug,self.data_path,self.offline)
                self.cache_time=time.monotonic(); self.data_mtime=mtime
            return copy.deepcopy(self.cached)


def site_handler(primary, primary_slug='ai'):
    """One server serves every installed dashboard, with isolated caches/data files."""
    root=primary.template_path.parent
    services={primary_slug:primary}; lock=threading.Lock()
    def get_service(slug):
        with lock:
            if slug not in services:
                data=root / ('dashboard_data.json' if slug=='ai' else f'{slug}_data.json')
                data=data if data.exists() else None
                if slug=='ai': services[slug]=ai.DashboardService(root/'ai.html',data,primary.offline,False,primary.cache_seconds)
                else: services[slug]=ModalityService(slug,root/CONFIGS[slug]['template'],data,primary.offline,primary.cache_seconds)
            return services[slug]
    class Handler(ai.make_handler(primary)):
        def do_GET(self):
            path=urllib.parse.urlsplit(self.path).path
            pages={'/ai.html':'ai','/1_ai.html':'ai','/1_ai_6.html':'ai'}
            for slug,c in CONFIGS.items(): pages['/'+c['template']]=slug; pages['/'+slug+'.html']=slug
            slug=pages.get(path)
            match=re.fullmatch(r'/api/(ai|ct|mri|pet|xray)/(dashboard|fda-clearances)',path)
            if path in ('/api/dashboard','/api/fda-clearances'):
                slug=primary_slug; kind=path.rsplit('/',1)[1]
            elif match: slug,kind=match.groups()
            else: kind=None
            if slug:
                try:
                    service=get_service(slug)
                    if kind:
                        payload=service.payload(); content=payload if kind=='dashboard' else payload['fda_benchmark']
                        self.send_content(200,ai.safe_json(content),'application/json; charset=utf-8')
                    else: self.send_content(200,service.html(),'text/html; charset=utf-8')
                except Exception:
                    logging.exception('Dashboard request failed'); self.send_content(500,'Dashboard unavailable. Check server logs.','text/plain; charset=utf-8')
                return
            super().do_GET()
    return Handler


def main(slug):
    config=CONFIGS[slug]; parser=argparse.ArgumentParser(description=f"Serve/build the {config['name']} dashboard and the complete installed site.")
    parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8080)
    parser.add_argument('--template',type=Path,default=BASE_DIR/config['template'])
    parser.add_argument('--data',type=Path,default=BASE_DIR/f'{slug}_data.json')
    parser.add_argument('--offline',action='store_true'); parser.add_argument('--cache-seconds',type=int,default=900)
    parser.add_argument('--build',type=Path,help='Write a standalone rendered HTML file and exit.')
    args=parser.parse_args()
    if args.cache_seconds < 1: parser.error('--cache-seconds must be positive')
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    data=args.data if args.data.exists() else None
    if not args.data.exists() and args.data != BASE_DIR/f'{slug}_data.json': parser.error('--data file does not exist')
    service=ModalityService(slug,args.template,data,args.offline,args.cache_seconds)
    if args.build:
        if args.build.resolve()==args.template.resolve(): parser.error('--build must not overwrite the source template')
        args.build.parent.mkdir(parents=True,exist_ok=True); args.build.write_text(service.html(),encoding='utf-8'); return
    server=ThreadingHTTPServer((args.host,args.port),site_handler(service,slug))
    logging.info('Dashboard: http://%s:%s/%s',args.host,server.server_port,config['template'])
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
