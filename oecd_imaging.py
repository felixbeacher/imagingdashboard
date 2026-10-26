"""Live OECD country time-series for diagnostic exams and imaging equipment.

Exams: total-provider observations (_T) where available; otherwise hospital
provider (HP1). The chosen scope is always disclosed for the entire country.
Equipment: all providers (_T), units per million inhabitants. Never fill years.
"""
import csv
import io
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.request import Request, urlopen

COUNTRIES = {
    'CHE': 'Switzerland',
    'GBR': 'United Kingdom',
    'USA': 'United States',
    'DEU': 'Germany',
    'FRA': 'France',
    'CAN': 'Canada',
    'AUS': 'Australia',
    'JPN': 'Japan',
}
MODALITIES = {'CT_SCAN': 'CT', 'MRI': 'MRI', 'PET_SCAN': 'PET'}
BASE = 'https://sdmx.oecd.org/public/rest/v1/data/'
COUNTRY_KEY = '+'.join(COUNTRIES)
EXAMS_ENDPOINT = (BASE + 'OECD.ELS.HD,DSD_HEALTH_PROC@DF_DIAG_EXAM,/'
                  + COUNTRY_KEY + '..EXM_10P3PS...............?startPeriod=2015')
EQUIPMENT_ENDPOINT = (BASE + 'OECD.ELS.HD,DSD_HEALTH_REAC_HOSP@DF_MED_TECH,/'
                      + COUNTRY_KEY + '..10P6HB......_T?startPeriod=2015')
SOURCE_URLS = {
    'exams': 'https://data-explorer.oecd.org/vis?df%5Bag%5D=OECD.ELS.HD&df%5Bid%5D=DSD_HEALTH_PROC%40DF_DIAG_EXAM',
    'equipment': 'https://data-explorer.oecd.org/vis?df%5Bag%5D=OECD.ELS.HD&df%5Bid%5D=DSD_HEALTH_REAC_HOSP%40DF_MED_TECH',
}

def provider_scope(country, mode, provider):
    """Retain national exclusions even when the SDMX provider code is total.

    Coverage notes: OECD Health at a Glance 2025, diagnostic technologies.
    These describe reporting coverage, not an estimate of unreported activity.
    """
    if provider is None:
        return None
    if country == 'GBR':
        return ('Public-hospital equipment only (OECD UK coverage)' if mode == 'equipment'
                else 'Hospitals only (OECD UK coverage; excludes examinations outside hospital)')
    if country == 'AUS':
        return ('Equipment eligible for public reimbursement only' if mode == 'equipment'
                else 'Medicare-paid fee-for-service examinations only')
    return ('All healthcare providers' if provider == '_T'
            else 'Hospitals only (not all examinations)')

def _empty():
    return {
        'source': 'OECD Health Statistics / OECD Data Explorer',
        'checked': None,
        'countries': {
            code: {
                'name': name,
                'exams': {'status': 'unavailable', 'scope': None, 'series': {k: [] for k in MODALITIES.values()}},
                'equipment': {'status': 'unavailable', 'scope': 'All healthcare settings',
                              'series': {k: [] for k in MODALITIES.values()}},
            } for code, name in COUNTRIES.items()
        },
        'sources': SOURCE_URLS.copy(),
        'note': ('Examination counts and scanner availability have different denominators and provider coverage. '
                 'Do not divide one by the other or infer unmet need without local evidence.'),
    }

def _request_csv(url):
    req = Request(url, headers={'Accept': 'text/csv', 'User-Agent': 'Medical Imaging Dashboard data researcher/1.0'})
    with urlopen(req, timeout=35) as response:
        content_type = response.headers.get('Content-Type', '').lower()
        if 'csv' not in content_type:
            raise ValueError('OECD did not return CSV')
        payload = response.read(8_000_001)
    if len(payload) > 8_000_000:
        raise ValueError('OECD data exceeds size limit')
    rows = list(csv.DictReader(io.StringIO(payload.decode('utf-8-sig'))))
    if not rows:
        raise ValueError('OECD feed has no observations')
    return rows

