"""Shared economy tab. Standard library; risk observations are a dated CSV snapshot.

The AI updater calls publish_macro during static builds and MacroService when serving.
Economic observations refresh independently of the supplied risk data. The chart
must be regenerated when risk-data.csv changes; its fingerprint is checked here.
"""
from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import html
import json
import math
import re
import shutil
import tempfile
import os
import threading
import time

COMPONENTS = ['Geopolitical tension', 'Financial stress', 'Supply-chain pressure',
              'Energy price pressure', 'Food price pressure']
TOTAL = 'Global risk composite | 0_100'


def read_risk(root):
    path = Path(root) / 'risk-data.csv'
    with path.open(encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError('Risk CSV is empty')
    previous = None
    for row in rows:
        month = datetime.strptime(row['month'], '%Y-%m-%d')
        if month.day != 1 or (previous is not None and month.year * 12 + month.month != previous + 1):
            raise ValueError('Risk months must be continuous and strictly increasing')
        previous = month.year * 12 + month.month
        scores = [float(row[name + ' | score_0_100']) for name in COMPONENTS]
        total = float(row[TOTAL])
        if any(not math.isfinite(x) or not 0 <= x <= 100 for x in scores + [total]):
            raise ValueError('Invalid risk score')
        if abs(sum(scores) / 5 - total) > .00001:
            raise ValueError('Risk composite is inconsistent with the five components')
        if abs(sum(scores) - float(row['Total | sum_0_500'])) > .00001:
            raise ValueError('Risk component sum is inconsistent')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    svg = (Path(root) / 'risk.svg').read_text(encoding='utf-8')
    if f'risk-data-sha256:{digest}' not in svg:
        raise ValueError('Risk chart and CSV do not match; regenerate risk.svg')
    latest, prior = rows[-1], rows[-2] if len(rows) > 1 else rows[-1]
    peak = max(rows, key=lambda row: float(row[TOTAL]))
    return dict(start=rows[0]['month'], end=latest['month'], count=len(rows),
                latest=float(latest[TOTAL]), change=float(latest[TOTAL])-float(prior[TOTAL]),
                peak=float(peak[TOTAL]), peak_month=peak['month'],
                components=[dict(name=name, score=float(latest[name+' | score_0_100'])) for name in COMPONENTS],
                rows=[dict(month=row['month'], total=float(row[TOTAL]),
                           scores=[float(row[name+' | score_0_100']) for name in COMPONENTS]) for row in rows],
                csv_sha256=digest)


def build_payload(root, fetch_economics, offline=False):
    return dict(generated_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                economics=fetch_economics(offline), risk=read_risk(root),
                economic_mode='offline' if offline else 'source_refresh',
                risk_notice='Supplied historical snapshot; economic refreshes do not update this risk dataset.')


def render(template, payload):
    raw=json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return template.replace('<!-- MACRO_DATA -->', raw)


def atomic_write(path, content):
    path=Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(content)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def publish_macro(destination, root, fetch_economics, offline=False):
    root=Path(root);destination=Path(destination)
    payload=build_payload(root, fetch_economics, offline)
    page=render((root/'global-macro.template.html').read_text(encoding='utf-8'),payload)
    destination.mkdir(parents=True,exist_ok=True)
    for name in ['risk.svg','risk-data.csv','global-risk-report.html']:
        if (root/name).resolve() != (destination/name).resolve():shutil.copy2(root/name,destination/name)
    atomic_write(destination/'global-macro.html',page)
    return payload


class MacroService:
    def __init__(self,root,fetch_economics,offline=False,cache_seconds=900):
        self.root=Path(root);self.fetch=fetch_economics;self.offline=offline;self.seconds=cache_seconds
        self.cached=None;self.updated=0;self.lock=threading.Lock()
    def payload(self):
        with self.lock:
            if self.cached is None or time.monotonic()-self.updated>=self.seconds:
                self.cached=build_payload(self.root,self.fetch,self.offline);self.updated=time.monotonic()
            return self.cached
    def html(self):
        return render((self.root/'global-macro.template.html').read_text(encoding='utf-8'),self.payload())
