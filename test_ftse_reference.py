import json
from pathlib import Path
import unittest
from unittest.mock import patch
from ftse_reference import render_reference

class ReferenceTests(unittest.TestCase):
    def test_figures_keep_provenance_and_accessible_values(self):
        page=render_reference()
        self.assertEqual(page.count('<figure '),4)
        self.assertEqual(page.count('<figcaption>'),4)
        self.assertIn('34 out of 100',page)
        self.assertIn('illustrative and unverified',page)
        self.assertIn('2022: 9.8',page)
        self.assertLess(page.index('1 · Earnings'),page.index('2 · Asset'))
        self.assertLess(page.index('2 · Asset'),page.index('3 · Broad'))

    def test_invalid_or_mislabelled_reference_cannot_publish(self):
        original=json.loads((Path(__file__).parent/'ftse-reference.json').read_text())
        for alteration in ('status','series'):
            data=json.loads(json.dumps(original))
            if alteration=='status':data['status']='live'
            else:data['series']['pe']=[1]
            with patch('ftse_reference.Path.read_text',return_value=json.dumps(data)):
                with self.assertRaises(ValueError):render_reference()
