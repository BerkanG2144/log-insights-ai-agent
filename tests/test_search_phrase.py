"""Read-only full-corpus regression checks; opt in with LOADER_DB_TESTS=1."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest

SERVER = Path(__file__).resolve().parents[1] / 'server'
sys.path.insert(0, str(SERVER))
spec = importlib.util.spec_from_file_location('phrase_test_server', SERVER / 'server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


@unittest.skipUnless(os.getenv('LOADER_DB_TESTS') == '1', 'requires local full corpus')
class PhraseSearchTests(unittest.TestCase):
    def search(self, dataset, text, **kwargs):
        result = server.search_logs(dataset, text, **kwargs)
        self.assertEqual(result['evidence']['status'], 'ok', result)
        self.assertTrue(result['results'])
        self.assertIn('score', result['results'][0])
        return result

    def test_appread_phrase_and_label(self):
        text = 'failed to read message prefix'
        for filters in ({}, {'label': 'APPREAD'}):
            result = self.search('bgl', text, phrase=True, limit=2, **filters)
            ev = result['evidence']
            self.assertEqual(ev['rows_matched'], 5983)
            self.assertEqual(ev['rows_returned'], 2)
            self.assertTrue(ev['truncated'])
            self.assertTrue(ev['params']['phrase'])
            self.assertIn('phraseto_tsquery', ev['sql'])
            self.assertIn('adjacent ordered tokens', ev['scope'])
        self.assertEqual(server.count_by('bgl', 'label', label='APPREAD')['results'][0]['count'], 5983)

    def test_default_word_search_and_openstack_phrase(self):
        text = 'Error during ComputeManager'
        default = self.search('openstack', text)
        explicit = self.search('openstack', text, phrase=False)
        self.assertEqual(default['results'], explicit['results'])
        self.assertEqual(default['evidence']['rows_matched'], 4069)
        self.assertNotIn('phraseto_tsquery', default['evidence']['sql'])
        self.assertEqual(self.search('openstack', text, phrase=True)['evidence']['rows_matched'], 8)
        self.assertEqual(self.search('bgl', 'ciod')['evidence']['rows_matched'], 350567)

    def test_order_case_and_literal_input(self):
        self.assertEqual(self.search('bgl', 'FAILED TO READ MESSAGE PREFIX', phrase=True)['evidence']['rows_matched'], 5983)
        for text in ('prefix message read to failed', "zzznomatch' OR 1=1 --"):
            result = server.search_logs('bgl', text, phrase=True)
            self.assertEqual(result['evidence']['status'], 'empty', result)
            self.assertEqual(result['results'], [])


if __name__ == '__main__':
    unittest.main()
