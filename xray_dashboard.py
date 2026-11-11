"""Source-backed X-ray modality page generator.

Refreshes live radiography research from PubMed, verifies the Grand View
Research X-ray systems market estimate, and checks NHS England's Diagnostic
Imaging Dataset (DID) landing page for newly finalised annual releases.
Unavailable sources remain clearly labelled; no figures are fabricated.
"""
import argparse
from datetime import date, datetime, timezone
from html import unescape
import json
import logging
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

LOG = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
PUBMED_BASE = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
NHS_DID_URL = 'https://www.england.nhs.uk/statistics/statistical-work-areas/diagnostic-imaging-dataset/'
GVR_URL = 'https://www.grandviewresearch.com/industry-analysis/x-ray-systems-market'

XRAY_QUERY = (
    '("chest radiograph"[Title] OR "chest x-ray"[Title] OR '
    '"plain radiography"[Title] OR "digital radiography"[Title] OR '
    '"chest radiography"[Title]) '
    'NOT (review[Publication Type] OR meta-analysis[Publication Type] '
    'OR protocol[Title] OR "computed tomography"[Title] '
    'OR "magnetic resonance"[Title] OR "case report"[Title])'
)

XRAY_RESEARCH_CATEGORIES = (
    ('AI / workflow triage', r'artificial intelligence|\bai\b|deep learning|machine learning|prioriti[sz]ation|triage|automated'),
    ('Chest / lung radiography', r'chest|pulmonary|lung|tuberculosis|pneumonia|thorax'),
    ('Musculoskeletal / trauma', r'fracture|bone|joint|orthop|spine|trauma|extremity'),
    ('Dose / image quality', r'dose|radiation|detector|dual[- ]energy|exposure|quality'),
)


def safe_json(obj):
    return (
        json.dumps(obj, ensure_ascii=False, allow_nan=False)
        .replace('<', '\\u003c')
        .replace('>', '\\u003e')
        .replace('&', '\\u0026')
        .replace('\u2028', '\\u2028')
        .replace('\u2029', '\\u2029')
    )


def _read(url, max_bytes=2_000_000, timeout=22):
    req = Request(url, headers={
        'User-Agent': 'MedicalImagingDashboard/1.0 (public X-ray research indexing)',
        'Accept': 'application/json, application/xml, text/xml, text/html, */*',
    })
    with urlopen(req, timeout=timeout) as reply:
        content = reply.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError('Source response exceeds bound')
    return content


def _clean_html(markup):
    text = markup.decode('utf-8', 'replace')
    text = re.sub(r'(?is)<(script|style|noscript)\b[^>]*>.*?</\1>', ' ', text)
    return re.sub(r'\s+', ' ', unescape(re.sub(r'(?s)<[^>]*>', ' ', text))).strip()


def _text(node):
    return ' '.join(''.join(node.itertext()).split()) if node is not None else ''


def _date(article):
    for x in article.findall('.//ArticleDate'):
        y = x.findtext('Year')
        m = x.findtext('Month')
        d = x.findtext('Day')
        if y and m and d and y.isdecimal() and m.isdecimal() and d.isdecimal():
            try:
                return date(int(y), int(m), int(d)).isoformat()
            except ValueError:
                pass
    d = article.find('.//PubMedPubDate[@PubStatus="pubmed"]')
    if d is not None:
        y = d.findtext('Year')
        m = d.findtext('Month')
        day = d.findtext('Day')
        if y and m and day and all(t.isdecimal() for t in (y, m, day)):
            try:
                return date(int(y), int(m), int(day)).isoformat()
            except ValueError:
                pass
    y = article.findtext('.//PubDate/Year')
    if y and y.isdecimal():
        return y
    return 'Date not supplied'


def _priority(title, journal, types, has_results):
    title_low = title.casefold()
    journal_low = journal.casefold()
    category = next(
        (name for name, pattern in XRAY_RESEARCH_CATEGORIES if re.search(pattern, title_low)),
        'X-ray clinical / technical study',
    )
    if 'Randomized Controlled Trial' in types:
        design_points = 12
    elif 'Clinical Trial' in types:
        design_points = 9
    elif any(t in types for t in ('Validation Study', 'Multicenter Study', 'Comparative Study', 'Observational Study')):
        design_points = 6
    else:
        design_points = 0
    specialist = any(k in journal_low for k in ('radiology', 'roentgen', 'imaging', 'radiograph'))
    return category, design_points + (4 if specialist else 0) + (2 if has_results else 0)


