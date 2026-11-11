import io
import json
from datetime import datetime, timezone, date
import unittest
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from global_valuation import (
    parse_etf, parse_world, parse_z1_buffett, fetch, render,
    validate_history, merge_history, valuation_trend, write_history,
    read_history, buffett_gauge,
)


def make_z1_zip(equities, gdp):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        eq_lines = ['date,LM103164105.Q'] + [f'{q},{v}' for q, v in equities]
        gdp_lines = ['date,FU086902005.Q'] + [f'{q},{v}' for q, v in gdp]
        zf.writestr('csv/F51_1_s.csv', '\n'.join(eq_lines))
        zf.writestr('csv/S1_1_i_q.csv', '\n'.join(gdp_lines))
    return buf.getvalue()


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
    def test_z1_buffett_computes_trailing_four_quarter_ratio(self):
        eq, gdp = [], []
        for yr in range(2015, 2026):
            for q in range(1, 5):
                label = f'{yr}:Q{q}'
                gdp.append((label, '2500000'))
                eq.append((label, str(10_000_000 + (yr - 2015) * 1_000_000)))
        for q, val in [(1, '25000000'), (2, '26200000')]:
            gdp.append((f'2026:Q{q}', '2500000'))
            eq.append((f'2026:Q{q}', val))
        raw = make_z1_zip(eq, gdp)
        history = parse_z1_buffett(raw, today=date(2026, 11, 11))
        self.assertEqual(history[-1]['period'], '2026 Q2')
        self.assertAlmostEqual(history[-1]['value'], 262.0)
        self.assertEqual(len(history), 12)
        with self.assertRaises(ValueError):
            parse_z1_buffett(make_z1_zip([('2027:Q1', '100')], [('2027:Q1', '100')]), today=date(2026, 11, 11))
    @patch('global_valuation.urlopen')
    def test_offline_no_requests_and_no_fake_score(self,call):
        page=render(fetch(True));call.assert_not_called()
        self.assertIn('Assessment unavailable',page);self.assertNotIn('Undervalued',page)
    @patch('global_valuation.urlopen',side_effect=TimeoutError)
    def test_failures_do_not_receive_retrieval_dates(self,call):
        data=fetch();self.assertEqual(data['buffett']['status'],'unavailable');self.assertNotIn('retrieved_at',data['buffett']);self.assertNotIn('percentile',data['buffett'])
    def test_percentile_render_discloses_basis(self):
        page=render(dict(buffett=dict(history=[dict(year=2026,period='2026 Q2',value=262.1)],percentile=100,median=130.7,comparison_count=30)))
        self.assertIn('Elevated relative to history',page);self.assertIn('does not prove they are overpriced',page)
        self.assertIn('US Buffett Indicator',page);self.assertNotIn('Institutional View',page)
        self.assertNotIn('Share prices compared with profits and assets',page)

    def test_buffett_gauge_scale_and_historical_median(self):
        page=render(dict(buffett=dict(history=[dict(year=2026,period='2026 Q2',value=262.1)],
                                      percentile=100,median=130.7,comparison_count=30)))
        self.assertIn('262.1%',page)
        self.assertIn('scale 0 to 300% of GDP',page)
        self.assertIn('stroke-dasharray="87.37 100"',page)
        self.assertIn('Historical median 130.7% of GDP',page)
        self.assertIn('100th historical percentile is a separate ranking',page)

    def test_buffett_gauge_extends_beyond_200_if_needed(self):
        svg=buffett_gauge(235.0,95.0,'2026 Q2')
        self.assertIn('scale 0 to 250% of GDP',svg)
        self.assertIn('stroke-dasharray="94.00 100"',svg)

    def test_box_one_and_acwi_are_not_rendered(self):
        page=render(dict(
            buffett=dict(status='available',history=[dict(year=2026,period='2026 Q2',value=262.1)],
                         percentile=100,median=130.7,comparison_count=30)))
        self.assertNotIn('1 · Share prices compared with profits and assets',page)
        self.assertNotIn('Global-equity P/E',page)
        self.assertNotIn('Global CAPE',page)
        self.assertIn('Buffett Indicator — US market cap / GDP',page)
        self.assertIn('mini-charts single',page)

    def test_etf_box_is_omitted_even_if_payload_contains_etf(self):
        data={'etf':{'status':'available','pe':{'value':24.72,'period':'2026-10-15'},
                     'pb':{'value':3.89,'period':'2026-10-15'}, 'history':{'pe':[],'pb':[]}}}
        page=render(data)
        self.assertNotIn('Share prices compared with profits and assets', page)
        self.assertNotIn('24.72', page)
        self.assertNotIn('Global-equity P/E', page)

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
        eq, gdp = [], []
        for yr in range(2015, 2026):
            for q in range(1, 5):
                gdp.append((f'{yr}:Q{q}', '2500000'))
                eq.append((f'{yr}:Q{q}', str((50 + (yr - 2015) * 10) * 100_000)))
        for q in range(1, 3):
            gdp.append((f'2026:Q{q}', '2500000'))
            eq.append((f'2026:Q{q}', str(100 * 100_000)))
        response=MagicMock();response.__enter__.return_value.read.return_value=make_z1_zip(eq, gdp)
        call.return_value=response
        result=fetch()['buffett']
        self.assertEqual(result['comparison_count'],11)
        self.assertEqual(result['percentile'],50.0)
        self.assertEqual(result['status'],'available')
