import unittest
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
if __name__=='__main__':unittest.main()
