import json
from datetime import datetime,timezone
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from global_valuation import parse_etf,parse_world,fetch,render,validate_history,merge_history,valuation_trend,write_history,read_history

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

    def test_single_latest_valuation_has_no_fake_line_chart(self):
        data={'etf':{'status':'available','pe':{'value':24.72,'period':'2026-10-15'},
                     'pb':{'value':3.89,'period':'2026-10-15'}, 'history':{'pe':[],'pb':[]}}}
        page=render(data)
        self.assertIn('Historical trend not yet available', page)
        self.assertNotIn('2026-10-15: 24.72 times', page)
        self.assertNotIn('verified source observations from', page)

    def test_archive_merges_only_true_observation_dates_and_validates_schema(self):
        earlier={'pe':[{'period':'2026-10-01','value':20.0}],
                 'pb':[{'period':'2026-10-01','value':2.5}]}
        latest={'pe':{'period':'2026-10-15','value':24.72},
                'pb':{'period':'2026-10-15','value':3.89}}
        combined=merge_history(earlier,latest)
        combined=merge_history(combined,latest)
        self.assertEqual(len(combined['pe']),2)
        self.assertEqual(combined['pb'][-1]['value'],3.89)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'history.json'
            write_history(path,combined)
            self.assertEqual(read_history(path),combined)
            corrupted={'source':'Other ETF','observations':combined}
            with self.assertRaises(ValueError):
                validate_history(corrupted)
            with self.assertRaises(ValueError):
                validate_history({'source':'iShares MSCI ACWI ETF fundamentals',
                                  'observations':{'pe':[{'period':'2026-10-15','value':float('nan')}],
                                                  'pb':[]}})

    def test_time_chart_needs_three_real_dates(self):
        series=[{'period':p,'value':v} for p,v in
                [('2026-08-15',20.0),('2026-09-15',22.0),('2026-10-15',23.0)]]
        self.assertEqual(valuation_trend(series[:1], 'P/E'),'')
        self.assertEqual(valuation_trend(series[:2], 'P/E'),'')
        svg=valuation_trend(series,'P/E')
        self.assertIn('2026-10-15',svg)
        self.assertIn('2026-08',svg)

    @patch('global_valuation.urlopen')
    def test_rank_excludes_latest_and_counts_ties(self,call):
        rows=[dict(countryiso3code='WLD',indicator=dict(id='CM.MKT.LCAP.GD.ZS'),date=str(2000+i),value=100 if i==10 else 50+i*10) for i in range(11)]
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps([dict(pages=1),rows]).encode()
        call.side_effect=[TimeoutError(),response]
        result=fetch()['buffett']
        self.assertEqual(result['comparison_count'],10)
        self.assertEqual(result['percentile'],55)
        self.assertEqual(result['status'],'available')
