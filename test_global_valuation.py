import json
from datetime import datetime,timezone
import unittest
from unittest.mock import patch, MagicMock
from global_valuation import parse_etf,parse_world,fetch,render

class GlobalValuationTests(unittest.TestCase):
    def test_fundamentals_require_values_and_dates(self):
        points={k:dict(formattedValue=v,formattedAsOfDate='Oct 15, 2025') for k,v in [('priceEarnings','24.72'),('priceBook','3.89')]}
        obj=json.dumps(dict(componentId='fundamentalsAndRisk',dataPoints=points)).replace('"','&quot;')
        raw='<walrus-render-on-client componentprops="'+obj+'"></walrus-render-on-client>'
        self.assertEqual(parse_etf(raw)['pe']['value'],24.72)
        with self.assertRaises(ValueError):parse_etf(raw.replace('24.72','NaN'))
        with self.assertRaises(ValueError):parse_etf('<html>blocked</html>')
    def test_world_validates_coverage_and_completeness(self):
        row=dict(countryiso3code='WLD',indicator=dict(id='CM.MKT.LCAP.GD.ZS'),date='2024',value=120)
        self.assertEqual(parse_world(json.dumps([dict(pages=1),[row]])),[dict(year=2024,value=120)])
        with self.assertRaises(ValueError):parse_world(json.dumps([dict(pages=2),[row]]))
        row['countryiso3code']='USA'
        with self.assertRaises(ValueError):parse_world(json.dumps([dict(pages=1),[row]]))
    @patch('global_valuation.urlopen')
    def test_offline_no_requests_and_no_fake_score(self,call):
        page=render(fetch(True));call.assert_not_called()
        self.assertIn('Assessment unavailable',page);self.assertNotIn('Undervalued',page)
    @patch('global_valuation.urlopen',side_effect=TimeoutError)
    def test_failures_do_not_receive_retrieval_dates(self,call):
        data=fetch();self.assertEqual(data['etf']['status'],'unavailable');self.assertNotIn('retrieved_at',data['etf']);self.assertNotIn('percentile',data['buffett'])
    def test_percentile_render_discloses_basis(self):
        page=render(dict(buffett=dict(history=[dict(year=2024,value=120)],percentile=95,median=85,comparison_count=20)))
        self.assertIn('Elevated relative to history',page);self.assertIn('does not prove they are overpriced',page)
        self.assertIn('Buffett Indicator',page);self.assertNotIn('Institutional View',page)

    @patch('global_valuation.urlopen')
    def test_rank_excludes_latest_and_counts_ties(self,call):
        rows=[dict(countryiso3code='WLD',indicator=dict(id='CM.MKT.LCAP.GD.ZS'),date=str(2000+i),value=100 if i==10 else 50+i*10) for i in range(11)]
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps([dict(pages=1),rows]).encode()
        call.side_effect=[TimeoutError(),response]
        result=fetch()['buffett']
        self.assertEqual(result['comparison_count'],10)
        self.assertEqual(result['percentile'],55)
        self.assertEqual(result['status'],'available')
