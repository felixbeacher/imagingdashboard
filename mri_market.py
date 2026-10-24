"""MR equipment market reference source checks, never fictional current sales."""
import copy
from datetime import date
from html import unescape
import json
import logging
from pathlib import Path
import re
from urllib.request import Request, urlopen

REFERENCE=Path(__file__).resolve().parent/'mri_market_reference.json'
LOG=logging.getLogger(__name__)

def validate(reference):
    if reference.get('schema_version')!=1:return False
    estimates=reference.get('size',{}).get('entries',[])
    share=reference.get('shares',{}).get('entries',[])
    if len(estimates)<2 or len(share)<4:
        raise ValueError('Incomplete MRI equipment market reference')
    for entry in estimates:
        if not (isinstance(entry['value'],(int,float)) and not isinstance(entry['value'],bool)
                and 0.1<entry['value']<100 and entry['source'].startswith('https://')
                and entry['publication_date'] and entry['match_phrase']):
            raise ValueError('MRI market source missing or implausible')
    if any(not isinstance(row['value'],(int,float)) or row['value']<0 for row in share) or abs(sum(x['value'] for x in share)-100)>0.00001:
        raise ValueError('MRI vendor share references must sum to 100%')
    if reference['shares']['reference_year']>date.today().year:
        raise ValueError('MRI share reference year in future')
    return True

def read_reference(path=REFERENCE):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    validate(data)
    return data

def _public_html(url):
    req=Request(url,headers={
        'User-Agent':'Medical Imaging Dashboard reference checker/1.0',
        'Accept':'text/html,application/xhtml+xml'
    })
    with urlopen(req,timeout=16) as response:
        if 'html' not in response.headers.get('Content-Type','').lower():
            raise ValueError('Source did not return HTML')
        b=response.read(2_000_001)
    if len(b)>2_000_000:raise ValueError('Source page exceeds limit')
    html=b.decode('utf-8','replace')
    html=re.sub(r'(?is)<(script|style|noscript)\b[^>]*>.*?</\1>',' ',html)
    return ' '.join(unescape(re.sub(r'(?s)<[^>]*>',' ',html)).split())

def refresh(reference,offline=False,today=None,fetcher=None):
    """Recheck quoted 2025 published figures; never silently reinterpret forecasts."""
    out=copy.deepcopy(reference)
    validate(out)
    out['checked_at']=(today or date.today()).isoformat()
    getter=fetcher or _public_html
    for entry in out['size']['entries']:
        if offline:
            entry['check_status']='offline · dated published reference'
            continue
        try:
            content=getter(entry['source']).casefold()
            exact=' '.join(entry['match_phrase'].casefold().split())
            if exact in content:
                entry['last_verified_at']=out['checked_at']
                entry['check_status']='published 2025 estimate reverified'
            else:
                # Keep the dated reference unchanged rather than guess at a new
                # market value from an unrelated forecast, CAGR or revenues.
                entry['check_status']='source reached; exact 2025 figure not reverified'
        except Exception as exc:
            LOG.info('MRI market publisher %s could not be rechecked (%s)',entry['publisher'],type(exc).__name__)
            entry['check_status']='source inaccessible · dated published reference'
    out['shares']['check_status']='historical 2022 vendor-share figure reproduced in 2024; not a live API'
    validate(out)
    return out
