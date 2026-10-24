"""Source-backed CT modality page generator.

The data pipeline deliberately distinguishes:
* OECD annual equipment and CT-exam observations (not sales or patient need).
* Recent PubMed CT research discovery (not systematic evidence synthesis).
* Derived, source-dated analysis performed in the browser on selected annual values.

No imaginary world averages, vendor shares, CT forecasts or historical interpolation.
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
import ct_market

LOG = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
CT_QUERY = ('("computed tomography"[Title] OR "CT angiography"[Title] OR '
            '"photon-counting CT"[Title] OR "spectral CT"[Title] OR "coronary CT"[Title]) '
            'NOT (review[Publication Type] OR meta-analysis[Publication Type] '
            'OR protocol[Title] OR photoacoustic[Title] OR "electron tomography"[Title] '
            'OR "optical coherence tomography"[Title])')
DOI_RE = re.compile(r'^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$')


def safe_json(obj):
    return (json.dumps(obj, ensure_ascii=False, allow_nan=False)
            .replace('<', '\\u003c').replace('>', '\\u003e')
            .replace('&', '\\u0026').replace('\u2028', '\\u2028')
            .replace('\u2029', '\\u2029'))


def _read(url, max_bytes=1_800_000, timeout=23):
    req = Request(url, headers={
        'User-Agent': 'MedicalImagingDashboard/1.0 (public CT research indexing)',
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
    if 'photon-count' in low:return 'Photon-counting CT'
    if 'spectral' in low or 'dual-energy' in low:return 'Spectral CT'
    if 'coronary' in low or 'cardiac' in low:return 'Cardiac CT'
    if 'angio' in low:return 'CT angiography'
    if 'dose' in low or 'radiation' in low:return 'Dose and optimisation'
    return 'CT clinical / technical study'


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
        if not re.search(r'computed tomography|CT angiograph|photon.counting CT|spectral CT|coronary CT',title,re.I):
            continue
        if re.search(r'\b(?:review|meta-analysis|protocol|photoacoustic)\b|electron tomography|optical coherence tomography',title,re.I):
            continue
        journal=_text(art.find('.//Journal/Title')) or 'Journal not supplied'
        types=[_text(t) for t in art.findall('.//PublicationType') if _text(t)]
        design=next((t for t in types if t in (
            'Randomized Controlled Trial','Clinical Trial','Observational Study',
            'Multicenter Study','Comparative Study')), None)
        sections=art.findall('.//Abstract/AbstractText')
        results=next((a for a in sections if a.get('NlmCategory') == 'RESULTS'
                      or a.get('Label','').upper()=='RESULTS'),None)
        words=_text(results).split() if results is not None else []
        excerpt=' '.join(words[:18])+('…' if len(words)>18 else '')
        result.append(dict(
            title=title[:330],url='https://pubmed.ncbi.nlm.nih.gov/'+pmid+'/',
            journal=journal[:160],date=_date(art),kind=_kind(title),
            design=design or 'Study design not verified by this feed',
            excerpt=excerpt,
        ))
    result.sort(key=lambda paper: (paper['date'] if re.fullmatch(r'\d{4}-\d{2}-\d{2}',paper['date']) else paper['date'][:4]+'-00-00',paper['title']), reverse=True)
    return result[:limit]


def pubmed_feed(offline=False, today=None):
    today=today or date.today()
    out=dict(status='unavailable',checked=today.isoformat(),count=None,
             items=[],query=CT_QUERY,window='past 365 days',error='PubMed retrieval unavailable')
    if offline:
        out['error']='Offline mode; no PubMed search performed'
        return out
    try:
        search_url=PUBMED_BASE+'esearch.fcgi?'+urlencode({
            'db':'pubmed','term':CT_QUERY,'sort':'pub date','retmode':'json',
            'retmax':24,'reldate':365,'datetype':'pdat',
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
        LOG.warning('CT PubMed source unavailable: %s',type(exc).__name__)
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


def ct_trend_scenario(points, mode, through=2027):
    """Illustrative trend extension from recent, dated OECD observations.

    Based on the latest three actual annual points. Geometric annualised
    endpoint growth is capped at +/-5% (scanners) or +/-8% (examinations).
    Widening +/-2 percentage-point yearly sensitivity is NOT a confidence band.
    """
    if mode not in ('equipment', 'exams'):
        raise ValueError('Unsupported CT trend kind')
    clean=sorted((p['year'],float(p['value'])) for p in points)
    if len(clean)<3 or len({y for y,_ in clean})!=len(clean):
        return {'status':'unavailable','reason':'At least three distinct annual OECD observations are required','points':[]}
    sample=clean[-3:]
    first,last=sample[0],sample[-1]
    elapsed=last[0]-first[0]
    if (elapsed<2 or elapsed>6 or last[0]<through-4 or
            first[1]<=0 or last[1]<=0):
        return {'status':'unavailable','reason':'Recent, positive and sufficiently close observations are required','points':[]}
    raw=(last[1]/first[1])**(1/elapsed)-1
    cap=0.05 if mode=='equipment' else 0.08
    trend=max(-cap,min(cap,raw))
    future=[]
    for year in range(last[0]+1,through+1):
        elapsed_from_latest=year-last[0]
        middle=last[1]*(1+trend)**elapsed_from_latest
        lower=last[1]*max(.01,1+trend-.02)**elapsed_from_latest
        upper=last[1]*(1+trend+.02)**elapsed_from_latest
        future.append({'year':year,'value':round(middle,3),
                       'low':round(lower,3),'high':round(upper,3),
                       'status':'modelled'})
    return {'status':'illustrative','base_year':last[0],'base_value':round(last[1],3),
            'start_year':first[0],'start_value':round(first[1],3),
            'raw_annual_rate':round(raw,6),'annual_rate':round(trend,6),
            'capped':abs(raw)>cap,'max_rate':cap,'sensitivity_pp':2,
            'points':future,
            'method':'Latest three annual actual observations; annualised endpoint growth with transparent cap and +/-2 percentage-point sensitivity.'}


def generate(offline=False, today=None, oecd_fetch=None, pubmed_fetch=None, market_fetch=None):
    today=today or date.today()
    data=(oecd_fetch or oecd_imaging.fetch)(offline=offline)
    if not isinstance(data,dict) or 'countries' not in data:
        raise ValueError('OECD collector returned invalid CT coverage')
    for code,country in data['countries'].items():
        if not isinstance(country,dict):
            raise ValueError('Invalid country record')
        for mode in ('equipment','exams'):
            series=country.get(mode,{}).get('series',{}).get('CT',[])
            if not isinstance(series,list):
                raise ValueError('Invalid CT time series')
            valid=[]
            for point in series:
                yr=point.get('year');value=point.get('value')
                if not isinstance(yr,int) or not 2015<=yr<=today.year or not isinstance(value,(int,float)) or isinstance(value,bool) or not 0<=value<100_000:
                    raise ValueError('Invalid CT observation')
                valid.append((yr,float(value)))
            if len({year for year,_ in valid})!=len(valid):
                raise ValueError('Duplicate CT observation years')
            country[mode]['projection'] = ct_trend_scenario(
                series, mode, through=2027
            )
    for region in REGIONAL_GROUPS.values():
        if any(code not in data['countries'] for code in region['countries']):
            raise ValueError('Regional CT sample contains a country without OECD coverage')
    publication=(pubmed_fetch or pubmed_feed)(offline=offline,today=today)
    if not isinstance(publication,dict) or 'items' not in publication:
        raise ValueError('Invalid publication feed')
    market=(market_fetch or ct_market.refresh)(ct_market.read_reference(),offline=offline,today=today)
    ct_market.validate(market)
    return dict(schema_version=1,
                generated_at=datetime.now(timezone.utc).isoformat(),
                oecd=data,regional_groups=REGIONAL_GROUPS,pubmed=publication,market=market,
                purpose='CT modality data and recent CT research, not AI-sector commercial metrics')


def render(template,payload):
    marker='<!-- CT_DATA -->'
    if template.count(marker)!=1:
        raise ValueError('CT template must have exactly one source-backed data slot')
    if 'ct-overview' not in template or 'ct-papers' not in template:
        raise ValueError('CT template missing required dashboard sections')
    return template.replace(marker,safe_json(payload))


def main():
    parser=argparse.ArgumentParser(description='Generate published CT dashboard using public sources.')
    parser.add_argument('--template',type=Path,default=BASE_DIR/'ct.template.html')
    parser.add_argument('--output',type=Path,default=BASE_DIR/'ct.html')
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    payload=generate(offline=args.offline)
    template=args.template.read_text(encoding='utf-8')
    output=render(template,payload)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(output,encoding='utf-8')
    count=sum(len(c[k]['series'].get('CT',[])) for c in payload['oecd']['countries'].values()
              for k in ('exams','equipment'))
    LOG.info('CT page written: %s; OECD CT observations=%d; PubMed %s',
             args.output,count,payload['pubmed']['status'])
    print('CT market research: %d publisher estimates (%s); %d vendor-share categories (%s)' % (
          len(payload['market']['size']['entries']),payload['market']['size']['year'],
          len(payload['market']['shares']['entries']),payload['market']['shares']['publication_date']))
    print('CT build: %d verified OECD annual CT points; PubMed: %s (%s titles); data checked %s' %
          (count,payload['pubmed']['status'],len(payload['pubmed']['items']),
           payload['oecd'].get('checked') or 'not available'))


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    main()
