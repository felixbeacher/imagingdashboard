"""Verify X-ray source-backed page, market verification, NHS DID check, and PubMed screening."""
from datetime import date
import json
from pathlib import Path
import re
import unittest
import xray_dashboard as xray

ROOT = Path(__file__).resolve().parent


class XrayTests(unittest.TestCase):
    def test_template_structure_and_offline_render(self):
        template = (ROOT / 'xray.template.html').read_text(encoding='utf-8')
        self.assertEqual(template.count('<!-- XRAY_DATA -->'), 1)
        payload = xray.generate(offline=True, today=date(2026, 11, 11))
        self.assertEqual(payload['pubmed']['status'], 'unavailable')
        self.assertEqual(payload['pubmed']['items'], [])
        self.assertEqual(payload['market']['value_bn'], 8.4)
        self.assertEqual(payload['nhs_did']['latest_finalised'], '2024-25')
        rendered = xray.render(template, payload)
        self.assertNotIn('<!-- XRAY_DATA -->', rendered)
        data = json.loads(re.search(r'<script id="xray-data" type="application/json">([\s\S]*?)</script>', rendered).group(1))
        self.assertEqual(data['market']['value_bn'], 8.4)

    def test_pubmed_screens_case_reports_and_non_xray(self):
        def article(pmid, title, pub_type):
            return (
                f'<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>'
                f'<ArticleTitle>{title}</ArticleTitle>'
                f'<PublicationTypeList><PublicationType>{pub_type}</PublicationType></PublicationTypeList>'
                f'</Article></MedlineCitation></PubmedArticle>'
            )
        xml = (
            '<PubmedArticleSet>'
            + article('1', 'AI triage of chest radiograph in emergency care', 'Randomized Controlled Trial')
            + article('2', 'Computed tomography for lung nodule evaluation', 'Comparative Study')
            + article('3', 'A rare case report on chest x-ray', 'Case Reports')
            + '</PubmedArticleSet>'
        ).encode('utf-8')
        items = xray.parse_pubmed(xml, ['1', '2', '3'])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['url'], 'https://pubmed.ncbi.nlm.nih.gov/1/')
        self.assertEqual(items[0]['category'], 'AI / workflow triage')

    def test_market_and_nhs_did_extract_verified_text(self):
        gvr_html = 'The global x-ray systems market size was valued at USD 8.4 billion in 2024 and is estimated at USD 8.9 billion for 2026.'
        market = xray.check_market(offline=False, today=date(2026, 11, 11), fetcher=lambda _: gvr_html)
        self.assertEqual(market['value_bn'], 8.4)
        self.assertEqual(market['estimate_value_bn'], 8.9)
        self.assertEqual(market['check_status'], 'source figure reverified')

        did_html = 'The statistics for 2012-13 to 2025-26 have now been finalised and are no longer provisional.'
        did = xray.check_nhs_did(offline=False, today=date(2026, 11, 11), fetcher=lambda _: did_html)
        self.assertEqual(did['latest_finalised'], '2025-26')