def parse_rows(rows, mode):
    """Strictly filter units, definitions, and codes before exposing chart data."""
    exams = mode == 'exams'
    required = {'REF_AREA','MEASURE','UNIT_MEASURE','TIME_PERIOD','OBS_VALUE',
                'HEALTH_FACILITY','PROVIDER'} if exams else {
                    'REF_AREA','MEASURE','UNIT_MEASURE','TIME_PERIOD','OBS_VALUE',
                    'MEDICAL_TECH','HEALTH_CARE_PROVIDER'}
    if not rows or not required.issubset(rows[0]):
        raise ValueError('OECD columns changed')
    chosen = {}
    for row in rows:
        country = row['REF_AREA']
        modality = row['HEALTH_FACILITY'] if exams else row['MEDICAL_TECH']
        provider = row['PROVIDER'] if exams else row['HEALTH_CARE_PROVIDER']
        if country not in COUNTRIES or modality not in MODALITIES:
            continue
        if row['MEASURE'] != ('EXAM' if exams else 'MTU'):
            continue
        if row['UNIT_MEASURE'] != ('EXM_10P3PS' if exams else '10P6HB'):
            continue
        if provider not in (('_T','HP1') if exams else ('_T',)):
            continue
        year_string = row['TIME_PERIOD']
        if len(year_string) != 4 or not year_string.isdecimal():
            continue
        year = int(year_string)
        if year < 2015 or year > date.today().year:
            continue
        raw_value = row['OBS_VALUE']
        if not raw_value or row.get('OBS_STATUS') == 'M':
            continue
        try:
            value = float(raw_value)
        except (ValueError, TypeError):
            continue
        if not math.isfinite(value) or value < 0 or value > 1_000_000:
            raise ValueError('Invalid OECD metric value')
        if row.get('UNIT_MULT') not in ('',None,'0'):
            raise ValueError('Unexpected OECD unit multiplier')
        key = (country, provider, MODALITIES[modality], year)
        if key in chosen and chosen[key] != value:
            raise ValueError('Conflicting OECD observations')
        chosen[key] = value
    return chosen

def fetch(offline=False):
    output = _empty()
    if offline:
        return output
    def collect(mode, endpoint):
        try:
            return parse_rows(_request_csv(endpoint), mode), None
        except Exception as exc:
            logging.warning('OECD %s unavailable (%s)', mode, type(exc).__name__)
            return {}, type(exc).__name__
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(collect, 'exams', EXAMS_ENDPOINT)
        b = pool.submit(collect, 'equipment', EQUIPMENT_ENDPOINT)
        exam_points, exam_error = a.result()
        equipment_points, equipment_error = b.result()
    output['checked'] = date.today().isoformat()
    for country, data in output['countries'].items():
        for mode, points, error in [('exams',exam_points,exam_error),('equipment',equipment_points,equipment_error)]:
            # Use a single provider definition for every modality within a country.
            # Prefer all-provider totals, otherwise explicitly show hospital-only exams.
            providers = ['_T'] if mode == 'equipment' else ['_T', 'HP1']
            if mode == 'exams':
                selected = next((p for p in providers
                    if sum(1 for key in points if key[0] == country and key[1] == p) >= 2), None)
            else:
                selected = '_T'
            scope = provider_scope(country, mode, selected)
            series = {}
            for modality in MODALITIES.values():
                series[modality] = [
                    {'year': year, 'value': round(value, 3)}
                    for (area, provider, code, year), value in sorted(points.items(), key=lambda pair: pair[0][-1])
                    if area == country and provider == selected and code == modality
                ]
            available = any(series.values())
            data[mode] = {
                'scope': scope,
                'status': 'available' if available else 'unavailable',
                'series': series,
                'reason': ('OECD endpoint unavailable (' + error + ')' if error else
                           'No comparable published country observations') if not available else '',
            }
    return output
