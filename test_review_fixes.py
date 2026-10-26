import copy
import importlib.util
import io
import unittest
from pathlib import Path
from datetime import date,timedelta
from unittest.mock import patch
from urllib.error import HTTPError
spec=importlib.util.spec_from_file_location('review_ai',Path(__file__).with_name('ai_update_data.py'))
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class ReviewFixTests(unittest.TestCase):
 def test_supplied_count_preserves_definition_and_chart(self):
  p=a.build_dashboard(offline=True)
  metric=p['regions']['global']['metrics']['prospective_studies']
  metric.update(value=17,label='Reviewed prospective studies',period='2025',methodology='Reviewed dataset of completed prospective trials',source={'name':'Example registry','url':'https://example.org/studies'})
  p['research_is_curated']=True
  v=a.template_view(p);card=v['regions']['global']['metrics'][1]
  self.assertEqual(card['value'],'17 studies');self.assertIn('completed prospective',card['description'])
  self.assertEqual(card['source'],'https://example.org/studies');self.assertEqual(v['registryChart']['values'][0],17)
  self.assertIn('Check Scope',v['registryChart']['title'])
 def test_ai_evidence_first_layout_survives_automatic_render(self):
  template=(Path(__file__).with_name('ai.template.html')).read_text(encoding='utf-8')
  payload=a.template_view(a.build_dashboard(offline=True))
  rendered=a.render_template(template,payload)
  for text in ('id="ai-overview-section"','id="ai-research-section"',
               'id="ai-evidence-section"',
               'id="ai-industry-section"','id="ai-news-section"',
               'id="ai-source-status-section"',
               "fdaSection.hidden=false"):
   self.assertIn(text,rendered)
  self.assertNotIn('AI Approvals vs. MedTech Venture Capital Investment',rendered)
  self.assertNotIn('Prospective Clinical Validation',rendered)
  self.assertNotIn('fdaSection.hidden=key',rendered)
  self.assertNotIn('For growth, inflation and broader market pressures, see',rendered)
  self.assertNotIn('id="macro-link"',rendered)
  self.assertIn('View annual and year-to-date values',rendered)
  self.assertIn("scroll.setAttribute('role','region')",rendered)
  self.assertIn("canvas.setAttribute('aria-label'",rendered)
  self.assertIn('ai-table-scroll',rendered)
  self.assertLess(rendered.index('id="ai-overview-section"'),rendered.index('id="fda-trend-section"'))
  self.assertLess(rendered.index('id="fda-trend-section"'),rendered.index('id="ai-research-section"'))
  self.assertLess(rendered.index('id="ai-research-section"'),rendered.index('id="ai-evidence-section"'))
  self.assertNotIn('id="regionSelect"',rendered)
  self.assertNotIn("getElementById('regionSelect')",rendered)
  self.assertIn("const key='global';",rendered)
  self.assertNotIn('id="ai-adoption-section"',rendered)
  self.assertNotIn('href="#ai-adoption-section"',rendered)
 def test_homepage_viewport_and_responsive_scaling(self):
  root=Path(__file__).parent
  page=(root/'index.html').read_text(encoding='utf-8')
  css=(root/'styles.css').read_text(encoding='utf-8')
  self.assertEqual(page.count('name="viewport"'),1)
  self.assertIn('class="dashboard-home"',page)
  self.assertIn('.dashboard-home .hero-banner h2',css)
  # Actual responsive layout is checked at three widths in browser_qa.cjs.

 def test_imf_failure_has_no_success_date(self):
  with patch.object(a,'public_json',side_effect=ValueError('failed')):e=a.regional_economic_background()
  self.assertEqual(e['global']['status'],'unavailable');self.assertIsNone(e['global']['retrieved'])
  self.assertTrue(all(c['retrieved'] is None and c['value'] is None for c in e['global']['cards']))
 def test_partial_imf_preserves_valid_zero(self):
  def fetch(url):
   if 'PCPIPCH' in url:raise ValueError('failed')
   return {'values':{'NGDP_RPCH':{'WEOWORLD':{str(date.today().year):0}}}}
  with patch.object(a,'public_json',side_effect=fetch):e=a.regional_economic_background()['global']
  self.assertEqual(e['status'],'partial');self.assertEqual(e['cards'][0]['value'],0);self.assertIsNone(e['retrieved'])
 def test_source_health_includes_pubmed_and_news_failure(self):
  p=a.build_dashboard(offline=True);v=a.template_view(p)
  self.assertTrue(any(x['name']=='PubMed implementation research' and x['status']=='unavailable' for x in v['sourceHealth']))
  self.assertTrue(any(x['name']=='News feeds' and x['status']=='unavailable' for x in v['sourceHealth']))
 def test_abbreviations_survive_implementation_filter(self):
  for title in ['Prospective CT deployment study','MRI adoption in routine care']:
   xml=f'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>{title}</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'.encode()
   with patch.object(a,'public_json',return_value={'esearchresult':{'idlist':['123']}}),patch.object(a,'read_url',return_value=xml):r=a.clinical_evidence_feed(extra_filter='deployment')
   self.assertEqual(len(r['items']),1);self.assertEqual(r['status'],'live')
 def test_failed_pubmed_has_no_success_date(self):
  with patch.object(a,'public_json',side_effect=HTTPError('x',429,'limited',{},None)):r=a.clinical_evidence_feed()
  self.assertIsNone(r['retrieved']);self.assertIn('429',r['reason']);self.assertTrue(r['attempted_at'])
 def test_transient_retry_and_permanent_failure(self):
  response=unittest.mock.MagicMock();response.__enter__.return_value.read.return_value=b'ok'
  with patch.object(a.urllib.request,'urlopen',side_effect=[HTTPError('x',503,'down',{},None),response]) as fetch,patch.object(a.time,'sleep'):
   self.assertEqual(a.read_url('https://example.org'),'ok'.encode());self.assertEqual(fetch.call_count,2)
  with patch.object(a.urllib.request,'urlopen',side_effect=HTTPError('x',404,'missing',{},None)) as fetch,patch.object(a.time,'sleep'):
   with self.assertRaises(HTTPError):a.read_url('https://example.org')
   self.assertEqual(fetch.call_count,1)
 def test_news_window_promotion_and_event_duplicates(self):
  today=date(2026,10,12)
  def item(title,day,url):return dict(title=title,published=day,url=url,source='Publisher')
  news=[item('CARPL.ai Bags $10 Mn To Scale Its AI Medical Imaging Marketplace','2026-10-10','a'),item('CARPL.ai Raises $10 Million in Series A Funding Led by IFC','2026-10-10','b'),item('Radiology AI Market Size Growth Analysis Report','2026-10-11','c'),item('New radiology AI tool','2026-08-01','d'),item('Another radiology AI tool','2026-10-13','e'),item('AI improves CT workflow','2026-10-11','f')]
  selected=a.select_recent_news(news,today)
  self.assertEqual(len(selected),2);self.assertEqual({i['url'] for i in selected},{'a','f'})
 def test_editorial_date_and_source_are_independent(self):
  p=a.build_dashboard(offline=True);p['generated_at']='2027-01-01T00:00:00Z'
  v=a.template_view(p);self.assertEqual(v['regions']['global']['editorialDate'],'2026-10-12')
  self.assertNotIn('expanding rapidly',v['regions']['global']['summary'])
  self.assertTrue(v['regions']['global']['editorialSource']['url'].startswith('https://'))

if __name__=='__main__':unittest.main()
