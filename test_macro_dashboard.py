import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import macro_dashboard as macro

ROOT=Path(__file__).parent
spec=importlib.util.spec_from_file_location('ai',ROOT/'ai_update_data.py')
ai=importlib.util.module_from_spec(spec);spec.loader.exec_module(ai)

class MacroTests(unittest.TestCase):
    def test_csv_and_svg_match_report(self):
        r=macro.read_risk(ROOT)
        self.assertEqual(r['count'],81);self.assertEqual(r['end'],'2026-09-01')
        self.assertEqual(len(r['components']),5)
        self.assertAlmostEqual(r['latest'],78.717949)
        self.assertEqual(r['peak_month'],'2022-03-01')
    def test_mismatched_chart_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(ROOT/'risk-data.csv',tmp)
            (Path(tmp)/'risk.svg').write_text('<svg/>')
            with self.assertRaisesRegex(ValueError,'do not match'):macro.read_risk(tmp)
    def test_noncontinuous_month_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'risk-data.csv').write_text((ROOT/'risk-data.csv').read_text().replace('2020-02-01','2020-04-01'))
            with self.assertRaisesRegex(ValueError,'continuous'):macro.read_risk(tmp)
    def test_bad_composite_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'risk-data.csv').write_text((ROOT/'risk-data.csv').read_text().replace('49.903846','99.903846'))
            with self.assertRaisesRegex(ValueError,'inconsistent'):macro.read_risk(tmp)
    def test_ai_build_does_not_fetch_imf(self):
        with patch.object(ai,'regional_economic_background',side_effect=AssertionError('IMF called')),patch.object(ai,'fetch_economic_outlook',side_effect=AssertionError('IMF article called')):
            p=ai.build_dashboard(offline=True)
        self.assertNotIn('economic_outlook',p);self.assertNotIn('regional_economics',p)
        view=ai.template_view(p)
        self.assertTrue(all(len(r['metrics'])==4 for r in view['regions'].values()))
        template=ROOT/'ai.template.html'
        if not template.exists():template=ROOT/'ai.html'
        rendered=ai.render_dashboard(template.read_text(),p)
        self.assertNotIn('ai-context-title',rendered);self.assertIn('global-macro.html',rendered)
        self.assertNotIn('_PLACEHOLDER',rendered)
    def test_offline_macro_retains_risk_without_invented_economics(self):
        with patch.object(ai,'public_json',side_effect=AssertionError('Network called')):
            p=macro.build_payload(ROOT,ai.regional_economic_background,True)
        self.assertEqual(p['economic_mode'],'offline');self.assertEqual(p['risk']['count'],81)
        self.assertTrue(all(c['value'] is None for r in p['economics'].values() for c in r['cards']))
    def test_macro_render_escapes_script(self):
        html=macro.render('<script><!-- MACRO_DATA --></script>',{'x':'</script><script>alert(1)</script>'})
        self.assertEqual(html.count('</script>'),1)
    def test_static_publication_copies_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            macro.publish_macro(tmp,ROOT,ai.regional_economic_background,True)
            for name in ['global-macro.html','risk-data.csv','risk.svg','global-risk-report.html']:self.assertTrue((Path(tmp)/name).is_file())
    def test_server_routes_and_safe_asset_allowlist(self):
        template=ROOT/'ai.template.html'
        if not template.exists():template=ROOT/'ai.html'
        service=ai.DashboardService(template,offline=True)
        handler=ai.make_handler(service);request=object.__new__(handler);responses=[]
        request.send_content=lambda status,content,kind:responses.append((status,content,kind))
        for route,kind in [('/global-macro.html','text/html'),('/api/macroeconomics','application/json'),('/risk.svg','image/svg+xml'),('/risk-data.csv','text/csv')]:
            request.path=route;request.do_GET();status,content,ctype=responses.pop();self.assertEqual(status,200);self.assertTrue(ctype.startswith(kind))
        request.path='/macro_dashboard.py';request.do_GET();self.assertEqual(responses.pop()[0],404)
    def test_requested_headings_and_risk_asset(self):
        for name in ['ai.html','ai.template.html']:
            page=(ROOT/name).read_text()
            self.assertIn('Summary: Global Market for Imaging AI',page)
            self.assertNotIn('Description of Region',page)
            self.assertNotIn('ai-context-title',page)
        for name in ['global-macro.html','global-macro.template.html']:
            page=(ROOT/name).read_text()
            self.assertIn('>Glob Econ</a>',page)
            self.assertIn('src="risk.svg"',page)
            self.assertIn('Further information',page);self.assertIn('Why it matters for imaging',page)
    def test_navigation_in_every_tab(self):
        for name in ['ai.html','index.html','ct.html','mri.html','pet.html','xray.html']:
            self.assertIn('href="global-macro.html"',(ROOT/name).read_text())

if __name__=='__main__':unittest.main()
