import importlib.util, unittest, copy, json
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('public_ai',Path(__file__).parent/'ai_update_data.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PublicSourceTests(unittest.TestCase):
 def test_offline_never_contacts_public_sources(self):
  with patch.object(m,'public_json') as fetch:
   d=m.automatic_observations('ct',True)
  fetch.assert_not_called();self.assertTrue(all(not r['metrics'] and not r['context'] for r in d.values()))
 def test_curated_priority_zero_withholding_and_null_fill(self):
  automatic={'global':{'metrics':{'a':{'value':7},'b':{'value':8},'c':{'value':9},'d':{'value':10}},'context':{}}}
  curated={'regions':{'global':{'metrics':{'a':{'value':0},'b':{'value':None},'c':{'value':None,'automatic':False},'d':{'value':'invalid'}}}}}
  out=m.merge_automatic(curated,automatic)['regions']['global']['metrics']
  self.assertEqual(out['a']['value'],0);self.assertEqual(out['b']['value'],8);self.assertIsNone(out['c']['value']);self.assertEqual(out['d']['value'],'invalid')
  self.assertIsNone(curated['regions']['global']['metrics']['b']['value'])
 def test_country_latest_values_and_unweighted_median(self):
  def row(country,year,value):return dict(SpatialDimType='COUNTRY',SpatialDim=country,TimeDim=year,NumericValue=value)
  rows=[row('USA',2010,999),row('USA',2021,10),row('CAN',2019,30),row('BRA',2021,100),row('XYZ',2021,-1)]
  with patch.object(m,'public_json',return_value={'value':rows}):d=m.who_capacity('ct')
  self.assertEqual(d['northAmerica']['value'],20);self.assertEqual(d['global']['value'],30)
  self.assertEqual(len(d['global']['country_observations']),3)
  self.assertIn('2019-01-01',d['northAmerica']['period']);self.assertIn('not scanners divided',d['global']['methodology'])
 def test_conflicting_or_truncated_who_data_withheld(self):
  rows=[dict(SpatialDimType='COUNTRY',SpatialDim='USA',TimeDim=2021,NumericValue=v) for v in (1,2)]
  for response in ({'value':rows},{'value':[],'@odata.nextLink':'more'}):
   with patch.object(m,'public_json',return_value=response):d=m.who_capacity('mri')
   self.assertTrue(all(x['value'] is None for x in d.values()))
 def test_valid_registry_zero_and_global_scope(self):
  with patch.object(m,'public_json',return_value={'totalCount':0,'studies':[]}):d=m.trial_observations('ai')
  self.assertTrue(all(v['value']==0 for v in d.values()))
  self.assertNotIn('LocationCountry',d['global']['query_url']);self.assertIn('LocationCountry',d['europe']['query_url'])
 def test_invalid_registry_response_never_becomes_zero(self):
  for response in ({'studies':[]},{'totalCount':True,'studies':[]},{'totalCount':2,'studies':[]}):
   with patch.object(m,'public_json',return_value=response):d=m.trial_observations('pet')
   self.assertTrue(all(v['value'] is None for v in d.values()))
 def test_cpi_same_month_yoy_and_missing_values(self):
  points=[dict(year='2026',period='M08',value='510'),dict(year='2025',period='M08',value='500'),dict(year='2025',period='M10',value='-'),dict(year='2026',period='M13',value='999')]
  response={'status':'REQUEST_SUCCEEDED','Results':{'series':[{'seriesID':'CUUR0000SAM','data':points}]}}
  with patch.object(m,'public_json',return_value=response):d=m.us_medical_inflation()
  self.assertAlmostEqual(d['value'],2);self.assertEqual(d['period'],'2026-08');self.assertIn('not hospital input',d['methodology'])
  response['Results']['series'][0]['data'].pop(1)
  with patch.object(m,'public_json',return_value=response),self.assertRaises(ValueError):m.us_medical_inflation()
 def test_one_source_failure_does_not_erase_others(self):
  trials={'global':{'value':0}};capacity={'global':{'value':5}}
  with patch.object(m,'trial_observations',return_value=trials),patch.object(m,'who_capacity',return_value=capacity),patch.object(m,'us_financing',side_effect=ValueError('blocked')),patch.object(m,'us_medical_inflation',return_value={'value':2}):
   d=m.automatic_observations('ct')
  self.assertEqual(d['global']['metrics']['prospective_studies']['value'],0);self.assertEqual(d['global']['metrics']['systems_density']['value'],5)
  self.assertIsNone(d['global']['context']['policy_rate']['value']);self.assertEqual(d['global']['context']['inflation']['value'],2)
  self.assertFalse(d['europe']['context'])
if __name__=='__main__':unittest.main()
