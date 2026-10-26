"""Bounded, public production EUDAMED device-register sample (not approval counts)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import html
import json
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

API = 'https://api.datalake.sante.service.ec.europa.eu/eudamed/'
PUBLIC = 'https://ec.europa.eu/tools/eudamed/'
GUIDE = 'https://webgate.ec.europa.eu/eudamed-help/en/files/Public%20API%20-%20user%20guide.pdf'
TERMS = ('qXR', 'qER', 'Lunit INSIGHT CXR', 'SubtleMR', 'BriefCase')
REFERENCE_CODES = ('APPLICABLE_LEGISLATION_ID', 'RISK_CLASS_ID', 'DEVICE_STATUS_TYPE_ID', 'STATUS_ID')
SNAPSHOT = Path(__file__).with_name('eudamed_snapshot.json')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def query_url(endpoint, params):
    return API + endpoint + '?' + urlencode({**params, 'format': 'json', 'api-version': 'v1.0'})


def read_json(url):
    request = Request(url, headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                                   'User-Agent': 'MedicalImagingDashboard/1.0 (EUDAMED public register) '})
    with urlopen(request, timeout=16) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError('Response exceeds the bounded sample size')
    data = json.loads(body)
    if not isinstance(data, dict) or not isinstance(data.get('value'), list):
        raise ValueError('Unexpected EUDAMED response; no count inferred')
    if data.get('nextLink'):
        raise ValueError('Sample response is paginated; no complete result inferred')
    return data['value']


def reference_key(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(int(value))
    return str(value or '')


def normalise(rows, term, references, url, retrieved):
    result = []
    for row in rows:
        # A filter that is ignored or changed by the upstream API must not inflate our sample.
        if str(row.get('TRADE_NAME', '')).strip().casefold() != term.casefold():
            raise ValueError('Source returned a record outside the exact trade-name query')
        identifier = row.get('PRIMARY_DI')
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError('Device record has no valid UDI-DI')
        def label(code):
            value = row.get(code)
            return references.get(code, {}).get(reference_key(value), 'Not supplied' if value is None else 'Source code ' + reference_key(value))
        result.append(dict(trade_name=term, manufacturer=str(row.get('MF_NAME') or 'Not supplied'),
                           udi_di=identifier, basic_udi=str(row.get('BASIC_UDI') or 'Not supplied'),
                           reference=str(row.get('REFERENCE') or 'Not supplied'),
                           legislation=label('APPLICABLE_LEGISLATION_ID'), risk_class=label('RISK_CLASS_ID'),
                           market_status=label('DEVICE_STATUS_TYPE_ID'), record_status=label('STATUS_ID'),
                           source_url=url, retrieved_at=retrieved))
    return result


def collect(offline=False, fetch=None, cached_path=SNAPSHOT):
    fetch = fetch or read_json
    try:
        cached = json.loads(Path(cached_path).read_text())
    except (OSError, ValueError):
        cached = {}
    now = stamp()
    if offline:
        return dict(cached, status='cached' if cached.get('items') else 'unavailable',
                    attempted_at=now, reason='Offline build; any displayed records retain their original retrieval dates.')
    tasks = [('reference', code, query_url('reference', {'CODE': code, 'LANGUAGE': 'en'})) for code in REFERENCE_CODES]
    tasks += [('device', term, query_url('udi', {'TRADE_NAME': term})) for term in TERMS]
    def run(task):
        kind, name, url = task
        try:
            return kind, name, url, fetch(url), None
        except Exception as error:
            return kind, name, url, [], type(error).__name__ + ': ' + str(error)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(run, tasks))
    references = {}
    for kind, name, url, rows, error in responses:
        if kind == 'reference' and not error:
            references[name] = {reference_key(row.get('ID')): str(row['VALUE']) for row in rows
                                if row.get('CODE') == name and row.get('LANGUAGE') == 'en' and row.get('VALUE')}
    items, searches = [], []
    errors = [name + ': ' + error for kind, name, url, rows, error in responses if kind == 'reference' and error]
    for kind, name, url, rows, error in responses:
        if kind != 'device':
            continue
        if not error:
            try:
                items.extend(normalise(rows, name, references, url, now))
            except ValueError as failure:
                error = str(failure)
        if error:
            errors.append(name + ': ' + error)
            # Only reuse records from this precise query, preserving their source dates.
            items.extend(item for item in cached.get('items', []) if item.get('trade_name') == name)
        searches.append(dict(term=name, source_url=url, status='unavailable' if error else 'retrieved',
                             records=None if error else len(rows), checked_at=now, reason=error or ''))
    unique = {item['udi_di']: item for item in items}
    return dict(status='partial' if errors else 'live', attempted_at=now, items=list(unique.values()),
                searches=searches, errors=errors,
                reason='Selected exact-name device registrations; not an EU approval total or a comprehensive imaging-AI register.')


def render(data):
    esc = lambda value: html.escape(str(value), quote=True)
    data = data or {}
    items = data.get('items', [])
    status = data.get('status', 'unavailable')
    out = ['<section class="card col-12" id="eu-regulatory-section" aria-labelledby="eu-regulatory-title">',
           '<h2 id="eu-regulatory-title">European Union · EUDAMED device registrations</h2>',
           '<p class="ai-section-intro">European device-register records are shown separately from US FDA authorisations. EUDAMED registration is not an approval decision or evidence of clinical benefit. CE conformity assessment and, where applicable, notified-body certification must be checked separately.</p>',
           '<p class="metric-desc">This selected imaging-AI watchlist uses exact product-name searches, not a complete census. One product can have several device identifiers; record counts are not product or approval counts. No match does not establish that a product lacks CE marking.</p>']
    if items:
        out.append('<p class="metric-desc">' + str(len(items)) + ' device-identifier records displayed · collection status: ' + esc('retrieved successfully' if status == 'live' else status) + ' · collection attempted ' + esc(data.get('attempted_at', 'date unavailable')[:10]) + '.</p><div class="ai-study-list">')
        for term in dict.fromkeys(item['trade_name'] for item in items):
            group = [item for item in items if item['trade_name'] == term]
            item = group[0]
            out.append('<article class="ai-study"><h3>' + esc(term) + '</h3><p class="metric-desc">Manufacturer: ' + esc(item['manufacturer']) + '</p>')
            for field, title in [('legislation', 'Legislation'), ('risk_class', 'Risk class'), ('market_status', 'Registered market status'), ('record_status', 'Register status')]:
                values = '; '.join(dict.fromkeys(row[field] for row in group))
                out.append('<p class="metric-desc">' + title + ': ' + esc(values) + '</p>')
            out.append('<details><summary>Device identifiers and source dates</summary><ul style="padding-left:20px">')
            for row in group:
                out.append('<li>UDI-DI: ' + esc(row['udi_di']) + ' · Reference: ' + esc(row['reference']) + ' · Retrieved: ' + esc(row['retrieved_at'][:10]) + '</li>')
            out.append('</ul></details><p class="metric-desc"><a target="_blank" rel="noopener noreferrer" href="' + esc(item['source_url']) + '">Original EUDAMED API records →</a></p></article>')
        out.append('</div>')
    else:
        message = ('No records matched the selected product names in this retrieval. This is not a count of all EU devices.' if status == 'live' else 'Device-register retrieval unavailable. No EU count is inferred and FDA figures are not substituted.')
        out.append('<p class="metric-desc">' + message + '</p>')
    out.append('<p class="metric-desc">Certificate numbers, certificate validity and approval dates are not provided by this device-data extract. The registered market status is a source field, not an independent verification of certification. Retrieval dates are not authorisation dates.</p>')
    out.append('<details style="margin-top:16px"><summary>Watchlist searches and collection status</summary><ul style="padding-left:20px">')
    for search in data.get('searches', []):
        out.append('<li>' + esc(search['term']) + ': ' + ('retrieval unavailable' if search['records'] is None else str(search['records']) + ' matching records') + ' · checked ' + esc(search['checked_at'][:10]) + '</li>')
    out.append('</ul><p class="metric-desc">' + esc(data.get('reason', 'No verified device sample available.')) + '</p></details>')
    out.append('<p class="metric-desc" style="margin-top:16px"><a href="' + PUBLIC + '" target="_blank" rel="noopener noreferrer">Search EUDAMED devices and certificates →</a> · <a href="' + GUIDE + '" target="_blank" rel="noopener noreferrer">Commission public API guide →</a></p></section>')
    return ''.join(out)
