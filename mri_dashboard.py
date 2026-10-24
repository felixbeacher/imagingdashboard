"""Source-backed MRI modality page generator.

The data pipeline deliberately distinguishes:
* OECD annual equipment and MRI-exam observations (not sales or patient need).
* Recent PubMed MRI research discovery (not systematic evidence synthesis).
* Derived, source-dated analysis performed in the browser on selected annual values.

No imaginary world averages, vendor shares, MRI forecasts or historical interpolation.
"""
import argparse
from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import oecd_imaging
import mri_market

LOG = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
MRI_QUERY = ('("magnetic resonance imaging"[Title] OR "MRI"[Title] OR '
             '"MR imaging"[Title] OR "functional MRI"[Title] OR "diffusion MRI"[Title]) '
             'NOT (review[Publication Type] OR meta-analysis[Publication Type] '
             'OR protocol[Title] OR spectroscopy[Title])')
DOI_RE = re.compile(r'^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$')


def safe_json(obj):
    return (json.dumps(obj, ensure_ascii=False, allow_nan=False)
            .replace('<', '\\u003c').replace('>', '\\u003e')
            .replace('&', '\\u0026').replace('\u2028', '\\u2028')
            .replace('\u2029', '\\u2029'))


def _read(url, max_bytes=1_800_000, timeout=23):
    req = Request(url, headers={
        'User-Agent': 'MedicalImagingDashboard/1.0 (public MRI research indexing)',
        'Accept': 'application/json, application/xml, text/xml, */*',
    })
    with urlopen(req, timeout=timeout) as reply:
        content = reply.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError('Source response exceeds bound')
    return content


def _date(article):
    for x in article.findall('.//ArticleDate'):
        y=x.findtext('Year');m=x.findtext('Month');d=x.findtext('Day')
        if y and m and d and y.isdecimal() and m.isdecimal() and d.isdecimal():
            try:return date(int(y),int(m),int(d)).isoformat()
            except ValueError:pass
    d = article.find('.//PubMedPubDate[@PubStatus="pubmed"]')
    if d is not None:
        y=d.findtext('Year');m=d.findtext('Month');day=d.findtext('Day')
        if y and m and day and all(t.isdecimal() for t in (y,m,day)):
            try:return date(int(y),int(m),int(day)).isoformat()
            except ValueError:pass
    y=article.findtext('.//PubDate/Year')
    if y and y.isdecimal():return y
    return 'Date not supplied'


def _text(node):
    return ' '.join(''.join(node.itertext()).split()) if node is not None else ''


def _kind(title):
    low=title.casefold()
    if 'cardiac' in low or 'heart' in low:return 'Cardiac MRI'
    if 'diffusion' in low:return 'Diffusion MRI'
    if 'functional mri' in low or 'fmri' in low:return 'Functional MRI'
    if 'low-field' in low or 'portable' in low:return 'Low-field MRI'
    if 'reconstruction' in low:return 'Acquisition and reconstruction'
    return 'MRI clinical / technical study'


MRI_RESEARCH_CATEGORIES = (
    ('Cardiac MRI', r'cardiac|cardiovascular|myocardial'),
    ('Neuro MRI', r'brain|neuro|cerebral|stroke|demyelina'),
    ('Oncology MRI', r'breast|prostate|cancer|tumou?r|oncolog'),
    ('Musculoskeletal MRI', r'musculoskelet|cartilage|knee|shoulder|spine|vertebr'),
    ('Diffusion / functional MRI', r'diffusion|functional|bold|perfusion'),
    ('MRI acceleration / reconstruction', r'reconstruction|compressed.sensing|undersampl|acceleration'),
    ('Low-field / portable MRI', r'low.field|portable|ultra.low.field|point.of.care'),
)


def mri_research_priority(title, journal, types, has_results):
    """Editorial DISCOVERY heuristic; not a clinical-quality or impact score."""
    title_low = title.casefold()
    journal_low = journal.casefold()
    category = next((name for name, pattern in MRI_RESEARCH_CATEGORIES
                     if re.search(pattern, title_low)), 'Other MRI clinical research')
    if 'Randomized Controlled Trial' in types:
        design_points = 12
    elif 'Clinical Trial' in types:
        design_points = 9
    elif any(t in types for t in ('Validation Study', 'Multicenter Study',
                                  'Comparative Study', 'Observational Study')):
        design_points = 6
    else:
        design_points = 0
    specialist = any(k in journal_low for k in
                     ('radiology', 'roentgen', 'imaging', 'magnetic resonance imaging'))
    score = design_points + (4 if specialist else 0) + (2 if has_results else 0)
    return category, score


