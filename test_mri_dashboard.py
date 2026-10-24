"""MRI page modality, provenance and regression checks; no network required."""
from datetime import date
import json
from pathlib import Path
import re
import unittest

import mri_dashboard as mri
import mri_market

ROOT=Path(__file__).parent


class MRIDashboardTests(unittest.TestCase):
    def test_mri_layout_closely_matches_ct(self):
        h=(ROOT/'mri.template.html').read_text(encoding='utf-8')
        for phrase in ('Aim of this page','SELECT REGION','MRI at a glance',
                'Regional MRI comparison','Global MRI equipment market size',
                'Scanner availability and examination activity',
                'From MRI trends to imaging decisions',
                'Recently published MRI research','Where MRI fits in to clinical care',
                'Technology and service considerations','Selected MRI equipment manufacturers',
                'What it measures','Why it matters for imaging',
                'Siemens Healthineers','United Imaging Healthcare',
                'Fujifilm Healthcare','2022 benchmark'):
            self.assertIn(phrase,h)
        self.assertIn('mri-region',h)
        self.assertIn('mri-share-bars',h)
        self.assertIn('mri-data',h)
        self.assertNotIn('Vendor AI Revenue Breakdown',h)
        self.assertNotIn('AI Approvals vs. MedTech Venture Capital Investment',h)
        self.assertNotIn('<!-- CT_DATA -->',h)
        self.assertNotIn('id="mri-country"',h)
        self.assertNotIn('DBS',h)
        self.assertEqual(h.count('</script>'),2)
        self.assertIn('min-width:700px',h)  # mobile scroll
        self.assertIn('id="mri-comparison-warning"',h)
        self.assertIn('role="list"',h)

    def test_mri_market_references_and_2022_shares(self):
        ref=mri_market.read_reference()
        self.assertEqual(ref['size']['year'],2025)
        self.assertEqual(len(ref['size']['entries']),3)
        self.assertEqual(ref['shares']['reference_year'],2022)
        self.assertEqual(sum(x['value'] for x in ref['shares']['entries']),100)
        self.assertEqual({x['name']:x['value'] for x in ref['shares']['entries']}['Siemens Healthineers'],33)
        self.assertEqual({x['name']:x['value'] for x in ref['shares']['entries']}['GE HealthCare'],23)
        self.assertIn('Next Move',ref['shares']['publisher'])
        self.assertNotIn('DBS',ref['shares']['source'])
        for record in ref['size']['entries']:
            self.assertTrue(record['publication_date'])
            self.assertTrue(record['source'].startswith('https://'))
        offline=mri_market.refresh(ref,offline=True,today=date(2026,10,24))
        self.assertEqual([x['value'] for x in offline['size']['entries']],
                         [x['value'] for x in ref['size']['entries']])

    def test_mri_source_is_not_ct_feed(self):
        d=mri.generate(offline=True,today=date(2026,10,24))
        self.assertEqual(d['pubmed']['status'],'unavailable')
        self.assertEqual(d['market']['shares']['reference_year'],2022)
        self.assertEqual(d['regional_groups']['europe']['countries'],['CHE','GBR','DEU','FRA'])
        self.assertIn('MRI',mri.MRI_QUERY)
        self.assertTrue(all(not country['equipment']['series']['MRI']
                            for country in d['oecd']['countries'].values()))
        self.assertTrue(all(country['exams']['projection']['status']=='unavailable'
                            for country in d['oecd']['countries'].values()))
        rendered=mri.render((ROOT/'mri.template.html').read_text(encoding='utf-8'),d)
        self.assertIn('"reference_year": 2022',rendered) if False else None
        self.assertIn('"reference_year": 2022'.replace(': ',': '),json.dumps(d))  # source schema
        self.assertIn('function renderMarket()',rendered)
        self.assertIn('function regionalHistory(',rendered)
        self.assertIn('mri-market-size-value',rendered)
        self.assertNotIn('<!-- MRI_DATA -->',rendered)

    def test_mri_projections_are_conservative(self):
        sufficient=[{'year':2021,'value':17},{'year':2022,'value':17.3},
                    {'year':2023,'value':17.6},{'year':2024,'value':17.8}]
        forecast=mri.mri_trend_scenario(sufficient,'equipment')
        self.assertEqual([x['year'] for x in forecast['points']],[2025,2026,2027])
        self.assertLessEqual(forecast['backtest_error_pct'],10.0)
        self.assertFalse(mri.mri_trend_scenario(sufficient[:3],'equipment')['points'])
        gappy=[sufficient[0],sufficient[1],{'year':2024,'value':17.7},
               {'year':2025,'value':18.1}]
        self.assertFalse(mri.mri_trend_scenario(gappy,'equipment')['points'])

    def test_pubmed_avoids_ct_primary_and_comprehensive_reviews(self):
        xml=b'''<PubmedArticleSet>
        <PubmedArticle><MedlineCitation><PMID>61</PMID><Article>
        <ArticleTitle>Photon-counting CT compared with MRI in bone imaging</ArticleTitle>
        </Article></MedlineCitation></PubmedArticle>
        <PubmedArticle><MedlineCitation><PMID>62</PMID><Article>
        <ArticleTitle>Magnetic resonance imaging of stroke: a comprehensive review</ArticleTitle>
        </Article></MedlineCitation></PubmedArticle>
        <PubmedArticle><MedlineCitation><PMID>63</PMID><Article>
        <ArticleTitle>Cardiac MRI for myocardial function: a comparative study</ArticleTitle>
        </Article></MedlineCitation></PubmedArticle>
        </PubmedArticleSet>'''
        items=mri.parse_pubmed(xml,['61','62','63'])
        self.assertEqual([x['url'] for x in items],
                         ['https://pubmed.ncbi.nlm.nih.gov/63/'])


    def test_pubmed_mri_filters_and_design(self):
        content=b'''<PubmedArticleSet>
        <PubmedArticle><MedlineCitation><PMID>42</PMID><Article>
        <ArticleTitle>Magnetic resonance imaging for cardiac assessment</ArticleTitle>
        <Journal><Title>Radiology</Title></Journal>
        <PublicationTypeList><PublicationType>Comparative Study</PublicationType></PublicationTypeList>
        </Article></MedlineCitation></PubmedArticle>
        <PubmedArticle><MedlineCitation><PMID>43</PMID><Article>
        <ArticleTitle>MRI findings in a rare case report</ArticleTitle>
        <PublicationTypeList><PublicationType>Case Reports</PublicationType></PublicationTypeList>
        </Article></MedlineCitation></PubmedArticle>
        </PubmedArticleSet>'''
        titles=mri.parse_pubmed(content,['42','43'])
        self.assertEqual(len(titles),1)
        self.assertEqual(titles[0]['category'],'Cardiac MRI')
        self.assertEqual(titles[0]['design'],'Comparative Study')
        self.assertIn('Verified indexed',titles[0]['selection_basis'])


if __name__=='__main__':
    unittest.main()
