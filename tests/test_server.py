"""MCP server checks: filter resolution, describe_dataset and tool annotations.

The first classes run without a database (known values are mocked). The full-corpus
checks are read-only; opt in with LOADER_DB_TESTS=1.
"""
import asyncio
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import server  # noqa: E402

KNOWN = {
    'level': ['FATAL', 'INFO'],
    'component': ['APP', 'KERNEL'],
    'team': ['Compute Platform', 'Network'],
    'label': ['-', 'APPREAD', 'APPRES'],
}


def fake_known_values(dataset, name):
    return KNOWN[name]


def no_database(*args, **kwargs):
    raise AssertionError('database must not be queried')


@patch.object(server, 'known_values', side_effect=fake_known_values)
class ResolveFilterTests(unittest.TestCase):
    def test_exact_values_pass_unchanged(self, known):
        resolved, normalized = server.resolve_filters('bgl', level='FATAL', label='-')
        self.assertEqual(resolved, {'level': 'FATAL', 'label': '-'})
        self.assertEqual(normalized, {})

    def test_case_is_corrected_and_reported(self, known):
        resolved, normalized = server.resolve_filters(
            'bgl', component='kernel', team='network', label='appread')
        self.assertEqual(resolved, {'component': 'KERNEL', 'team': 'Network', 'label': 'APPREAD'})
        self.assertEqual(normalized['label'], 'appread -> APPREAD')
        self.assertEqual(set(normalized), {'component', 'team', 'label'})

    def test_missing_filters_are_not_looked_up(self, known):
        resolved, normalized = server.resolve_filters('bgl', component=None, level='')
        self.assertEqual(resolved, {'component': None, 'level': ''})
        self.assertEqual(normalized, {})
        known.assert_not_called()

    def test_typo_suggests_close_values(self, known):
        with self.assertRaises(server.FilterError) as ctx:
            server.resolve_filters('bgl', label='APREAD')
        self.assertIn("unknown label 'APREAD' in bgl", str(ctx.exception))
        self.assertIn('did you mean: APPREAD', str(ctx.exception))

    def test_unrelated_value_lists_all_values(self, known):
        with self.assertRaises(server.FilterError) as ctx:
            server.resolve_filters('bgl', component='xyz')
        self.assertIn('valid values: APP, KERNEL', str(ctx.exception))

    def test_unknown_value_is_not_checkable_before_any_count(self, known):
        with patch.object(server, 'run_query', side_effect=no_database):
            for result in (server.count_by('bgl', 'label', component='KERNL'),
                           server.trend('bgl', 'day', level='WARN'),
                           server.search_logs('bgl', 'ciod', team='Networks')):
                ev = result['evidence']
                self.assertEqual(ev['status'], 'not_checkable', ev)
                self.assertIn('unknown', ev['reason'])
                self.assertIsNone(ev['rows_matched'])
                self.assertEqual(result['results'], [])

    def test_known_filter_without_matches_is_empty_in_every_analysis_tool(self, known):
        # The label exists globally, but the requested time range has no lines.
        # It must not be mistaken for an unknown value or a failed measurement.
        with patch.object(server, 'run_query', return_value=[{'n': 0, 'groups': 0, 'buckets': 0}]):
            results = [
                server.count_by('bgl', 'label', label='appread', from_ts='2100-01-01'),
                server.trend('bgl', 'day', label='appread', from_ts='2100-01-01'),
                server.search_logs('bgl', 'prefix', label='appread', from_ts='2100-01-01'),
            ]
        for result in results:
            with self.subTest(tool=result['evidence']['tool']):
                ev = result['evidence']
                self.assertEqual(ev['status'], 'empty')
                self.assertEqual(ev['rows_matched'], 0)
                self.assertEqual(ev['rows_returned'], 0)
                self.assertFalse(ev['truncated'])
                self.assertEqual(ev['normalized_filters']['label'], 'appread -> APPREAD')
                self.assertEqual(ev['params']['label'], 'appread')
                self.assertEqual(result['results'], [])


class ToolListTests(unittest.TestCase):
    def test_every_tool_is_read_only_with_title(self):
        tools = asyncio.run(server.mcp.list_tools())
        self.assertEqual(
            {t.name for t in tools},
            {'ping', 'describe_dataset', 'search_logs', 'nearby_events', 'count_by', 'trend'})
        for tool in tools:
            self.assertTrue(tool.annotations.read_only_hint, tool.name)
            self.assertFalse(tool.annotations.destructive_hint, tool.name)
            self.assertTrue(tool.annotations.idempotent_hint, tool.name)
            self.assertFalse(tool.annotations.open_world_hint, tool.name)
            self.assertTrue(tool.title, tool.name)

    def test_unknown_dataset(self):
        ev = server.describe_dataset('foo')['evidence']
        self.assertEqual(ev['status'], 'not_checkable')
        self.assertIn('unknown dataset', ev['reason'])


