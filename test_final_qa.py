"""Regressions for verified improvements from the final dashboard audit."""
import csv
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

import oecd_imaging as o
import macro_dashboard as macro
from public_build import compact_ai
from test_oecd_imaging import row

ROOT = Path(__file__).parent


class FinalQATests(unittest.TestCase):
    def test_hospital_fallback_is_per_modality_and_never_stitched(self):
        equipment = [row('CHE','HP1','MRI',2024,26.87,'equipment'),
                     row('DEU','HP1','PET_SCAN',2024,1.81,'equipment'),
                     row('DEU','_T','MRI',2023,37.1,'equipment'),
                     row('DEU','HP1','MRI',2024,13.51,'equipment')]
        with patch.object(o,'_request_csv',side_effect=lambda url:
                          equipment if 'DF_MED_TECH' in url else []):
            data=o.fetch()
        che=data['countries']['CHE']['equipment']
        self.assertEqual(che['series']['MRI'][0]['value'],26.87)
        self.assertIn('Hospitals only',che['scope_by_modality']['MRI'])
        deu=data['countries']['DEU']['equipment']
        self.assertEqual(deu['provider_by_modality']['PET'],'HP1')
        self.assertEqual(deu['series']['MRI'],[{'year':2023,'value':37.1,'flags':[]}])

    def test_source_flags_survive_collection_and_absent_flags_are_not_estimates(self):
        first=row('FRA','_T','MRI',2023,19,'equipment')
        first.update(OBS_STATUS='E',OBS_STATUS2='D')
        second=row('FRA','_T','MRI',2024,20,'equipment')
        with patch.object(o,'_request_csv',side_effect=lambda url:
                          [first,second] if 'DF_MED_TECH' in url else []):
            data=o.fetch()
        points=data['countries']['FRA']['equipment']['series']['MRI']
        self.assertEqual(points[0]['flags'],['D','E'])
        self.assertEqual(points[1]['flags'],[])
        self.assertEqual(data['flag_labels']['E'],'Source estimate')

    def test_scale_checks_flag_without_discarding_source_values(self):
        points=[{'year':2023,'value':40},{'year':2024,'value':800}]
        original=json.loads(json.dumps(points))
        notes=o.review_series(points,'equipment','CT')
        self.assertTrue(any('unusually large' in x for x in notes))
        self.assertTrue(any('50%' in x for x in notes))
        self.assertEqual(points,original)
        self.assertEqual(o.review_series([{'year':2023,'value':119.8}], 'equipment','CT'),[])
        self.assertEqual(o.review_series([{'year':2023,'value':0},{'year':2025,'value':10}], 'equipment','PET'),[])

    def test_recent_break_or_outlier_withholds_scenario_not_reported_points(self):
        import ct_dashboard,mri_dashboard,pet_dashboard
        points=[{'year':2021+i,'value':20+i} for i in range(4)]
        for module,method in [(ct_dashboard,'ct_trend_scenario'),
                              (mri_dashboard,'mri_trend_scenario'),
                              (pet_dashboard,'pet_trend_scenario')]:
            sample=json.loads(json.dumps(points));sample[-1]['flags']=['B']
            result=getattr(module,method)(sample,'equipment')
            self.assertEqual(result['status'],'unavailable')
            self.assertIn('source flags',result['reason'])
            self.assertEqual(sample[-1]['value'],23)

    def test_packaging_preserves_all_public_rendering_inputs(self):
        html=(ROOT/'ai.html').read_text()
        before=re.search(r'<script id="ai-data" type="application/json">(.*?)</script>',html,re.S)[1]
        compact=compact_ai(html)
        after=re.search(r'<script id="ai-data" type="application/json">(.*?)</script>',compact,re.S)[1]
        self.assertEqual(before,after)
        self.assertNotIn('id="dashboard-data"',compact)
        self.assertIn('View annual and year-to-date values',compact)
        self.assertLess(len(compact),len(html)*.65)
        with self.assertRaises(ValueError):compact_ai(compact)

    def test_risk_integrity_is_not_mistaken_for_calibration_verification(self):
        risk=macro.read_risk(ROOT)
        self.assertEqual(risk['integrity_status'],'passed')
        self.assertEqual(risk['calibration_status'],'unverified')
        self.assertIn('not supplied',risk['calibration_note'])

    def test_risk_raw_ranking_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            original=(ROOT/'risk-data.csv').read_text()
            rows=list(csv.DictReader(io.StringIO(original)))
            rows[0]['Geopolitical tension | raw']='9999'
            output=io.StringIO();writer=csv.DictWriter(output,fieldnames=list(rows[0]))
            writer.writeheader();writer.writerows(rows)
            (Path(directory)/'risk-data.csv').write_text(output.getvalue())
            shutil.copy(ROOT/'risk.svg',directory)
            with self.assertRaisesRegex(ValueError,'ordering'):
                macro.read_risk(directory)


if __name__=='__main__':unittest.main()