def parse_pubmed(xml_bytes, expected_ids, limit=8):
    root = ET.fromstring(xml_bytes)
    if root.tag != 'PubmedArticleSet':
        raise ValueError('Invalid PubMed response')
    expected = set(expected_ids)
    result = []
    for art in root.findall('PubmedArticle'):
        pmid = _text(art.find('./MedlineCitation/PMID'))
        title = _text(art.find('.//ArticleTitle'))
        if not pmid.isdecimal() or pmid not in expected or not title:
            continue
        if not re.search(r'radiograph|x-?ray', title, re.I):
            continue
        if re.search(r'\b(?:review|meta-analysis|protocol)\b|computed tomography|magnetic resonance', title, re.I):
            continue
        journal = _text(art.find('.//Journal/Title')) or 'Journal not supplied'
        types = [_text(t) for t in art.findall('.//PublicationType') if _text(t)]
        if any(t in types for t in ('Case Reports', 'Editorial', 'Letter', 'Comment', 'Review', 'Systematic Review', 'Meta-Analysis')):
            continue
        if re.search(r'\bcase report\b|\bcase presentation\b|a rare case of|\bcase series\b', title, re.I):
            continue
        uk_designs = {
            'Randomized Controlled Trial': 'Randomised Controlled Trial',
            'Multicenter Study': 'Multicentre Study',
        }
        design = next(
            (uk_designs.get(t, t) for t in types if t in (
                'Randomized Controlled Trial', 'Clinical Trial', 'Validation Study',
                'Multicenter Study', 'Comparative Study', 'Observational Study',
            )),
            None,
        )
        sections = art.findall('.//Abstract/AbstractText')
        results = next(
            (a for a in sections if a.get('NlmCategory') == 'RESULTS' or a.get('Label', '').upper() == 'RESULTS'),
            None,
        )
        words = _text(results).split() if results is not None else []
        excerpt = ' '.join(words[:18]) + ('…' if len(words) > 18 else '')
        category, priority = _priority(title, journal, types, bool(words))
        result.append(dict(
            title=title[:330],
            url='https://pubmed.ncbi.nlm.nih.gov/' + pmid + '/',
            journal=journal[:160],
            date=_date(art),
            category=category,
            priority=priority,
            selection_basis=('Verified indexed study type: ' + design if design else 'Radiography topic and date; design not indexed'),
            design=design or 'Study design not verified by this feed',
            excerpt=excerpt,
        ))

    def published(paper):
        d = paper['date']
        return d if re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) else d[:4] + '-00-00'

    result.sort(key=lambda paper: (paper['priority'], published(paper), paper['title']), reverse=True)
    selected, counts = [], {}
    for paper in result:
        cat = paper['category']
        if counts.get(cat, 0) >= 2:
            continue
        selected.append(paper)
        counts[cat] = counts.get(cat, 0) + 1
        if len(selected) >= limit:
            break
    selected.sort(key=lambda paper: published(paper), reverse=True)
    return selected


def pubmed_feed(offline=False, today=None):
    today = today or date.today()
    out = dict(
        status='unavailable',
        checked=today.isoformat(),
        count=None,
        items=[],
        query=XRAY_QUERY,
        window='past 365 days',
        error='PubMed retrieval unavailable',
    )
    if offline:
        out['error'] = 'Offline mode; no PubMed search performed'
        return out
    try:
        search_url = PUBMED_BASE + 'esearch.fcgi?' + urlencode({
            'db': 'pubmed', 'term': XRAY_QUERY, 'sort': 'pub date', 'retmode': 'json',
            'retmax': 80, 'reldate': 365, 'datetype': 'pdat',
            'tool': 'MedicalImagingXrayDashboard',
        })
        data = json.loads(_read(search_url).decode('utf-8'))
        query = data.get('esearchresult', {})
        count = int(query['count'])
        ids = query['idlist']
        if count < 0 or count > 50_000_000 or not isinstance(ids, list) or any(not str(x).isdigit() for x in ids):
            raise ValueError('Malformed PubMed search response')
        if count and not ids:
            raise ValueError('PubMed returned no sample of nonzero matches')
        items = []
        if ids:
            fetch_url = PUBMED_BASE + 'efetch.fcgi?' + urlencode({
                'db': 'pubmed', 'id': ','.join(ids), 'retmode': 'xml',
                'tool': 'MedicalImagingXrayDashboard',
            })
            items = parse_pubmed(_read(fetch_url), list(map(str, ids)))
        out.update(status='live', count=count, items=items, error='')
    except Exception as exc:
        LOG.warning('X-ray PubMed source unavailable: %s', type(exc).__name__)
        out['error'] = type(exc).__name__ + ' — published evidence feed unavailable'
    return out


