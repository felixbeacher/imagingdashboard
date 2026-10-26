"""OECD imaging feed and chart integrity tests; no live networking."""
import unittest
from unittest.mock import patch
import oecd_imaging as o

def row(country,provider,technology,year,value,mode='exams'):
    base={'REF_AREA':country,'TIME_PERIOD':str(year),'OBS_VALUE':str(value),
          'UNIT_MULT':'','OBS_STATUS':''}
    if mode=='exams':
        base.update(MEASURE='EXAM',UNIT_MEASURE='EXM_10P3PS',
                    HEALTH_FACILITY=technology,PROVIDER=provider)
    else:
        base.update(MEASURE='MTU',UNIT_MEASURE='10P6HB',
                    MEDICAL_TECH=technology,HEALTH_CARE_PROVIDER=provider)
    return base

class OECDImagingTests(unittest.TestCase):
    def test_units_modality_and_missing_years(self):
        rows=[row('CHE','HP1','MRI',2019,81.2),row('CHE','HP1','MRI',2021,88.5),
              row('CHE','HP1','CT_SCAN',2019,133.1),
              row('USA','_T','CT_SCAN',2020,258.2)]
        observed=o.parse_rows(rows,'exams')
        self.assertEqual(observed[('CHE','HP1','MRI',2019)],81.2)
        self.assertNotIn(('CHE','HP1','MRI',2020),observed)
        self.assertEqual(observed[('USA','_T','CT',2020)],258.2)
        wrong=row('CHE','HP1','MRI',2022,6.1)
        wrong['UNIT_MEASURE']='10P6HB'
        self.assertNotIn(('CHE','HP1','MRI',2022),o.parse_rows(rows+[wrong],'exams'))

    def test_conflicting_duplicate_observations_are_refused(self):
        with self.assertRaises(ValueError):
            o.parse_rows([row('GBR','_T','CT_SCAN',2022,120),
                          row('GBR','_T','CT_SCAN',2022,150)],'exams')

    def test_country_scope_and_missing_data(self):
        examination_rows=[
            row('CHE','HP1','CT_SCAN',2020,70),
            row('CHE','HP1','CT_SCAN',2022,85),
            row('CHE','HP1','MRI',2020,60),
            row('CHE','_T','MRI',2021,200),
            row('GBR','_T','MRI',2021,80),
            row('GBR','_T','MRI',2022,85)]
        equipment_rows=[
            row('CHE','_T','CT_SCAN',2020,20,'equipment'),
            row('CHE','_T','CT_SCAN',2022,21,'equipment'),
            row('CHE','_T','MRI',2022,15,'equipment'),
            row('GBR','_T','MRI',2020,12,'equipment')]
        def fetch_rows(url):
            return examination_rows if 'DF_DIAG_EXAM' in url else equipment_rows
        with patch.object(o,'_request_csv',side_effect=fetch_rows):
            result=o.fetch()
        self.assertEqual(result['countries']['CHE']['exams']['scope'],
                         'Hospitals only (not all examinations)')
        self.assertEqual([r['year'] for r in result['countries']['CHE']['exams']['series']['CT']],[2020,2022])
        self.assertEqual(result['countries']['CHE']['exams']['series']['MRI'],
                         [{'year':2020,'value':60.0}])
        self.assertIn('Hospitals only',result['countries']['GBR']['exams']['scope'])
        self.assertIn('Public-hospital',result['countries']['GBR']['equipment']['scope'])
        self.assertEqual(result['countries']['CHE']['equipment']['scope'],'All healthcare providers')
        self.assertEqual(result['countries']['JPN']['exams']['status'],'unavailable')

    def test_total_provider_code_does_not_erase_australian_exclusions(self):
        rows = [row('AUS', '_T', 'CT_SCAN', 2023, 170),
                row('AUS', '_T', 'CT_SCAN', 2024, 180)]
        equipment = [row('AUS', '_T', 'CT_SCAN', 2024, 75, 'equipment')]
        with patch.object(o, '_request_csv', side_effect=lambda url:
                          rows if 'DF_DIAG_EXAM' in url else equipment):
            data = o.fetch()['countries']['AUS']
        self.assertIn('Medicare-paid', data['exams']['scope'])
        self.assertIn('public reimbursement', data['equipment']['scope'])
        self.assertEqual(data['exams']['series']['CT'][-1]['value'], 180)
        self.assertEqual(data['equipment']['series']['CT'][-1]['value'], 75)

    def test_offline_no_invented_observations(self):
        with patch.object(o,'_request_csv',side_effect=AssertionError('Network not expected')):
            result=o.fetch(offline=True)
        self.assertTrue(all(not any(c[k]['series'][m] for m in ('CT','MRI','PET'))
                            for c in result['countries'].values() for k in ('exams','equipment')))

    def test_one_source_fails_other_remains_available(self):
        def fetch_rows(url):
            if 'DF_DIAG_EXAM' in url:
                raise TimeoutError('OECD unavailable')
            return [row('CHE','_T','MRI',2020,16.5,'equipment')]
        with patch.object(o,'_request_csv',side_effect=fetch_rows):
            result=o.fetch()
        self.assertEqual(result['countries']['CHE']['exams']['status'],'unavailable')
        self.assertEqual(result['countries']['CHE']['equipment']['status'],'available')

if __name__ == '__main__':
    unittest.main()
