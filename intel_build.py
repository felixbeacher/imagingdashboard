"""Render source-linked briefings, with no browser-side APIs or credentials."""
import html
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
CATEGORIES = {'regulatory':'Regulatory Clearances','ma':'M&A and Consolidation','funding':'Funding','partnerships':'New Partnerships'}
def esc(value):
    return html.escape(str(value), quote=True)
def card(row, full=False):
    url = row['url']
    assert urlparse(url).scheme == 'https' and urlparse(url).netloc
    stamp = date.fromisoformat(row['date']).strftime('%d %b %Y')
    label = CATEGORIES[row['category']]
    method = row.get('method', 'editorial')
    checked = row.get('checked', '2026-10-25')
    method_label = {'source-digest': 'Automated headline digest · general category guidance', 'ai-source-brief': 'AI synthesis · editorial interpretation'}.get(method, 'AI-assisted editorial brief')
    checked_label = 'Feed retrieved' if method in ('source-digest','ai-source-brief') else 'Source checked'
    source_label = 'Source report via Google News' if urlparse(url).hostname == 'news.google.com' else 'Source report'
    body = f'<p>{esc(row["summary"])}</p>'
    if full:
        body += f'<section class="intel-meaning"><h4>What this means for you</h4><p>{esc(row["meaning"])}</p></section><section class="intel-watch"><h4>What to watch</h4><p>{esc(row["watch"])}</p></section>'
    else:
        body += f'<a class="intel-read" href="intel-{esc(row["category"])}.html#{esc(row["id"])}">Read the briefing <span aria-hidden="true">→</span></a>'
    return f'<article class="intel-story" id="{esc(row["id"])}"><div class="intel-story-meta"><span>{esc(label)}</span><time datetime="{esc(row["date"])}">{stamp}</time></div><h3>{esc(row["title"])}</h3><p class="intel-story-location">{esc(row["region"])} · {esc(row["status"])}</p>{body}<div class="intel-story-source"><a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{source_label}: {esc(row["source"])} ↗</a><span>{esc(method_label)} · {checked_label.lower()} {esc(checked)}</span></div></article>'

def build():
    payload = json.loads((ROOT/'intel-articles.json').read_text())
    rows = sorted(payload['articles'],key=lambda x:x['date'],reverse=True)
    edition = date.fromisoformat(payload['edition']).strftime('%d %B %Y')
    automatic = payload.get('mode') == 'automated'
    edition_label = ('Feed edition' if automatic else 'Pilot edition') + ' · ' + edition
    backend = payload.get('backend', {})
    status_note = ('Automatic collection: last attempted ' + backend['last_attempt'] + '. ' + str(backend.get('successful_sources', 0)) + ' of ' + str(len(backend.get('sources', []))) + ' feeds responded. ' if backend else '')
    status_note += 'Source-led briefings with clearly labelled editorial interpretation or general category guidance.'
    if backend and not backend.get('successful_sources'):
        status_note += ' No feeds responded on the latest attempt; previously collected stories are retained.'
    note = ('Selected source-linked developments; announcement dates are retained. ' if automatic else 'Pilot examples dated June–October 2026. ') + status_note
    assert len({r['id'] for r in rows}) == len(rows)
    for r in rows:
        assert r['category'] in CATEGORIES
        assert date.fromisoformat(r['date']) <= date.today()
    for slug in ['feed',*CATEGORIES]:
        path = ROOT/f'intel-{slug}.html'
        text = path.read_text()
        text = re.sub(r'\s*<!-- INTEL EDITION START -->.*?<!-- INTEL EDITION END -->','',text,flags=re.S)
        if slug == 'feed':
            text = re.sub(r'<p class="intel-note">.*?</p>','',text,flags=re.S)
            section = f'<section class="intel-edition" aria-labelledby="intel-edition-title"><div class="intel-edition-heading"><div><p class="intel-eyebrow">{esc(edition_label)}</p><h2 id="intel-edition-title">The developments. The implications.</h2></div><span class="intel-status">{len(rows)} selected briefings</span></div><p class="intel-note">{esc(note)}</p><div class="intel-story-grid">'+''.join(card(r) for r in rows)+'</div></section>'
            section += '<details class="intel-method"><summary>About this feed and its sources</summary><p>Collection runs weekly on Mondays. Coverage depends on available publisher feeds and news search; selection is not comprehensive. Duplicate headlines and reports outside the four categories are filtered. A feed retrieval date does not independently verify an announcement.</p><p>Automated headline digests reproduce a source headline and add general category guidance. AI source briefings, when enabled, paraphrase supplied excerpts and separate reported facts from interpretation. Company announcements are not independent evidence of clinical benefit. Links through Google News are labelled accordingly.</p><p>When source material is limited, a headline digest is published with general considerations rather than a detailed interpretation. Original announcement dates are retained; the edition date does not make older stories breaking news.</p></details>'
        else:
            text = re.sub(r'<section class="intel-empty".*?</section>','',text,flags=re.S)
            selected=[r for r in rows if r['category']==slug]
            section = f'<section class="intel-edition" aria-labelledby="intel-edition-title"><div class="intel-edition-heading"><h2 id="intel-edition-title">Selected briefings</h2><span class="intel-status">{esc(edition_label)}</span></div><p class="intel-note">{esc(note)}</p>'+''.join(card(r,True) for r in selected)+'</section>'
        text = text.replace('</main>','<!-- INTEL EDITION START -->'+section+'<!-- INTEL EDITION END --></main>')
        path.write_text(text)
if __name__ == '__main__':
    build()
