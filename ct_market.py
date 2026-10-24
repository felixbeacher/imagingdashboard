"""CT market-research estimate updater.

Commercial research pages are checked at scheduled rebuild. Published facts are
retained with their original publisher/date if verification is blocked. Raw
research-estimate observations are NOT confused with official OECD series or
directly measured equipment revenue.

Vendor share source is a dated DBS publication, not a recurring public API.
"""
import copy
from datetime import date
from html import unescape
import logging
from pathlib import Path
import re
from urllib.request import Request, urlopen
import json

LOG=logging.getLogger(__name__)
HERE=Path(__file__).resolve().parent
REFERENCE=HERE/'ct_market_reference.json'

def read_reference(path=REFERENCE):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    validate(data)
    return data

def validate(data):
    if data.get('schema_version')!=1:
        raise ValueError('Unsupported CT market evidence schema')
    size=data['size']
    entries=size['entries']
    if size['year']<2020 or len(entries)<2:
        raise ValueError('Incomplete CT market estimates')
    for item in entries:
        if (not isinstance(item['value'],(int,float)) or isinstance(item['value'],bool)
            or not 0.1<=item['value']<=40 or not item['source'].startswith('https://')
            or not item['publisher'] or not item.get('publication_date')):
            raise ValueError('Unreliable CT market size estimate')
    shares=data['shares']['entries']
    if not shares or any(not isinstance(item['value'],(int,float)) or item['value']<0 or item['value']>100 for item in shares):
        raise ValueError('Unreliable CT vendor share')
    if round(sum(x['value'] for x in shares),5)!=100:
        raise ValueError('CT vendor share series must total 100%')
    if not data['shares']['source'].startswith('https://'):
        raise ValueError('Missing DBS source')
    return True

def _clean_html(markup):
    html=markup.decode('utf-8','replace')
    html=re.sub(r'(?is)<(script|style|noscript)\b[^>]*>.*?</\1>', ' ',html)
    return re.sub(r'\s+',' ',unescape(re.sub(r'(?s)<[^>]*>', ' ',html))).strip()

def _fetch(url):
    req=Request(url,headers={'User-Agent':'Medical Imaging Dashboard research source checker/1.0','Accept':'text/html,application/xhtml+xml'})
    with urlopen(req,timeout=17) as response:
        if not any(s in response.headers.get('Content-Type','').lower() for s in ['html','text/plain']):
            raise ValueError('Market source did not return an HTML page')
        body=response.read(2_000_001)
        if len(body)>2_000_000:raise ValueError('Market page response exceeds limit')
    return _clean_html(body)

def _near_2025_market_price(content,original,year):
    # Extract amounts only from a sentence directly describing the 2025 market
    # and only when anchored to explicit market size wording. Never scrape an
    # unrelated forecast or company revenue.
    patterns=(
        r'(?:global.{0,90})?(?:computed tomography|CT scanners?|CT scanner).{0,95}?'
        r'(?:market size (?:was )?(?:valued at|reached|has reached to)|market was valued at)'
        r'.{0,28}?(?:USD|\$)\s*(\d{1,2}(?:\.\d{1,3})?)\s*billion.{0,32}?'
        +str(year),
        r'(?:computed tomography|CT scanners?).{0,100}?(?:market size|market).{0,65}?'
        r'(?:valued at|reached|has reached to).{0,28}?(?:USD|\$)\s*'
        r'(\d{1,2}(?:\.\d{1,3})?)\s*billion.{0,32}?'+str(year),
    )
    for p in patterns:
        for match in re.finditer(p,content,re.I):
            observed=float(match.group(1))
            if 0.5<=observed<=25 and .6*original<=observed<=1.6*original:
                return observed
    # Allow the exact vetted source statement, extracted as flattened text.
    raw_phrase=re.sub(r'\s+',' ',original and '' or '')
    return None

def refresh(reference,offline=False,today=None,fetcher=None):
    """Attempt to refresh publisher-provided comparable 2025 reference figures.

    Values remain explicitly dated source claims if retrieval is unavailable;
    do not replace them with zero, a guessed update, or a projection.
    """
    result=copy.deepcopy(reference)
    validate(result)
    today=today or date.today()
    checked=today.isoformat()
    result['checked_at']=checked
    checker=fetcher or _fetch
    if offline:
        for entry in result['size']['entries']:
            entry['check_status']='offline · using dated published reference'
        result['shares']['check_status']='published August 2025 reference · not a live API'
        return result
    for entry in result['size']['entries']:
        try:
            content=checker(entry['source'])
            value=_near_2025_market_price(content,entry['value'],result['size']['year'])
            if value is None:
                entry['check_status']='source reachable; target-year figure not reverified'
            else:
                entry['value']=value
                entry['last_verified_at']=checked
                entry['check_status']='source figure reverified'
        except Exception as exc:
            LOG.info('CT market estimate could not be checked: %s (%s)',entry['publisher'],type(exc).__name__)
            entry['check_status']='site not accessible · using dated published reference'
    # DBS vendor-share figures come from a fixed, published August 2025 PDF.
    # No invented time-series or spurious 2026 update is created.
    result['shares']['check_status']='DBS August 2025 published reference · no public live share API'
    validate(result)
    return result