def parse_pubmed(xml, expected_ids, limit=10):
    """Validated PubMed output; never infer a trial design from title/abstract."""
    root=ET.fromstring(xml)
    if root.tag != 'PubmedArticleSet':
        raise ValueError('Invalid PubMed response')
    expected=set(expected_ids)
    result=[]
    for art in root.findall('PubmedArticle'):
        pmid=_text(art.find('./MedlineCitation/PMID'))
        title=_text(art.find('.//ArticleTitle'))
        if not pmid.isdecimal() or pmid not in expected or not title:
            continue
        if not re.search(r'\bMRI\b|magnetic resonance|\bMR imaging\b',title,re.I):
            continue
        if re.search(r'\b(?:review|meta-analysis|protocol|photoacoustic|bibliometric)\b|comprehensive (?:literature )?(?:review|survey)|systematic analysis of the literature|\bcase report\b|\bcase presentation\b|a rare case of|photon.counting CT|computed tomography.*compared with MRI',title,re.I):
            continue
        journal=_text(art.find('.//Journal/Title')) or 'Journal not supplied'
        types=[_text(t) for t in art.findall('.//PublicationType') if _text(t)]
        if any(t in types for t in ('Case Reports', 'Editorial', 'Letter', 'Comment',
                                     'Review', 'Systematic Review', 'Meta-Analysis')):
            continue
        if re.search(r'\bcase report\b|\bcase presentation\b|a rare case of|\bcase series\b',title,re.I):
            continue
        design=next((t for t in types if t in (
            'Randomized Controlled Trial','Clinical Trial','Validation Study',
            'Multicenter Study','Comparative Study','Observational Study')), None)
        sections=art.findall('.//Abstract/AbstractText')
        results=next((a for a in sections if a.get('NlmCategory') == 'RESULTS'
                      or a.get('Label','').upper()=='RESULTS'),None)
        words=_text(results).split() if results is not None else []
        excerpt=' '.join(words[:18])+('…' if len(words)>18 else '')
        category, priority=mri_research_priority(title,journal,types,bool(words))
        result.append(dict(
            title=title[:330],url='https://pubmed.ncbi.nlm.nih.gov/'+pmid+'/',
            journal=journal[:160],date=_date(art),kind=_kind(title),
            category=category,priority=priority,
            selection_basis=('Verified indexed study type: '+design if design else
                             'MRI topic and date; design not indexed'),
            design=design or 'Study design not verified by this feed',
            excerpt=excerpt,
        ))
    def published(paper):
        d=paper['date']
        return d if re.fullmatch(r'\d{4}-\d{2}-\d{2}',d) else d[:4]+'-00-00'
    # Indexed design and specialist-journal relevance are editorial discovery
    # signals, not a validated clinical-quality assessment.
    result.sort(key=lambda paper: (paper['priority'],published(paper),paper['title']),
                reverse=True)
    selected=[]
    counts={}
    for paper in result:
        category=paper['category']
        if counts.get(category,0)>=2:
            continue
        selected.append(paper)
        counts[category]=counts.get(category,0)+1
        if len(selected)>=limit:
            break
    selected.sort(key=lambda paper: published(paper),reverse=True)
    return selected