def check_market(offline=False, today=None, fetcher=None):
    today = today or date.today()
    checked = today.isoformat()
    out = {
        'publisher': 'Grand View Research',
        'source': GVR_URL,
        'year': 2024,
        'value_bn': 8.4,
        'estimate_year': 2026,
        'estimate_value_bn': 8.9,
        'checked_at': checked,
        'check_status': 'offline · using dated published reference',
    }
    if offline:
        return out
    try:
        raw = (fetcher or _read)(GVR_URL)
        txt = _clean_html(raw) if isinstance(raw, bytes) else raw
        m_2024 = re.search(r'market size was valued at (?:USD|\$)\s*(\d+(?:\.\d+)?)\s*billion in 2024', txt, re.I)
        m_2026 = re.search(r'estimated at (?:USD|\$)\s*(\d+(?:\.\d+)?)\s*billion (?:for|in) 2026', txt, re.I)
        if m_2024:
            val = float(m_2024.group(1))
            if 1.0 <= val <= 40.0:
                out['value_bn'] = val
        if m_2026:
            est = float(m_2026.group(1))
            if 1.0 <= est <= 40.0:
                out['estimate_value_bn'] = est
        if m_2024 or m_2026:
            out['last_verified_at'] = checked
            out['check_status'] = 'source figure reverified'
        else:
            out['check_status'] = 'source reachable; target figure not reverified'
    except Exception as exc:
        LOG.info('X-ray market check unavailable (%s)', type(exc).__name__)
        out['check_status'] = 'site not accessible · using dated published reference'
    return out


def check_nhs_did(offline=False, today=None, fetcher=None):
    today = today or date.today()
    checked = today.isoformat()
    out = {
        'source': NHS_DID_URL,
        'latest_finalised': '2024-25',
        'checked_at': checked,
        'check_status': 'offline · using dated published DID figures',
    }
    if offline:
        return out
    try:
        raw = (fetcher or _read)(NHS_DID_URL)
        txt = _clean_html(raw) if isinstance(raw, bytes) else raw
        finalised = re.search(r'statistics for \d{4}-\d{2} to (20\d{2}-\d{2}) have now been finalised', txt, re.I)
        if finalised:
            out['latest_finalised'] = finalised.group(1)
            out['check_status'] = f"NHS England DID checked {checked}; latest finalised annual release: {out['latest_finalised']}"
        else:
            out['check_status'] = f'NHS England DID reachable ({checked}); using verified 2024/25 finalised release'
    except Exception as exc:
        LOG.info('NHS England DID check unavailable (%s)', type(exc).__name__)
        out['check_status'] = 'NHS England page inaccessible · using verified 2024/25 release'
    return out


def generate(offline=False, today=None, pubmed_fetch=None, market_fetch=None, nhs_fetch=None):
    today = today or date.today()
    publication = (pubmed_fetch or pubmed_feed)(offline=offline, today=today)
    if not isinstance(publication, dict) or 'items' not in publication:
        raise ValueError('Invalid X-ray PubMed publication feed')
    market = (market_fetch or check_market)(offline=offline, today=today)
    nhs = (nhs_fetch or check_nhs_did)(offline=offline, today=today)
    return {
        'schema_version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'pubmed': publication,
        'market': market,
        'nhs_did': nhs,
    }


def render(template, payload):
    marker = '<!-- XRAY_DATA -->'
    if template.count(marker) != 1:
        raise ValueError('X-ray template must have exactly one source-backed data slot')
    if 'xr-overview' not in template or 'xr-papers' not in template:
        raise ValueError('X-ray template missing required dashboard sections')
    return template.replace(marker, safe_json(payload))


def main():
    parser = argparse.ArgumentParser(description='Generate published X-ray dashboard using public sources.')
    parser.add_argument('--template', type=Path, default=BASE_DIR / 'xray.template.html')
    parser.add_argument('--output', type=Path, default=BASE_DIR / 'xray.html')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    payload = generate(offline=args.offline)
    output = render(args.template.read_text(encoding='utf-8'), payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding='utf-8')
    print(
        'X-ray build: PubMed %s (%s titles); market=%s; NHS DID=%s'
        % (
            payload['pubmed']['status'],
            len(payload['pubmed']['items']),
            payload['market']['check_status'],
            payload['nhs_did']['latest_finalised'],
        )
    )


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
