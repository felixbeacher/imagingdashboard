"""Render source-linked pilot briefings, with no API calls or credentials."""
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
    body = f'<p>{esc(row["summary"])}</p>'
    if full:
        body += f'<section class="intel-meaning"><h4>What this means for you</h4><p>{esc(row["meaning"])}</p></section><section class="intel-watch"><h4>What to watch</h4><p>{esc(row["watch"])}</p></section>'
    else:
        body += f'<a class="intel-read" href="intel-{esc(row["category"])}.html#{esc(row["id"])}">Read the briefing <span aria-hidden="true">→</span></a>'
    return f'<article class="intel-story" id="{esc(row["id"])}"><div class="intel-story-meta"><span>{esc(label)}</span><time datetime="{esc(row["date"])}">{stamp}</time></div><h3>{esc(row["title"])}</h3><p class="intel-story-location">{esc(row["region"])} · {esc(row["status"])}</p>{body}<div class="intel-story-source"><a href="{esc(url)}" target="_blank" rel="noopener noreferrer">Original announcement: {esc(row["source"])} ↗</a><span>AI-assisted editorial brief · source checked 25 Oct 2026</span></div></article>'

def build():
    payload = json.loads((ROOT/'intel-articles.json').read_text())
    rows = sorted(payload['articles'],key=lambda x:x['date'],reverse=True)
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
            section = '<section class="intel-edition" aria-labelledby="intel-edition-title"><div class="intel-edition-heading"><div><p class="intel-eyebrow">Pilot edition · 25 October 2026</p><h2 id="intel-edition-title">The developments. The implications.</h2></div><span class="intel-status">4 selected briefings</span></div><p class="intel-note">A working editorial sample, with announcements dated June–October 2026. Selected examples, not a comprehensive or continuously updated news service.</p><div class="intel-story-grid">'+''.join(card(r) for r in rows)+'</div></section>'
            section += '<details class="intel-method"><summary>About this edition and its sources</summary><p>Briefings paraphrase linked company announcements. Company claims are attributed; practical implications are editorial interpretation. No independently verified clinical benefits are implied. The current sample is concentrated on two companies to demonstrate the format, not to represent the whole market.</p><p>Automatic news writing and publication are not enabled in this pilot. No paid AI API is used. Stories retain their announcement dates so older developments are not presented as breaking news.</p></details>'
        else:
            text = re.sub(r'<section class="intel-empty".*?</section>','',text,flags=re.S)
            selected=[r for r in rows if r['category']==slug]
            section = '<section class="intel-edition" aria-labelledby="intel-edition-title"><div class="intel-edition-heading"><h2 id="intel-edition-title">Selected briefings</h2><span class="intel-status">Pilot edition · 25 Oct 2026</span></div><p class="intel-note">Dated examples for the draft feed. Source announcements and editorial interpretation are separated below.</p>'+''.join(card(r,True) for r in selected)+'</section>'
        text = text.replace('</main>','<!-- INTEL EDITION START -->'+section+'<!-- INTEL EDITION END --></main>')
        path.write_text(text)
if __name__ == '__main__':
    build()
