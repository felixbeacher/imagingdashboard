import copy
from datetime import date
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import intel_build
import intel_collect as backend

class IntelBackendTests(unittest.TestCase):
    def feed(self,title='Imaging company announces FDA clearance',stamp='Sun, 25 Oct 2026 08:00:00 GMT',url='https://example.org/story'):
        return f'<rss><channel><item><title>{title}</title><link>{url}</link><pubDate>{stamp}</pubDate><description>Source description.</description></item></channel></rss>'.encode()
    def test_feed_date_category_and_url(self):
        rows=backend.parse_feed(self.feed(),'Publisher',date(2026,10,25))
        self.assertEqual(rows[0]['category'],'regulatory')
        for raw in [self.feed(stamp='Mon, 26 Oct 2026 08:00:00 GMT'),self.feed(stamp='bad'),self.feed(url='javascript:alert(1)'),self.feed(title='Hospital appoints a new receptionist')]:
            self.assertEqual(backend.parse_feed(raw,'Publisher',date(2026,10,25)),[])
    def test_reject_xml_entities(self):
        with self.assertRaises(ValueError):
            backend.parse_feed(b'<!DOCTYPE rss [<!ENTITY e "oops">]><rss/>','Source')
    def test_duplicate_title_and_url(self):
        a={'title':'Radiology company raises funding for imaging AI','url':'https://one.example/a'}
        self.assertTrue(backend.duplicate(a,dict(a,url='https://two.example/a')))
        self.assertFalse(backend.duplicate(a,dict(a,title='FDA clears new CT scanner',url='https://other.example/a')))
    def test_api_disabled_without_explicit_free_confirmation(self):
        with patch.dict(os.environ,{'INTEL_ENABLE_AI':'true','INTEL_FREE_TIER_CONFIRMED':'false','GEMINI_API_KEY':'test-only'},clear=True),patch('urllib.request.urlopen') as opener:
            self.assertIsNone(backend.ai_draft({'description':'text '*100}))
            opener.assert_not_called()
    def test_reject_unsupported_number_or_evidence(self):
        item={'title':'Imaging company raises $30 million','description':'Source description about financing.'}
        draft=dict(summary='The company raised $99 million in new financing.',meaning='Ask about support and product delivery plans.',watch='Review financing terms before drawing conclusions.',evidence='A fabricated quotation unsupported by the source.')
        with self.assertRaises(ValueError):backend.validate_draft(draft,item)
        draft['evidence']=item['title']
        with self.assertRaises(ValueError):backend.validate_draft(draft,item)
    def test_repeated_refresh_keeps_archive_and_deduplicates(self):
        item=dict(title='Medical imaging company announces partnership',date=date.today().isoformat(),url='https://example.org/new',source='Source',category='partnerships',description='Short feed excerpt')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'articles.json';path.write_text(json.dumps({'edition':date.today().isoformat(),'mode':'pilot','articles':[]}))
            with patch.object(backend,'collect',return_value=([item],[dict(name='Source',status='ok')])),patch.dict(os.environ,{},clear=True):
                self.assertEqual(backend.refresh(path)['new_articles'],1)
                self.assertEqual(backend.refresh(path)['new_articles'],0)
            self.assertEqual(len(json.loads(path.read_text())['articles']),1)
            with patch.object(backend,'collect',return_value=([],[dict(name='Source',status='unavailable')])):
                backend.refresh(path)
            self.assertEqual(len(json.loads(path.read_text())['articles']),1)
    def test_daily_limit_survives_repeated_runs(self):
        today=date.today().isoformat()
        rows=[dict(title=f'Imaging partnership with hospital {i}',date=today,url=f'https://example.org/{i}',source='Source',category='partnerships',description='Short excerpt') for i in range(8)]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'articles.json';path.write_text(json.dumps({'edition':today,'articles':[]}))
            with patch.object(backend,'collect',return_value=(rows,[])),patch.dict(os.environ,{},clear=True):
                self.assertEqual(backend.refresh(path)['new_articles'],4)
                self.assertEqual(backend.refresh(path)['new_articles'],0)
    def test_ai_error_falls_back_without_further_calls(self):
        today=date.today().isoformat()
        rows=[dict(title=f'Imaging partnership hospital {i}',date=today,url=f'https://example.org/{i}',source='Source',category='partnerships',description='Excerpt '*100) for i in range(2)]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'articles.json';path.write_text(json.dumps({'edition':today,'articles':[]}))
            with patch.object(backend,'collect',return_value=(rows,[])),patch.dict(os.environ,{'INTEL_ENABLE_AI':'true','INTEL_FREE_TIER_CONFIRMED':'true','GEMINI_API_KEY':'test-only'},clear=True),patch.object(backend,'ai_draft',side_effect=TimeoutError) as draft:
                result=backend.refresh(path)
                self.assertEqual(draft.call_count,1)
                self.assertEqual(result['ai_errors'],1)
                self.assertTrue(all(r['method']=='source-digest' for r in json.loads(path.read_text())['articles']))
    def test_render_escapes_feed_text_and_labels_digest(self):
        row=backend.source_digest(dict(title='<script>bad</script>',source='Source',date='2026-10-25',category='ma',url='https://example.org/x'),'2026-10-25')
        rendered=intel_build.card(row,True)
        self.assertNotIn('<script>',rendered)
        self.assertIn('general category guidance',rendered)
    def test_build_is_repeatable_and_links_resolve(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for p in intel_build.ROOT.glob('intel-*.html'):(root/p.name).write_text(p.read_text())
            (root/'intel-articles.json').write_text((intel_build.ROOT/'intel-articles.json').read_text())
            with patch.object(intel_build,'ROOT',root):
                intel_build.build();first={p.name:p.read_text() for p in root.glob('*.html')};intel_build.build()
                self.assertEqual(first,{p.name:p.read_text() for p in root.glob('*.html')})
                for content in first.values():self.assertEqual(content.count('<!-- INTEL EDITION START -->'),1)
if __name__=='__main__':unittest.main()
