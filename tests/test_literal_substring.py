"""Read-only literal-substring regressions; opt in with LOADER_DB_TESTS=1."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import server  # noqa: E402


@unittest.skipUnless(os.getenv('LOADER_DB_TESTS') == '1', 'requires local full corpus')
class LiteralSubstringTests(unittest.TestCase):
    def test_special_characters_are_literal(self):
        # Evaluate the actual filter against tiny synthetic rows, without writes.
        cases = [
            ('%', 'load 50%', True), ('%', 'load 50', False),
            ('_', 'image_cache', True), ('_', 'imageXcache', False),
            ('!_%', 'literal !_% marker', True), ('!_%', 'literal !xy marker', False),
            ('\\', 'path\\file', True), ('\\', 'path/file', False),
            ('ERROR', 'an Error occurred', True), ('ERROR', 'all clear', False),
        ]
        for needle, message, expected in cases:
            with self.subTest(needle=needle, message=message):
                where, params, _ = server.build_where('openstack', text=needle)
                rows = server.run_query(
                    'SELECT COUNT(*) AS n FROM (SELECT %(message)s AS message) t ' + where,
                    {**params, 'message': message})
                self.assertEqual(rows[0]['n'], int(expected))

    def test_both_tools_count_literal_percent_and_underscore(self):
        # Independent reference counts from the original OpenStack corpus.
        for text, expected in [('%', 353), ('_', 68792)]:
            with self.subTest(text=text):
                counted = server.count_by('openstack', 'level', text=text)
                trended = server.trend('openstack', 'day', text=text)
                for result in [counted, trended]:
                    self.assertEqual(result['evidence']['status'], 'ok', result)
                    self.assertEqual(result['evidence']['rows_matched'], expected)
                    self.assertFalse(result['evidence']['truncated'])
                    self.assertEqual(sum(row['count'] for row in result['results']), expected)

    def test_ordinary_text_matches_previous_substring_behavior(self):
        text = 'Error during ComputeManager'
        params = {'text': '%' + text.lower() + '%'}
        old_counts = server.run_query(
            'SELECT level AS key, COUNT(*) AS count FROM openstack_logs '
            'WHERE LOWER(message) LIKE %(text)s GROUP BY level ORDER BY count DESC', params)
        old_trend = server.run_query(
            "SELECT date_trunc('day', ts) AS bucket_start, COUNT(*) AS count "
            'FROM openstack_logs WHERE LOWER(message) LIKE %(text)s '
            "GROUP BY date_trunc('day', ts) ORDER BY bucket_start", params)
        counted = server.count_by('openstack', 'level', text=text)
        trended = server.trend('openstack', 'day', text=text)
        self.assertEqual(counted['evidence']['status'], 'ok', counted)
        self.assertEqual(trended['evidence']['status'], 'ok', trended)
        self.assertEqual(counted['results'], server.clean_rows(old_counts))
        self.assertEqual(trended['results'], server.clean_rows(old_trend))
        self.assertEqual(counted['evidence']['rows_matched'], 8)
        self.assertEqual(trended['evidence']['rows_matched'], 8)


if __name__ == '__main__':
    unittest.main()
