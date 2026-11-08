import importlib.util
import json
from datetime import datetime, timezone
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


class CloudTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.registry=self.root/'submissions';self.registry.mkdir()
        self.local={'hostname':'local','boot_id':'boot-local','pid_namespace':'pid:[1]'}
        self.counts={'visible_total':11,'visible_live':10,'core_v3_subtree_live':5}
        self.now=1800000000
    def tearDown(self):self.temp.cleanup()
    def submission(self,name='one',state='submitted',**kw):
        (self.registry/(name+'.json')).write_text(json.dumps({'name':name,'state':state,'mode':'live','workers':32,**kw}))
    def node(self,name,hostname='remote',boot='boot-remote',age=0,**kw):
        path=self.root/'runtime/nodes'/name/'telemetry.json';path.parent.mkdir(parents=True)
        value={'schema':'bc-v3-node-telemetry-v1','timestamp':datetime.fromtimestamp(self.now-age,timezone.utc).isoformat(),
               'hostname':hostname,'boot_id':boot,'pid_namespace':'pid:[2]',
               'processes':{'visible_total':21,'visible_live':20,'core_v3_subtree_live':15},**kw}
        path.write_text(json.dumps(value));return path
    def inspect(self,**kw):
        return monitor.node_process_totals(self.root,self.counts,now_unix=self.now,local_identity=self.local,
                                            submissions_root=self.registry,**kw)
    def test_fresh_cloud_coverage_and_worker_concurrency_is_not_node_count(self):
        self.submission(argv=['sco','--worker-nodes','1']);self.node('one')
        cloud,total=self.inspect()
        self.assertEqual(cloud['expected_active_cloud_nodes'],1)
        self.assertTrue(total['complete']);self.assertEqual(total['fields']['visible_live']['complete_total'],30)
        self.assertEqual(self.counts['visible_live'],10)  # Existing local record is untouched.
    def test_missing_cloud_reports_are_unknown_not_zero(self):
        self.submission('one');self.submission('two');self.node('one')
        cloud,total=self.inspect()
        self.assertEqual(cloud['missing_fresh_nodes'],1);self.assertFalse(total['complete'])
        self.assertEqual(total['fields']['visible_live']['known_subtotal'],30)
        self.assertIsNone(total['fields']['visible_live']['complete_total'])
    def test_stale_and_absent_counters_are_not_summed_as_zero(self):
        self.submission();self.node('old',age=91)
        cloud,total=self.inspect();self.assertEqual(cloud['nodes'][0]['status'],'stale')
        self.assertEqual(total['fields']['visible_live']['known_subtotal'],10);self.assertFalse(total['complete'])
        (self.root/'runtime/nodes/old/telemetry.json').unlink()
        self.node('missing',processes={'visible_total':21,'core_v3_subtree_live':15})
        cloud,total=self.inspect();self.assertFalse(total['complete'])
        self.assertEqual(total['fields']['visible_live']['missing_count_nodes'],1)
        self.assertIsNone(total['fields']['visible_live']['complete_total'])
    def test_local_and_duplicate_host_boot_are_not_double_counted(self):
        self.submission();self.node('self','local','boot-local',pid_namespace='pid:[1]')
        self.node('old-copy',age=10,processes={'visible_total':99,'visible_live':99,'core_v3_subtree_live':99})
        self.node('new-copy',age=1)
        cloud,total=self.inspect();self.assertTrue(total['complete'])
        self.assertEqual(total['fields']['visible_live']['complete_total'],30)
        self.assertEqual({n['status'] for n in cloud['nodes']},{'local_duplicate','duplicate_superseded','fresh'})
    def test_bad_registry_future_clock_and_namespace_conflict_are_explicit(self):
        (self.registry/'bad.json').write_text('{')
        self.node('future',age=-30)
        cloud,total=self.inspect();self.assertFalse(total['complete']);self.assertIsNone(cloud['expected_active_cloud_nodes'])
        self.assertEqual(cloud['nodes'][0]['status'],'future_timestamp')
        (self.registry/'bad.json').unlink();(self.root/'runtime/nodes/future/telemetry.json').unlink()
        self.node('self','local','boot-local',pid_namespace='pid:[999]')
        cloud,total=self.inspect();self.assertFalse(total['complete'])
        self.assertEqual(cloud['issues'][0]['kind'],'local_pid_namespace_conflict')
    def test_ended_submissions_are_not_expected_and_stale_local_is_incomplete(self):
        self.submission(state='submission_failed');self.submission('done',state='completed')
        cloud,total=self.inspect();self.assertEqual(cloud['expected_active_cloud_nodes'],0);self.assertTrue(total['complete'])
        cloud,total=self.inspect(local_observed_unix=self.now-91);self.assertFalse(total['complete'])


if __name__ == '__main__': unittest.main()
