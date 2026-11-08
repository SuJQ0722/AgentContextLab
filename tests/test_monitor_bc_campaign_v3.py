import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import monitor_bc_campaign_v3 as monitor


class RawAccountingTests(unittest.TestCase):
    def test_unknown_cache_is_not_zero_and_zero_is_known(self):
        result = monitor.aggregate([
            {'raw_provider_usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}},
            {'raw_provider_usage': {'prompt_tokens': 8, 'completion_tokens': 1, 'total_tokens': 9, 'prompt_tokens_details': {'cached_tokens': 0}}},
            {'raw_provider_usage': {'prompt_tokens': 4, 'completion_tokens': None, 'total_tokens': None, 'prompt_tokens_details': {'cached_tokens': None}}},
        ])
        fields = result['fields']
        self.assertEqual(fields['prompt']['complete_total'], 22)
        self.assertEqual(fields['cached_input']['known_count'], 1)
        self.assertEqual(fields['cached_input']['known_subtotal'], 0)
        self.assertEqual(fields['cached_input']['missing_count'], 2)
        self.assertIsNone(fields['cached_input']['complete_total'])
        self.assertEqual(fields['noncache_input']['known_subtotal'], 8)
        self.assertEqual(fields['total']['known_subtotal'], 21)
        self.assertIsNone(fields['total']['complete_total'])

    def test_conservation_is_per_request_and_conflicts_are_unknown(self):
        values, errors = monitor.analyze_usage({'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 13,
                                               'prompt_cache_hit_tokens': 4, 'prompt_cache_miss_tokens': 7})
        self.assertIn('cache_split_not_conserved', errors)
        self.assertIn('prompt_output_total_not_conserved', errors)
        self.assertIsNone(values['cached_input'])
        values, errors = monitor.analyze_usage({'prompt_tokens': 10, 'input_tokens': 11, 'prompt_cache_hit_tokens': 0})
        self.assertIsNone(values['prompt'])
        self.assertIsNone(values['noncache_input'])
        self.assertIn('prompt_invalid_or_conflicting', errors)

    def test_raw_http_wins_dedup_final_inflight_and_summary(self):
        with tempfile.TemporaryDirectory() as td:
            metrics = Path(td); (metrics / 'wire').mkdir()
            def write(path, rows):
                path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
            raw = {'request_id': 'a', 'purpose': 'agent', 'response_complete': True,
                   'raw_provider_usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12,
                                          'prompt_tokens_details': {'cached_tokens': 0}}}
            write(metrics / 'wire/raw-usage.jsonl', [
                {'request_id': 'a', 'event': 'response_started'}, raw, raw,
                {'request_id': 'b', 'purpose': 'compaction', 'event': 'response_started'},
                {'request_id': 'c', 'purpose': 'compaction', 'response_complete': False,
                 'raw_provider_usage': {'prompt_tokens': 500, 'completion_tokens': 999}},
            ])
            write(metrics / 'calls.jsonl', [{'call_id': 'sdk-a', 'usage': {'inputTokens': 1000000},
                                            'client_stream_seconds': 2}])
            issues = []
            rows, states, purposes, latency = monitor.accounting(metrics, 'dsh', issues)
            self.assertEqual(len(rows), 3)
            self.assertEqual(states['http_terminal'], 2)
            self.assertEqual(states['http_response_inflight'], 1)
            self.assertEqual(monitor.aggregate(rows)['fields']['prompt']['known_subtotal'], 10)
            self.assertEqual(purposes['compaction']['fields']['prompt']['missing_count'], 2)
            self.assertEqual(latency['sdk_client_seconds_known_subtotal'], 2)
            self.assertEqual(issues, [])

    def test_missing_raw_cannot_use_normalized_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            metrics = Path(td)
            (metrics / 'calls.jsonl').write_text(json.dumps({'call_id': 'a', 'usage': {'inputTokens': 9, 'cacheReadTokens': 0}}) + '\n')
            issues = []
            rows, _, _, _ = monitor.accounting(metrics, 'dsh', issues)
            self.assertIsNone(monitor.aggregate(rows)['fields']['prompt']['complete_total'])
            self.assertEqual(monitor.aggregate(rows)['fields']['prompt']['missing_count'], 1)
            self.assertEqual(issues[0]['kind'], 'missing_raw_http_usage')

    def test_sent_before_headers_is_unknown_without_double_counting_finished_requests(self):
        with tempfile.TemporaryDirectory() as td:
            metrics = Path(td); (metrics / 'wire').mkdir()
            def write(name, rows):
                (metrics / 'wire' / name).write_text(''.join(json.dumps(r)+'\n' for r in rows))
            write('requests.jsonl', [{'request_id': key, 'request_sent': True} for key in ['a', 'b']] +
                  [{'request_id': 'blocked', 'request_sent': False, 'guard_error': 'not sent'}])
            write('raw-usage.jsonl', [{'request_id': 'a', 'event': 'response_started'},
                  {'request_id': 'a', 'purpose': 'agent', 'response_complete': True,
                   'raw_provider_usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12,
                                          'prompt_tokens_details': {'cached_tokens': 0}}}])
            rows, states, _, _ = monitor.accounting(metrics, 'dsh', [])
            totals = monitor.aggregate(rows)
            self.assertEqual(len(rows), 2)
            self.assertEqual(states['http_sent_without_response'], 1)
            self.assertEqual(totals['fields']['total']['known_subtotal'], 12)
            self.assertEqual(totals['fields']['total']['missing_count'], 1)
            self.assertIsNone(totals['fields']['total']['complete_total'])
            # Also preserve the missing first-ever response, without duplicating SDK starts.
            (metrics / 'wire/raw-usage.jsonl').unlink()
            rows, _, _, _ = monitor.accounting(metrics, 'dsh', [])
            self.assertEqual(len(rows), 2)


if __name__ == '__main__': unittest.main()
