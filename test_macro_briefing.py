import json
import unittest
from unittest.mock import patch, MagicMock
from macro_briefing import briefings


class BriefingTests(unittest.TestCase):
    def setUp(self):
        self.payload = dict(generated_at='2026-10-16T12:00:00Z',
            economics={k:dict(cards=[dict(label='Growth',value=3.1,period='2026',source=dict(name='IMF',url='https://www.imf.org'))]) for k in ('global','europe')},
            risk=dict(end='2026-09-01',latest=50,change=2,components=[]))

    def response(self, entry=None):
        entry = entry or dict(summary='Growth remains positive in the supplied estimates.',implication='Investment may depend on local procurement budgets.',uncertainty='Historical risk does not describe current conditions.',source_ids=['econ0','risk'])
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps(dict(candidates=[dict(finishReason='STOP',content=dict(parts=[dict(text=json.dumps({k:entry for k in self.payload['economics']}))]))])).encode()
        return response

    @patch.dict('os.environ',{},clear=True)
    @patch('macro_briefing.urlopen')
    def test_missing_key_and_offline_never_call_provider(self, call):
        self.assertEqual(briefings(self.payload)['status'],'not_configured')
        with patch.dict('os.environ',{'GEMINI_API_KEY':'private'}):
            self.assertEqual(briefings(self.payload,True)['status'],'offline')
        call.assert_not_called()

    @patch.dict('os.environ',{'GEMINI_API_KEY':'private'},clear=True)
    @patch('macro_briefing.urlopen')
    def test_single_call_all_regions_and_no_secret_published(self, call):
        call.return_value=self.response()
        result=briefings(self.payload)
        self.assertEqual(result['status'],'generated')
        self.assertEqual(set(result['regions']),{'global','europe'})
        self.assertNotIn('private',json.dumps(result))
        self.assertNotIn('private',call.call_args.args[0].full_url)
        self.assertEqual(call.call_count,1)

    @patch.dict('os.environ',{'GEMINI_API_KEY':'private'},clear=True)
    @patch('macro_briefing.urlopen')
    def test_bad_citation_or_numbers_falls_back(self,call):
        for summary,ids in [('Growth is 999%.',['econ0']),('Growth is positive.',['invented'])]:
            call.return_value=self.response(dict(summary=summary,implication='May affect investment.',uncertainty='Limited evidence.',source_ids=ids))
            result=briefings(self.payload)
            self.assertEqual(result['status'],'unavailable')
            self.assertIsNone(result['generated_at'])
            self.assertIn('3.1%',result['regions']['global']['summary'])

    @patch.dict('os.environ',{'GEMINI_API_KEY':'private'},clear=True)
    @patch('macro_briefing.urlopen',side_effect=TimeoutError)
    def test_timeout_preserves_data_summary(self,call):
        self.assertEqual(briefings(self.payload)['status'],'unavailable')

if __name__=='__main__':unittest.main()
