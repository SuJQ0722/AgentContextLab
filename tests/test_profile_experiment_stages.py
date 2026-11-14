import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('stage_profile', Path(__file__).resolve().parents[1]/'scripts/profile_experiment_stages.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class StageProfileTests(unittest.TestCase):
    def test_exclusive_wall_partition_does_not_double_count_summary_in_compression(self):
        out=M.partition_intervals([('sdk',[(10,30)]),('compression',[(5,35)]),('web',[(40,50),(45,60)])],0,100)
        self.assertEqual(out,dict(sdk=20,compression=10,web=20,unassigned=50))

    def test_interval_union_clips_nested_and_parallel_work(self):
        self.assertEqual(M.union_seconds([(0,10),(2,7),(8,15),(18,25)],3,20),14)
        self.assertEqual(M.union_seconds([(None,5),(8,4)]),0)

    def test_transport_separates_routes_and_censored_requests(self):
        events=[
            dict(event='request_started',request_id='a',sdk_request_id='sdk',at_unix=10),
            dict(event='transport_phase',request_id='a',phase='http11.send_request_body.failed',phase_seconds=45),
            dict(event='route_failed',request_id='a',elapsed_seconds=46,error_type='WriteTimeout'),
            dict(event='request_started',request_id='b',sdk_request_id='sdk',at_unix=60),
            dict(event='transport_phase',request_id='b',phase='http11.send_request_body.complete',phase_seconds=2,elapsed_seconds=3),
            dict(event='response_headers',request_id='b',elapsed_seconds=103,status_code=200),
            dict(event='stream_complete',request_id='b',elapsed_seconds=108,request_wall_seconds=154),
            dict(event='request_started',request_id='c',sdk_request_id='next',at_unix=180),
        ]
        rows,_=M.parse_transport(events,200)
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['failed_upload_seconds'],45)
        self.assertFalse(rows[0]['censored'])
        self.assertEqual(rows[1]['after_upload_to_headers_seconds'],100)
        self.assertEqual(rows[1]['stream_seconds'],5)
        self.assertEqual(rows[1]['wall_seconds'],108)
        self.assertTrue(rows[2]['censored'])
        self.assertEqual(rows[2]['censored_elapsed_until_attempt_end'],20)
        self.assertIsNone(rows[2]['upload_seconds'])

    def test_http_error_is_terminal_not_censored(self):
        rows,_=M.parse_transport([dict(event='final_inline_request',attempt_id='x',at_unix=10),
            dict(event='route_http_error',attempt_id='x',http_status=429,client_seconds=2)],100)
        self.assertTrue(rows[0]['failed'])
        self.assertFalse(rows[0]['censored'])
        self.assertEqual(rows[0]['errors'],['HTTP_429'])

    def test_success_rounds_exclude_errors_and_summary_and_do_not_pool_retries(self):
        with tempfile.TemporaryDirectory()as td:
            p=Path(td);root=p/'runs/attempt_002/native';metrics=root/'metrics';metrics.mkdir(parents=True)
            result=dict(native_artifact_root=str(root),status='timeout',end_to_end_seconds=100,
                        started_at_unix_estimate=100,finished_at_unix=200)
            (root.parent/'result.json').write_text(json.dumps(result))
            # Wrapper total covers previous retries. The profiler must use physical attempt time.
            wrapper={**result,'end_to_end_seconds':900}
            rp=p/'result.json';rp.write_text(json.dumps(wrapper))
            calls=[dict(call_id='ok',purpose='agent',started_at=110,ended_at=120,client_stream_seconds=10,finish={'kind':'tool_calls'}),
                   dict(call_id='err',purpose='agent',started_at=120,ended_at=130,client_stream_seconds=10,error_type='ReadTimeout'),
                   dict(call_id='sum',purpose='compaction',started_at=130,ended_at=140,client_stream_seconds=10)]
            (metrics/'calls.jsonl').write_text('\n'.join(json.dumps(x)for x in calls))
            starts=[dict(call_id=x['call_id'],purpose=x['purpose'],started_at=x['started_at'])for x in calls]
            starts.append(dict(call_id='pending',purpose='agent',started_at=150))
            (metrics/'call-starts.jsonl').write_text('\n'.join(json.dumps(x)for x in starts))
            obs=dict(slot_id='s',benchmark='b',harness='hermes',method='visual',question_id='q',repeat=1,
                     status='timeout_unresolved',latest_terminal_result_path=str(rp))
            r=M.profile(obs)
            self.assertEqual(r['e2e_seconds'],100)
            self.assertEqual(r['decisions_observed'],1)
            self.assertEqual(r['tool_decisions_observed'],1)
            self.assertEqual(r['agent_errors'],1)
            self.assertEqual(r['compaction_calls'],1)
            self.assertEqual(r['pending_sdk_calls'],1)
            self.assertEqual(r['sdk_union_seconds'],30)
            self.assertEqual(r['sdk_plus_censored_union_seconds'],80)
            self.assertIsNone(r['render_seconds']['sum'])
            self.assertIsNone(r['http_requests'])


if __name__=='__main__':unittest.main()