def pubmed_feed(offline=False, today=None):
    today=today or date.today()
    out=dict(status='unavailable',checked=today.isoformat(),count=None,
             items=[],query=MRI_QUERY,window='past 365 days',error='PubMed retrieval unavailable')
    if offline:
        out['error']='Offline mode; no PubMed search performed'
        return out
    try:
        search_url=PUBMED_BASE+'esearch.fcgi?'+urlencode({
            'db':'pubmed','term':MRI_QUERY,'sort':'pub date','retmode':'json',
            'retmax':80,'reldate':365,'datetype':'pdat',
            'tool':'MedicalImagingCTDashboard',
        })
        data=json.loads(_read(search_url).decode('utf-8'))
        query=data.get('esearchresult',{})
        count=int(query['count'])
        ids=query['idlist']
        if count<0 or count>50_000_000 or not isinstance(ids,list) or any(not str(x).isdigit() for x in ids):
            raise ValueError('Malformed PubMed search response')
        if count and not ids:
            raise ValueError('PubMed returned no sample of nonzero matches')
        items=[]
        if ids:
            fetch_url=PUBMED_BASE+'efetch.fcgi?'+urlencode({
                'db':'pubmed','id':','.join(ids),'retmode':'xml',
                'tool':'MedicalImagingCTDashboard',
            })
            items=parse_pubmed(_read(fetch_url),list(map(str,ids)))
        out.update(status='live',count=count,items=items,error='')
    except Exception as exc:
        LOG.warning('MRI PubMed source unavailable: %s',type(exc).__name__)
        out['error']=type(exc).__name__+' — published evidence feed unavailable'
    return out


def empty_oecd():
    return oecd_imaging.fetch(offline=True)



# These are COUNTRY SAMPLES within regions, not geographical aggregates.
# Country annual series are independently published OECD observations. We never
# average differently dated observations or relabel a sampled country as a region.
REGIONAL_GROUPS = {
    'europe': {'name': 'Europe', 'countries': ['CHE', 'GBR', 'DEU', 'FRA']},
    'northAmerica': {'name': 'North America', 'countries': ['USA', 'CAN']},
    'asiaPacific': {'name': 'Asia-Pacific', 'countries': ['AUS', 'JPN']},
}


def _capped_growth(first, last, years, cap):
    if years < 1 or first <= 0 or last <= 0:
        raise ValueError('Valid positive observations are required')
    raw = (last / first)**(1 / years) - 1
    return max(-cap, min(cap, raw)), raw


def mri_trend_scenario(points, mode, through=2027):
    """Backtested *illustrative* scenario, not an OECD or statistical forecast.

    Require four consecutive annual observations ending 2024 or later. Fit
    annualised growth on the first three observations, predict the held-out
    fourth year, and withhold projections when the held-out relative error is
    too large. Refit using the latest four actual readings. The +/-2 pp band
    expresses scenario sensitivity, not a statistical confidence interval.
    """
    if mode not in ('equipment', 'exams'):
        raise ValueError('Unsupported MRI trend kind')
    series = sorted((p['year'], float(p['value'])) for p in points)
    if len(series) < 4 or len({y for y, _ in series}) != len(series):
        return {'status': 'unavailable', 'reason': 'At least four distinct annual OECD observations are required', 'points': []}
    sample = series[-4:]
    if (any(sample[i][0] - sample[i-1][0] != 1 for i in range(1, 4))
            or sample[-1][0] < 2024 or min(v for _, v in sample) <= 0):
        return {'status': 'unavailable', 'reason': 'Four consecutive recent, positive observation years are required', 'points': []}
    if sample[-1][0] >= through:
        return {'status': 'unavailable', 'reason': 'No future scenario years in the requested period', 'points': []}
    cap = 0.05 if mode == 'equipment' else 0.08
    error_limit = 0.10 if mode == 'equipment' else 0.15
    # One-year out-of-sample historical backtest: fit years 1-3; predict year 4.
    trial_rate, _ = _capped_growth(sample[0][1], sample[2][1], 2, cap)
    trial_prediction = sample[2][1] * (1 + trial_rate)
    error = abs(trial_prediction - sample[3][1]) / sample[3][1]
    if error > error_limit:
        return {'status': 'unavailable', 'reason':
                'Held-out annual backtest error exceeds ' + str(round(100 * error_limit)) + '%',
                'backtest_error_pct': round(error * 100, 2), 'points': []}
    # Refit across the four *observed* annual readings only.
    rate, raw = _capped_growth(sample[0][1], sample[-1][1], 3, cap)
    latest = sample[-1]
    future = []
    for year in range(latest[0] + 1, through + 1):
        n = year - latest[0]
        scenario = latest[1] * (1 + rate)**n
        lower = latest[1] * max(0.01, 1 + rate - 0.02)**n
        upper = latest[1] * (1 + rate + 0.02)**n
        future.append({'year': year, 'value': round(scenario, 3),
                       'low': round(lower, 3), 'high': round(upper, 3),
                       'status': 'modelled'})
    return {'status': 'illustrative', 'base_year': latest[0],
            'base_value': round(latest[1], 3),
            'start_year': sample[0][0], 'start_value': round(sample[0][1], 3),
            'annual_rate': round(rate, 6), 'raw_annual_rate': round(raw, 6),
            'backtest_error_pct': round(error * 100, 2),
            'backtest_limit_pct': round(error_limit * 100, 0),
            'capped': abs(raw) > cap, 'max_rate': cap,
            'sensitivity_pp': 2, 'points': future,
            'method': 'Four recent consecutive annual readings; hold-out final year backtest, '
                      'then capped endpoint annualised growth with +/-2 percentage point '
                      'annual-rate sensitivity.'}


