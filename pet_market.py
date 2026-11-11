"""PET market-research estimate updater and verifier.

Re-checks the published Mordor Intelligence PET market page on weekly builds.
Dated reference values are retained with their original publication date if
verification is unavailable; forecasts are always labelled as projections.
"""
import copy
from datetime import date
from html import unescape
import json
import logging
from pathlib import Path
import re
from urllib.request import Request, urlopen

LOG = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent
REFERENCE = HERE / 'pet_market_reference.json'


def read_reference(path=REFERENCE):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    validate(data)
    return data


def validate(data):
    if data.get('schema_version') != 1:
        raise ValueError('Unsupported PET market evidence schema')
    if not str(data.get('source', '')).startswith('https://') or not data.get('publisher'):
        raise ValueError('Missing PET market source metadata')
    base = data['baseline']
    proj = data['projection']
    for key, obj in (('baseline', base), ('projection', proj)):
        if not isinstance(obj.get('year'), int) or obj['year'] < 2020:
            raise ValueError(f'Invalid PET {key} year')
        val = obj.get('value')
        if not isinstance(val, (int, float)) or isinstance(val, bool) or not 0.1 <= val <= 40:
            raise ValueError(f'Unreliable PET {key} market value')
    if proj['year'] <= base['year']:
        raise ValueError('PET projection year must follow baseline year')
    cagr = proj.get('cagr_pct')
    if not isinstance(cagr, (int, float)) or isinstance(cagr, bool) or not 0 <= cagr <= 40:
        raise ValueError('Unreliable PET CAGR estimate')
    return True


def _clean_html(markup):
    text = markup.decode('utf-8', 'replace')
    text = re.sub(r'(?is)<(script|style|noscript)\b[^>]*>.*?</\1>', ' ', text)
    return re.sub(r'\s+', ' ', unescape(re.sub(r'(?s)<[^>]*>', ' ', text))).strip()


def _fetch(url):
    req = Request(url, headers={
        'User-Agent': 'Medical Imaging Dashboard research source checker/1.0',
        'Accept': 'text/html,application/xhtml+xml',
    })
    with urlopen(req, timeout=17) as response:
        if not any(s in response.headers.get('Content-Type', '').lower() for s in ('html', 'text/plain')):
            raise ValueError('PET market source did not return HTML')
        body = response.read(2_500_001)
    if len(body) > 2_500_000:
        raise ValueError('PET market response exceeds size limit')
    return _clean_html(body)


def extract_mordor(content):
    """Extract snapshot base/projection values and CAGR when explicitly labelled."""
    snap_pairs = re.findall(
        r'Market Size\s*\(\s*(20\d{2})\s*\)\s*(?:USD|\$)\s*(\d+(?:\.\d+)?)\s*Billion',
        content, re.I,
    )
    cagr_match = re.search(
        r'Growth Rate\s*\(\s*20\d{2}\s*[-–]\s*20\d{2}\s*\)\s*(\d+(?:\.\d+)?)\s*%',
        content, re.I,
    )
    if len(snap_pairs) < 2 or not cagr_match:
        return None
    parsed = sorted((int(y), float(v)) for y, v in snap_pairs[:2])
    (base_yr, base_val), (proj_yr, proj_val) = parsed
    cagr = float(cagr_match.group(1))
    if not (2024 <= base_yr <= 2030 and proj_yr > base_yr and 0.5 <= base_val <= 20 and 0.5 <= proj_val <= 30 and 0 <= cagr <= 30):
        return None
    return {
        'baseline_year': base_yr,
        'baseline_value': base_val,
        'projection_year': proj_yr,
        'projection_value': proj_val,
        'cagr_pct': cagr,
    }


def refresh(reference, offline=False, today=None, fetcher=None):
    result = copy.deepcopy(reference)
    validate(result)
    today = today or date.today()
    checked = today.isoformat()
    result['checked_at'] = checked
    if offline:
        result['check_status'] = 'offline · using dated published reference'
        return result
    checker = fetcher or _fetch
    try:
        content = checker(result['source'])
        extracted = extract_mordor(content)
        if extracted:
            result['baseline']['year'] = extracted['baseline_year']
            result['baseline']['value'] = extracted['baseline_value']
            result['baseline']['label'] = f"{extracted['baseline_year']} estimate"
            result['projection']['year'] = extracted['projection_year']
            result['projection']['value'] = extracted['projection_value']
            result['projection']['cagr_pct'] = extracted['cagr_pct']
            result['last_verified_at'] = checked
            result['check_status'] = 'source figure reverified'
        else:
            result['check_status'] = 'source reachable; target figures not reverified'
    except Exception as exc:
        LOG.info('PET market estimate could not be checked: %s', type(exc).__name__)
        result['check_status'] = 'site not accessible · using dated published reference'
    validate(result)
    return result
