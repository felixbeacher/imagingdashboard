import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
import eudamed


class EudamedTests(unittest.TestCase):
    def test_wrong_search_membership_cannot_inflate_sample(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            eudamed.normalise([{'TRADE_NAME': 'Unrelated product', 'PRIMARY_DI': '123'}],
                              'qXR', {}, 'https://example.org', '2026-10-25')

    def test_failure_keeps_source_date_and_never_becomes_zero(self):
        old = dict(trade_name='qXR', udi_di='123', retrieved_at='2026-09-01T00:00:00Z')
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)/'cache.json'
            cache.write_text(json.dumps({'items': [old]}))
            def failed(url):
                raise TimeoutError('source failed')
            result = eudamed.collect(fetch=failed, cached_path=cache)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['items'][0]['retrieved_at'], old['retrieved_at'])
        self.assertTrue(all(row['records'] is None for row in result['searches']))

    def test_no_match_is_zero_query_results_not_zero_eu_approvals(self):
        with tempfile.TemporaryDirectory() as directory:
            result = eudamed.collect(fetch=lambda url: [], cached_path=Path(directory)/'none.json')
        self.assertEqual(result['items'], [])
        self.assertTrue(all(row['records'] == 0 for row in result['searches']))
        rendered = eudamed.render(result)
        self.assertIn('No match does not establish', rendered)
        self.assertNotIn('0 approvals', rendered)

    def test_eu_section_survives_ai_rebuild_alongside_us_benchmark(self):
        import ai_update_data as ai
        template = Path(__file__).with_name('ai.template.html').read_text()
        payload = ai.build_dashboard(offline=True)
        rendered = ai.render_dashboard(template, payload)
        self.assertEqual(rendered.count('id="eu-regulatory-section"'), 1)
        self.assertEqual(rendered.count('id="fda-trend-section"'), 1)
        self.assertNotIn('<!-- EUDAMED_REGISTRATION_FEED -->', rendered)
        self.assertIn('EUDAMED device registrations', rendered)

    def test_real_device_identifier_deduplication_and_safe_rendering(self):
        def fetch(url):
            params = parse_qs(urlparse(url).query)
            if 'CODE' in params:
                return []
            term = params['TRADE_NAME'][0]
            if term != 'qXR':
                return []
            return [{'TRADE_NAME': term, 'PRIMARY_DI': '123', 'MF_NAME': '<script>bad</script>'}]*2
        with tempfile.TemporaryDirectory() as directory:
            result = eudamed.collect(fetch=fetch, cached_path=Path(directory)/'none.json')
        self.assertEqual(len(result['items']), 1)
        self.assertIn('&lt;script&gt;', eudamed.render(result))
        self.assertNotIn('<script>bad', eudamed.render(result))


class WorldwideDefaultsTests(unittest.TestCase):
    def test_worldwide_groups_are_country_samples_and_not_aggregated_totals(self):
        import ct_dashboard, mri_dashboard, pet_dashboard
        for module in (ct_dashboard, mri_dashboard, pet_dashboard):
            groups = module.REGIONAL_GROUPS
            expected = set().union(*(set(v['countries']) for k,v in groups.items() if k != 'global'))
            self.assertEqual(set(groups['global']['countries']), expected)
