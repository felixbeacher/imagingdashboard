"""Remove build-only AI evidence after validation, keeping the browser payload.

The canonical dataset remains available to build validation and in the source
snapshot; visitors need only ai-data. No data or rendering inputs are changed.
"""
import argparse
import json
from pathlib import Path
import re


def compact_ai(html):
    pattern = r'<script\s+id="dashboard-data"\s+type="application/json">(.*?)</script>'
    matches = list(re.finditer(pattern, html, re.S))
    if len(matches) != 1:
        raise ValueError('Expected one canonical AI build dataset before packaging')
    browser = re.search(r'<script id="ai-data" type="application/json">(.*?)</script>', html, re.S)
    if not browser or not json.loads(browser[1]).get('regions'):
        raise ValueError('Public AI rendering payload is missing')
    canonical = json.loads(matches[0][1])
    if not canonical.get('fda_benchmark') or not canonical.get('regions'):
        raise ValueError('Canonical AI evidence is invalid')
    return html[:matches[0].start()] + html[matches[0].end():]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    path = args.directory / 'ai.html'
    original = path.read_text(encoding='utf-8')
    public = compact_ai(original)
    path.write_text(public, encoding='utf-8')
    before, after = len(original.encode()), len(public.encode())
    print(f'Public AI HTML: {before:,} -> {after:,} bytes '
          f'({100 * (before-after) / before:.1f}% smaller before compression).')


if __name__ == '__main__':
    main()
