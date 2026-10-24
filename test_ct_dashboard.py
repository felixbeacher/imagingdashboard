"""CT modality dashboard source, analytics and layout tests (no network needed)."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import ct_dashboard as ct

ROOT=Path(__file__).parent


class CTDashboardTests(unittest.TestCase):
    def fake_oecd(self,offline=False):
        obj=ct.empty_oecd()
        obj['checked']='2026-10-24'
        c=obj['countries']['CHE']
        c['equipment'].update(status='available',scope='All healthcare providers',
            series={'CT':[{'year':2021,'value':24.2},{'year':2023,'value':25.6}],
                    'MRI':[],'PET':[]})
        c['exams'].update(status='available',scope='Hospitals only (not all examinations)',
            series={'CT':[{'year':2021,'value':151.4},{'year':2022,'value':157.3}],
                    'MRI':[],'PET':[]})
        return obj

    def fake_pubmed(self,offline=False,today=None):
        return dict(status='live',checked='2026-10-24',count=42,
                    items=[{'title':'Computed tomography in stroke care',
                            'journal':'Journal Example','date':'2026',
                            'url':'https://pubmed.ncbi.nlm.nih.gov/123/',
                            'kind':'CT clinical / technical study','design':'Study design not verified by this feed',
                            'excerpt':''}],query=ct.CT_QUERY)

    def test_page_is_real_ct_not_ai_dashboard(self):
        t=(ROOT/'ct.template.html').read_text(encoding='utf-8')
        for label in ('CT at a glance','Scanner availability and examination activity',
                      'What it measures','Why it matters for imaging',
                      'Recently published CT research','From CT trends to imaging decisions',
                      'Aim of this page', 'ct-data-lag', 'ct-region', 'ct-country', 'ct-region-scanners'):
            self.assertIn(label,t)
        for stale in ('AI Approvals vs. MedTech Venture Capital Investment',
                      'Vendor AI Revenue Breakdown','Radiologist Vacancy Rate'):
            self.assertNotIn(stale,t)
        self.assertIn('name="viewport"',t)
        self.assertIn('ct.template.html',str(ROOT/'ct.template.html'))
        self.assertNotIn('Imaging modality · computed tomography',t)
        self.assertNotIn('Unlike imaging AI',t)
        self.assertNotIn('<h3>Radiation and appropriateness</h3>',t)
        self.assertLess(t.index('id="ct-market"'), t.index('id="ct-industry"'))
        self.assertLess(t.index('id="ct-industry"'), t.index('Global CT manufacturer shares · DBS estimate'))
        self.assertLess(t.index('Global CT manufacturer shares · DBS estimate'), t.index('Selected CT product portfolios'))
        self.assertLess(t.index('id="ct-activity"'),t.index('id="ct-interpretation"'))
        self.assertLess(t.index('id="ct-interpretation"'),t.index('id="ct-research"'))

    def test_valid_observations_and_scope_are_not_aggregated(self):
        d=ct.generate(offline=True,today=__import__('datetime').date(2026,10,24),
            oecd_fetch=self.fake_oecd,pubmed_fetch=self.fake_pubmed)
        self.assertEqual(d['oecd']['countries']['CHE']['equipment']['series']['CT'][1]['year'],2023)
        self.assertEqual(d['oecd']['countries']['CHE']['exams']['scope'],
            'Hospitals only (not all examinations)')
        self.assertEqual(d['pubmed']['count'],42)
        self.assertIn('projection',d['oecd']['countries']['CHE']['equipment'])
        self.assertEqual(d['oecd']['countries']['CHE']['equipment']['projection']['status'],'unavailable')
        self.assertEqual(d['regional_groups']['europe']['countries'],['CHE','GBR','DEU','FRA'])
        self.assertEqual(d['regional_groups']['northAmerica']['countries'],['USA','CAN'])
        self.assertEqual(d['regional_groups']['asiaPacific']['countries'],['AUS','JPN'])
        self.assertFalse(d['oecd']['countries']['USA']['equipment']['series']['CT'])

    def test_reject_future_and_duplicate_year(self):
        for invalid in [
            [{'year':2028,'value':10}],
            [{'year':2021,'value':10},{'year':2021,'value':11}],
            [{'year':2020,'value':-1}],
        ]:
            def bad(offline=False):
                obj=self.fake_oecd()
                obj['countries']['CHE']['equipment']['series']['CT']=invalid
                return obj
            with self.assertRaises(ValueError):
                ct.generate(offline=True,today=__import__('datetime').date(2026,10,24),
                    oecd_fetch=bad,pubmed_fetch=self.fake_pubmed)

    def test_2025_2026_2027_ct_scenario_from_2024_actuals(self):
        points=[{'year':2022,'value':20},{'year':2023,'value':20.5},
                {'year':2024,'value':22}]
        forecast=ct.ct_trend_scenario(points,'equipment',through=2027)
        self.assertEqual(forecast['status'],'illustrative')
        self.assertEqual([x['year'] for x in forecast['points']],[2025,2026,2027])
        self.assertTrue(forecast['capped'])  # 2022-2024 annualised growth exceeds 5%
        self.assertAlmostEqual(forecast['annual_rate'],0.05,places=4)
        self.assertAlmostEqual(forecast['points'][0]['value'],23.1)
        self.assertTrue(all(x['low'] < x['value'] < x['high'] for x in forecast['points']))
        self.assertGreater(forecast['points'][2]['high']-forecast['points'][2]['low'],
                           forecast['points'][0]['high']-forecast['points'][0]['low'])
        self.assertEqual(points[-1]['year'],2024)  # actual history remains unchanged

    def test_actual_2025_supersedes_projected_2025_and_sparse_history_does_not_infer(self):
        points=[{'year':2023,'value':100},{'year':2024,'value':104},
                {'year':2025,'value':107}]
        forecast=ct.ct_trend_scenario(points,'exams',through=2027)
        self.assertEqual([x['year'] for x in forecast['points']],[2026,2027])
        self.assertFalse(ct.ct_trend_scenario(points[:2],'exams')['points'])
        self.assertFalse(ct.ct_trend_scenario([
            {'year':2016,'value':80},{'year':2018,'value':83},
            {'year':2021,'value':89}],'exams')['points'])
        self.assertFalse(ct.ct_trend_scenario([
            {'year':2021,'value':0},{'year':2023,'value':2},
            {'year':2024,'value':4}],'exams')['points'])

    def test_ct_market_estimates_are_dated_and_source_backed(self):
        import ct_market
        catalog=ct_market.read_reference()
        self.assertEqual(catalog['size']['year'],2025)
        self.assertGreaterEqual(len(catalog['size']['entries']),3)
        for entry in catalog['size']['entries']:
            self.assertTrue(entry['source'].startswith('https://'))
            self.assertTrue(entry['publication_date'])
        self.assertEqual(sum(e['value'] for e in catalog['shares']['entries']),100)
        self.assertTrue(any(e.get('derived') for e in catalog['shares']['entries']))
        snap=ct_market.refresh(catalog,offline=True)
        self.assertEqual([x['value'] for x in snap['size']['entries']],
                         [x['value'] for x in catalog['size']['entries']])
        self.assertTrue(all('published reference' in x['check_status'] for x in snap['size']['entries']))

    def test_commercial_estimates_survive_embedded_render(self):
        payload=ct.generate(offline=True)
        rendered=ct.render((ROOT/'ct.template.html').read_text(encoding='utf-8'),payload)
        self.assertIn('id="ct-market"',rendered)
        self.assertIn('function renderMarket()',rendered)
        self.assertIn('id="ct-share-bars"',rendered)
        self.assertIn("el('div','ct-share-bar')",rendered)
        self.assertIn('.sort((a,b)=>b.value-a.value',rendered)
        self.assertIn("el('strong','ct-share-percent',fmt(item.value,0)+'%')",rendered)
        self.assertNotIn('id="ct-share-stack"',rendered)
        self.assertNotIn('id="ct-share-legend"',rendered)
        self.assertIn('CT manufacturer shares',rendered)
        self.assertIn('DBS CIO Industry Guide',rendered)
        import re
        obj=json.loads(re.search(r'<script id="ct-data" type="application/json">([\s\S]*?)</script>',rendered).group(1))
        self.assertEqual(sum(x['value'] for x in obj['market']['shares']['entries']),100)

    def test_pubmed_does_not_invent_design(self):
        xml=b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID>
        <Article><ArticleTitle>Photon-counting CT for vascular imaging</ArticleTitle>
        <Journal><Title>Radiology Example</Title></Journal>
        <Abstract><AbstractText NlmCategory="RESULTS">Some observed evidence requiring careful interpretation and study-design assessment.</AbstractText></Abstract>
        </Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'''
        res=ct.parse_pubmed(xml,['123'])
        self.assertEqual(len(res),1)
        self.assertEqual(res[0]['kind'],'Photon-counting CT')
        self.assertIn('not verified',res[0]['design'])
        self.assertEqual(res[0]['url'],'https://pubmed.ncbi.nlm.nih.gov/123/')

    def test_newest_first_and_exclude_non_xray_tomography(self):
        xml=b'''<PubmedArticleSet>
        <PubmedArticle><MedlineCitation><PMID>101</PMID><Article><ArticleTitle>
        Computed tomography for abdominal assessment</ArticleTitle><ArticleDate>
        <Year>2026</Year><Month>02</Month><Day>10</Day></ArticleDate></Article>
        </MedlineCitation></PubmedArticle>
        <PubmedArticle><MedlineCitation><PMID>102</PMID><Article><ArticleTitle>
        Photon-counting CT for lung disease</ArticleTitle><ArticleDate>
        <Year>2026</Year><Month>10</Month><Day>12</Day></ArticleDate></Article>
        </MedlineCitation></PubmedArticle>
        <PubmedArticle><MedlineCitation><PMID>103</PMID><Article><ArticleTitle>
        Photoacoustic computed tomography for animal tissue</ArticleTitle><ArticleDate>
        <Year>2026</Year><Month>10</Month><Day>20</Day></ArticleDate></Article>
        </MedlineCitation></PubmedArticle>
        </PubmedArticleSet>'''
        items=ct.parse_pubmed(xml,['101','102','103'])
        self.assertEqual([i['title'] for i in items],
            ['Photon-counting CT for lung disease','Computed tomography for abdominal assessment'])
        self.assertEqual(items[0]['date'],'2026-10-12')

    def test_escape_script_data_and_build(self):
        payload=ct.generate(offline=True,today=__import__('datetime').date(2026,10,24),
            oecd_fetch=self.fake_oecd,pubmed_fetch=self.fake_pubmed)
        payload['pubmed']['items'][0]['title']='</script><script>alert(1)</script>'
        rendered=ct.render((ROOT/'ct.template.html').read_text(encoding='utf-8'),payload)
        self.assertEqual(rendered.count('</script>'),2)
        self.assertNotIn('</script><script>alert',rendered)
        self.assertIn(r'\u003c/script\u003e',rendered)
        self.assertEqual(rendered.count('id="ct-overview"'),1)
        self.assertEqual(rendered.count('id="ct-region"'),1)
        self.assertIn('function setRegionalOverview(regionKey)',rendered)
        self.assertIn('function chooseRegion(regionKey,preferredCode)',rendered)
        self.assertIn('Modelled trend (2025–2027, where applicable)',rendered)
        self.assertIn('function updateReportingNote(code,scanners,exams)',rendered)
        self.assertIn("svgChart(series.points,label,unit,series.projection)",rendered)
        self.assertNotIn('Explore country data',rendered)
        self.assertIn('Country detail within this region',rendered)
        self.assertIn('2021',rendered)

    def test_offline_sources_are_empty_not_imagined(self):
        d=ct.generate(offline=True)
        self.assertIsNone(d['pubmed']['count'])
        self.assertEqual(d['pubmed']['status'],'unavailable')
        self.assertTrue(all(not d['oecd']['countries'][k]['equipment']['series']['CT']
                            for k in d['oecd']['countries']))


if __name__ == '__main__':
    unittest.main()
