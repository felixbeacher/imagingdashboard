import unittest
from datetime import date
from unittest.mock import patch
from pathlib import Path
import ai_update_data as ai
import macro_dashboard as macro
class FinancingTests(unittest.TestCase):
 def test_offline_does_not_fetch(self):
  with patch.object(ai,'us_financing') as f,patch.object(ai,'us_medical_inflation') as c:
   values=ai.financing_background(True)
  f.assert_not_called();c.assert_not_called()
  self.assertTrue(all(x['value'] is None and x['retrieved'] is None for x in values))
 def test_failure_is_isolated_and_zero_is_preserved(self):
  with patch.object(ai,'us_financing',side_effect=ValueError('unavailable')),patch.object(ai,'us_medical_inflation',return_value={'value':0,'period':'2026-09','as_of':'2026-10-15'}):
   values=ai.financing_background()
  self.assertIsNone(values[0]['retrieved']);self.assertEqual(values[1]['value'],0)
  self.assertEqual(values[1]['period'],'2026-09');self.assertTrue(values[1]['retrieved'])
 def test_nonfinite_value_rejected(self):
  with patch.object(ai,'us_financing',return_value={'value':float('nan')}),patch.object(ai,'us_medical_inflation',return_value={'value':float('inf')}):
   values=ai.financing_background()
  self.assertTrue(all(x['value'] is None and x['retrieved'] is None for x in values))
 def test_payload_connects_callback(self):
  with patch.object(ai,'financing_background',return_value=[{'value':3.5}]) as f:
   payload=macro.build_payload(Path(__file__).parent,lambda offline:{},True,f)
  f.assert_called_once_with(True);self.assertEqual(payload['financing'][0]['value'],3.5)

 def test_medical_inflation_has_real_yoy_history_with_no_filled_gaps(self):
  year=date.today().year
  # Four prior years let the published CPI produce a three-year YoY timeline.
  rows=[dict(year=str(y),period=f'M{m:02d}',value=str(400+(y-(year-4))*12+m))
        for y in range(year-4,year+1) for m in range(1,13)
        if date(y,m,1)<=date.today() and not (y==year-2 and m==6)]
  response={'status':'REQUEST_SUCCEEDED','Results':{'series':[{'seriesID':'CUUR0000SAM','data':rows}]}}
  with patch.object(ai,'public_json',return_value=response) as api:
   value=ai.us_medical_inflation()
  self.assertTrue(2<=len(value['history'])<=36)
  self.assertTrue(all(point['month']!=f'{year-2}-06' for point in value['history']))
  self.assertEqual(value['history'][-1]['month'],value['period'])
  self.assertIn('startyear=',api.call_args.args[0])
  self.assertEqual(value['history'][-1]['value'],round(value['value'],4))

 def test_federal_funds_monthly_average_is_labelled_and_validated(self):
  today=date.today()
  months=[]
  for delta in range(15):
   year=today.year-(today.month<=delta)
   month=(today.month-delta-1)%12+1
   # This explicitly constructs publication dates in each calendar month.
   year=today.year+(today.month-1-delta)//12
   months.append((year,month))
  rows=[]
  for year,month in months:
   for value,day in [(3.5,1),(4.5,2)]:
    # If day two is in the future this month, omit it.
    if date(year,month,day)<=today:
     rows.append(dict(type='EFFR',effectiveDate=date(year,month,day).isoformat(),percentRate=value))
  with patch.object(ai,'public_json',return_value={'refRates':rows}):
   history=ai.us_funds_history()
  self.assertGreaterEqual(len(history),12)
  self.assertEqual(history[-1]['month'],f'{today.year}-{today.month:02d}')
  self.assertAlmostEqual(history[-1]['value'],4.0 if today.day>=2 else 3.5)

 def test_latest_rate_survives_history_source_failure(self):
  today=date.today().isoformat()
  def fetch(url):
   if '/last/1.json' in url:
    return {'refRates':[{'type':'EFFR','effectiveDate':today,'percentRate':3.2}]}
   raise ValueError('history unavailable')
  with patch.object(ai,'public_json',side_effect=fetch):
   value=ai.us_financing()
  self.assertEqual(value['value'],3.2)
  self.assertEqual(value['history'],[])
  self.assertIn('could not be checked',value['history_note'])

 def test_trend_charts_and_source_rebuild_are_present(self):
  root=Path(__file__).parent
  for name in ('global-macro.html','global-macro.template.html'):
   page=(root/name).read_text(encoding='utf-8')
   self.assertIn('class="financing-indicator-grid"',page)
   self.assertIn('card.append(financeTrend(m,rate))',page)
   self.assertNotIn('id="financing-trends"',page)
   self.assertIn('function financeTrend(',page)
   self.assertIn('See exact monthly figures',page)
   self.assertIn('year earlier',page)
  flow=(root/'.github/workflows/weekly.yml').read_text(encoding='utf-8')
  self.assertIn('publish_macro(output, root',flow)

if __name__=='__main__':unittest.main()
