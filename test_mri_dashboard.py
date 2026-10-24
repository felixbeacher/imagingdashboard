"""Verify MRI source-backed page, market reference and research screening without HTTP."""
import json
from datetime import date
from pathlib import Path
import re
import unittest
import mri_dashboard as mri
import mri_market

ROOT=Path(__file__).resolve().parent

class MRIPageTests(unittest.TestCase):
    def test_market_reference(self):
        x=mri_market.read_reference()
        self.assertEqual(x['size']['year'],2025)
        self.assertEqual(x['shares']['reference_year'],2022)
        self.assertEqual(sum(a['value'] for a in x['shares']['entries']),100)
        self.assertTrue(all(a['source'].startswith('https://') for a in x['size']['entries']))
        self.assertTrue(mri_market.validate(x))

    def test_template_mri_content(self):
        s=(ROOT/'mri.template.html').read_text(encoding='utf-8')
        for term in ('id="mri-data"', 'id="mri-region"', 'MRI at a glance',
                     'Global MRI equipment market size', 'MRI scanner availability',
                     'MRI manufacturer shares', 'Magnetic field strength and gradients',
                     'Paediatric MRI', 'United Imaging Healthcare','ACR MR Safety'):
            self.assertIn(term,s)
        for bad in ('AI Approvals vs. MedTech Venture Capital Investment',
                    'Vendor AI Revenue Breakdown', 'DBS estimate',
                    'photon-counting CT','id="ct-data"','<!-- CT_DATA -->'):
            self.assertNotIn(bad,s)
        self.assertEqual(s.count('<!-- MRI_DATA -->'),1)
        self.assertIn('mri.template.html',str(ROOT/'mri.template.html'))

    def test_offline_no_fabricated_observations(self):
        data=mri.generate(offline=True,today=date(2026,10,24))
        self.assertIsNone(data['pubmed']['count'])
        self.assertEqual(data['pubmed']['items'],[])
        self.assertTrue(all(not c['equipment']['series']['MRI'] for c in data['oecd']['countries'].values()))
        self.assertTrue(all(not c['exams']['series']['MRI'] for c in data['oecd']['countries'].values()))
        self.assertEqual(data['market']['shares']['reference_year'],2022)
        page=mri.render((ROOT/'mri.template.html').read_text(encoding='utf-8'),data)
        embedded=json.loads(re.search(r'<script id="mri-data" type="application/json">([\s\S]*?)</script>',page).group(1))
        self.assertEqual(embedded['market']['size']['year'],2025)
        self.assertIn('function renderMarket()',page)

    def test_forecasts_are_not_automatic(self):
        observations=[{'year':2021,'value':15},{'year':2022,'value':15.5},
                      {'year':2023,'value':16},{'year':2024,'value':16.5}]
        model=mri.mri_trend_scenario(observations,'equipment')
        self.assertEqual([x['year'] for x in model['points']],[2025,2026,2027])
        self.assertIn('backtest_error_pct',model)
        self.assertEqual(mri.mri_trend_scenario(observations[:3],'equipment')['status'],'unavailable')

    def test_non_mri_and_case_report_are_excluded(self):
        xml=b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID>
        <Article><ArticleTitle>Functional MRI for brain assessment</ArticleTitle>
        <Journal><Title>Radiology</Title></Journal>
        <PublicationTypeList><PublicationType>Comparative Study</PublicationType></PublicationTypeList>
        </Article></MedlineCitation></PubmedArticle>
        <PubmedArticle><MedlineCitation><PMID>124</PMID>
        <Article><ArticleTitle>A rare case of magnetic resonance imaging diagnosis</ArticleTitle>
        <PublicationTypeList><PublicationType>Case Reports</PublicationType></PublicationTypeList>
        </Article></MedlineCitation></PubmedArticle>
        </PubmedArticleSet>'''
        articles=mri.parse_pubmed(xml,['123','124'])
        self.assertEqual(len(articles),1)
        self.assertIn('MRI',articles[0]['title'])
        self.assertEqual(articles[0]['url'],'https://pubmed.ncbi.nlm.nih.gov/123/')

if __name__=='__main__':
    unittest.main()