def generate(offline=False, today=None, oecd_fetch=None, pubmed_fetch=None, market_fetch=None):
    today=today or date.today()
    data=(oecd_fetch or oecd_imaging.fetch)(offline=offline)
    if not isinstance(data,dict) or 'countries' not in data:
        raise ValueError('OECD collector returned invalid MRI coverage')
    for code,country in data['countries'].items():
        if not isinstance(country,dict):
            raise ValueError('Invalid country record')
        for mode in ('equipment','exams'):
            series=country.get(mode,{}).get('series',{}).get('MRI',[])
            if not isinstance(series,list):
                raise ValueError('Invalid MRI time series')
            valid=[]
            for point in series:
                yr=point.get('year');value=point.get('value')
                if not isinstance(yr,int) or not 2015<=yr<=today.year or not isinstance(value,(int,float)) or isinstance(value,bool) or not 0<=value<100_000:
                    raise ValueError('Invalid MRI observation')
                valid.append((yr,float(value)))
            if len({year for year,_ in valid})!=len(valid):
                raise ValueError('Duplicate MRI observation years')
            country[mode]['projection'] = mri_trend_scenario(
                series, mode, through=2027
            )
    for region in REGIONAL_GROUPS.values():
        if any(code not in data['countries'] for code in region['countries']):
            raise ValueError('Regional MRI sample contains a country without OECD coverage')
    publication=(pubmed_fetch or pubmed_feed)(offline=offline,today=today)
    if not isinstance(publication,dict) or 'items' not in publication:
        raise ValueError('Invalid publication feed')
    market=(market_fetch or mri_market.refresh)(mri_market.read_reference(),offline=offline,today=today)
    mri_market.validate(market)
    return dict(schema_version=1,
                generated_at=datetime.now(timezone.utc).isoformat(),
                oecd=data,regional_groups=REGIONAL_GROUPS,pubmed=publication,market=market,
                purpose='MRI modality data and recent MRI research, not AI-sector commercial metrics')


def render(template,payload):
    marker='<!-- MRI_DATA -->'
    if template.count(marker)!=1:
        raise ValueError('MRI template must have exactly one source-backed data slot')
    if 'mri-overview' not in template or 'mri-papers' not in template:
        raise ValueError('MRI template missing required dashboard sections')
    return template.replace(marker,safe_json(payload))


def main():
    parser=argparse.ArgumentParser(description='Generate published MRI dashboard using public sources.')
    parser.add_argument('--template',type=Path,default=BASE_DIR/'mri.template.html')
    parser.add_argument('--output',type=Path,default=BASE_DIR/'mri.html')
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    payload=generate(offline=args.offline)
    template=args.template.read_text(encoding='utf-8')
    output=render(template,payload)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(output,encoding='utf-8')
    count=sum(len(c[k]['series'].get('MRI',[])) for c in payload['oecd']['countries'].values()
              for k in ('exams','equipment'))
    LOG.info('MRI page written: %s; OECD MRI observations=%d; PubMed %s',
             args.output,count,payload['pubmed']['status'])
    print('MRI market research: %d publisher estimates (%s); %d vendor-share categories (%s)' % (
          len(payload['market']['size']['entries']),payload['market']['size']['year'],
          len(payload['market']['shares']['entries']),payload['market']['shares']['publication_date']))
    print('MRI build: %d verified OECD annual MRI points; PubMed: %s (%s titles); data checked %s' %
          (count,payload['pubmed']['status'],len(payload['pubmed']['items']),
           payload['oecd'].get('checked') or 'not available'))


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    main()