@unittest.skipUnless(os.getenv('LOADER_DB_TESTS') == '1', 'requires local full corpus')
class FullCorpusTests(unittest.TestCase):
    def values(self, result, name):
        return {row['value']: row['count'] for row in result['results']['values'][name]}

    def test_describe_bgl(self):
        result = server.describe_dataset('bgl')
        res, ev = result['results'], result['evidence']
        self.assertEqual(ev['status'], 'ok')
        self.assertEqual(ev['rows_matched'], 4747963)
        self.assertEqual(res['rows'], 4747963)
        self.assertEqual(res['null_timestamp_rows'], 0)
        self.assertTrue(res['first_ts'].startswith('2005-06-03'))
        self.assertTrue(res['last_ts'].startswith('2006-01-04'))
        labels = self.values(result, 'label')
        self.assertEqual(labels['-'], 4399503)
        self.assertEqual(labels['APPREAD'], 5983)
        self.assertEqual(sum(labels.values()), 4747963)
        self.assertEqual(len(self.values(result, 'component')), 10)
        self.assertEqual(sum(self.values(result, 'team').values()), 4747963)
        self.assertEqual(ev['rows_returned'],
                         sum(len(v) for v in res['values'].values()))
        self.assertIn('fictional', result['notes']['team'])
        self.assertIn('node', result['metadata']['count_by_group_by'])
        self.assertNotIn('count_by_group_by', res)

    def test_describe_openstack(self):
        result = server.describe_dataset('openstack')
        res = result['results']
        self.assertEqual(res['rows'], 207820)
        self.assertEqual(self.values(result, 'level'),
                         {'INFO': 204506, 'WARNING': 3118, 'ERROR': 194, 'CRITICAL': 2})
        self.assertEqual(len(self.values(result, 'component')), 12)
        self.assertNotIn('label', res['values'])
        self.assertIn('Not available', result['notes']['label'])

    def test_normalized_filters_give_the_same_counts(self):
        exact = server.count_by('bgl', 'label', label='APPREAD', component='APP')
        loose = server.count_by('bgl', 'label', label='appread', component='app')
        self.assertEqual(loose['results'], exact['results'])
        self.assertEqual(loose['evidence']['rows_matched'], 5983)
        self.assertNotIn('normalized_filters', exact['evidence'])
        self.assertEqual(loose['evidence']['normalized_filters'],
                         {'label': 'appread -> APPREAD', 'component': 'app -> APP'})
        self.assertEqual(loose['evidence']['params']['label'], 'appread')
        self.assertIn('label = APPREAD', loose['evidence']['scope'])

        upper = server.trend('bgl', 'day', level='FATAL', component='KERNEL')['evidence']
        lower = server.trend('bgl', 'day', level='fatal', component='kernel')['evidence']
        for key in ('rows_matched', 'active_buckets', 'peak_bucket', 'peak_count'):
            self.assertEqual(lower[key], upper[key], key)

        hits = server.search_logs('bgl', 'ciod', component='app', limit=3)
        same = server.search_logs('bgl', 'ciod', component='APP', limit=3)
        self.assertEqual(hits['results'], same['results'])
        self.assertEqual(hits['evidence']['normalized_filters'], {'component': 'app -> APP'})

    def test_value_of_other_dataset_is_reported(self):
        ev = server.count_by('openstack', 'component', level='FATAL')['evidence']
        self.assertEqual(ev['status'], 'not_checkable')
        self.assertIn("unknown level 'FATAL' in openstack", ev['reason'])
        self.assertIn('CRITICAL, ERROR, INFO, WARNING', ev['reason'])

    def test_known_label_in_empty_time_range_over_real_database(self):
        for name, call in (
            ('count_by', lambda: server.count_by('bgl', 'label', label='appread', from_ts='2100-01-01')),
            ('trend', lambda: server.trend('bgl', 'day', label='appread', from_ts='2100-01-01')),
            ('search_logs', lambda: server.search_logs('bgl', 'prefix', label='appread', from_ts='2100-01-01')),
        ):
            with self.subTest(tool=name):
                result = call()
                self.assertEqual(result['evidence']['status'], 'empty', result)
                self.assertEqual(result['evidence']['rows_matched'], 0)
                self.assertFalse(result['evidence']['truncated'])
                self.assertEqual(result['results'], [])


if __name__ == '__main__':
    unittest.main()
