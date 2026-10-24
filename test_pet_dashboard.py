"""PET isolation, missing-data and publication-screening regression checks."""
import copy
from datetime import date
from pathlib import Path
import unittest
import pet_dashboard as pet

class PETTests(unittest.TestCase):
    def test_pet_projection_uses_pet_not_mri(self):
        data=pet.empty_oecd()
        for country in data['countries'].values():
            for mode in ('equipment','exams'):
                country[mode]['series']['PET']=[dict(year=y,value=1+(y-2021)*.1) for y in range(2021,2025)]
                country[mode]['series']['MRI']=[dict(year=2024,value=100)]
        out=pet.generate(today=date(2026,10,24),offline=True,oecd_fetch=lambda **kw:copy.deepcopy(data))
        for country in out['oecd']['countries'].values():
            for mode in ('equipment','exams'):
                self.assertEqual(country[mode]['projection']['status'],'illustrative')
                self.assertLess(country[mode]['projection']['points'][0]['value'],2)

    def test_offline_and_page_integrity(self):
        payload=pet.generate(offline=True)
        self.assertEqual(payload['pubmed']['items'],[])
        self.assertFalse(any(c['equipment']['series']['PET'] for c in payload['oecd']['countries'].values()))
        text=pet.render(Path('pet.template.html').read_text(),payload)
        self.assertNotIn('<!-- PET_DATA -->',text)
        self.assertIn('k.series.PET',text)
        self.assertIn('aria-current="page" href="pet.html"',text)
        self.assertNotIn('magnetic resonance imaging',text)
        self.assertNotIn('renderMarket()',text)

    def test_research_rejects_other_modalities_and_case_reports(self):
        def paper(pmid,title,kind):
            return f'<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article><ArticleTitle>{title}</ArticleTitle><PublicationTypeList><PublicationType>{kind}</PublicationType></PublicationTypeList></Article></MedlineCitation></PubmedArticle>'
        xml='<PubmedArticleSet>'+paper('1','PSMA PET/CT for staging','Comparative Study')+paper('2','MRI for staging','Comparative Study')+paper('3','FDG PET case report','Case Reports')+'</PubmedArticleSet>'
        items=pet.parse_pubmed(xml.encode(),['1','2','3'])
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['url'],'https://pubmed.ncbi.nlm.nih.gov/1/')
