import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from visual_inline_route_accounting_v5 import collect_transport,inspect_attempt,resources
from monitor_bc_campaign_v3 import aggregate

RAW={'prompt_tokens':100,'prompt_tokens_details':{'cached_tokens':80},'completion_tokens':10,'total_tokens':110}
class AccountingTests(unittest.TestCase):
    def write(self,path,rows):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(''.join(json.dumps(x)+'\n'for x in rows))
    def test_duplicate_terminal_usage_counts_once_and_failure_unknown_remains(self):
        events=[{'event':'request_started','request_id':'bad','route':'r1','sdk_request_id':'sdk'},
                {'event':'route_failed','request_id':'bad','route':'r1','sdk_request_id':'sdk','status_code':429,'usage_known':False},
                {'event':'request_started','request_id':'good','route':'r2','sdk_request_id':'sdk'},
                {'event':'stream_complete','request_id':'good','route':'r2','raw_provider_usage':RAW},
                {'event':'route_returned','request_id':'good','route':'r2','raw_provider_usage':RAW}]
        rows,_=collect_transport('/attempt',[('ledger',x)for x in events+events[-1:]])
        result=aggregate(rows)
        self.assertEqual(result['observations'],2);self.assertEqual(result['fields']['total']['known_subtotal'],110)
        self.assertEqual(result['fields']['total']['missing_count'],1);self.assertIsNone(result['fields']['total']['complete_total'])
        self.assertEqual(result['fields']['cached_input']['known_subtotal'],80);self.assertEqual(result['fields']['noncache_input']['known_subtotal'],20)
    def test_sdk_duplicate_is_suppressed_when_transport_exists(self):
        with tempfile.TemporaryDirectory()as root:
            attempt=Path(root)/'attempt_001';metrics=attempt/'native/metrics'
            self.write(metrics/'transport-phases-v3.jsonl',[{'event':'request_started','request_id':'a','route':'r'},
                 {'event':'route_returned','request_id':'a','route':'r','raw_provider_usage':RAW}])
            self.write(metrics/'calls.jsonl',[{'call_id':'sdk','raw_provider_usage':RAW,'model':'r'}])
            rows,info=inspect_attempt(attempt,'hermes')
            self.assertEqual(len(rows),1);self.assertEqual(info['sdk_observations_suppressed'],1)
            self.assertEqual(aggregate(rows)['fields']['total']['known_subtotal'],110)
    def test_sdk_fallback_only_without_transport(self):
        with tempfile.TemporaryDirectory()as root:
            attempt=Path(root)/'attempt_001';metrics=attempt/'native/metrics'
            self.write(metrics/'calls.jsonl',[{'call_id':'sdk','raw_provider_usage':RAW,'model':'r'}])
            rows,info=inspect_attempt(attempt,'hermes')
            self.assertEqual(info['source'],'sdk_fallback_no_transport');self.assertEqual(len(rows),1)
            self.assertEqual(aggregate(rows)['fields']['total']['complete_total'],110)
    def test_dsh_attempt_ids_do_not_collapse_to_one_sdk_request(self):
        events=[{'event':'final_inline_request','attempt_id':'a','actual_model':'r1','sdk_request_id':'sdk'},
                {'event':'route_transport_error','attempt_id':'a','actual_model':'r1','raw_provider_usage':RAW,'usage_known':True},
                {'event':'final_inline_request','attempt_id':'b','actual_model':'r2','sdk_request_id':'sdk'},
                {'event':'stream_complete','attempt_id':'b','actual_model':'r2','raw_provider_usage':RAW,'usage_known':True}]
        rows,_=collect_transport('/attempt',[('dsh',x)for x in events]);self.assertEqual(len(rows),2)
        self.assertEqual(aggregate(rows)['fields']['total']['complete_total'],220)
        self.assertTrue(rows[0]['failed']);self.assertFalse(rows[0]['failed_cost_unknown'])
    def test_missing_cache_split_never_becomes_zero(self):
        raw={'prompt_tokens':100,'completion_tokens':10,'total_tokens':110}
        rows,_=collect_transport('/a',[('l',{'event':'stream_complete','request_id':'r','raw_provider_usage':raw})])
        fields=aggregate(rows)['fields'];self.assertEqual(fields['total']['complete_total'],110)
        self.assertIsNone(fields['cached_input']['complete_total']);self.assertEqual(fields['noncache_input']['missing_count'],1)
    def test_conflicting_usage_is_unknown_not_last_wins(self):
        issues=[];rows,_=collect_transport('/a',[('l',{'event':'stream_complete','request_id':'r','raw_provider_usage':RAW}),
            ('l',{'event':'route_returned','request_id':'r','raw_provider_usage':{**RAW,'total_tokens':111}})],issues)
        self.assertEqual(len(rows),1);self.assertTrue(rows[0]['usage_conflict']);self.assertIsNone(rows[0]['raw_provider_usage']);self.assertTrue(issues)
    def test_unsent_deadline_is_not_a_model_attempt(self):
        rows,_=collect_transport('/a',[('l',{'event':'route_deadline_exhausted','request_id':'never-sent'})]);self.assertEqual(rows,[])
    def test_429_backoff_is_separate_and_not_double_counted(self):
        event={'event':'route_backoff','request_id':'a','sdk_request_id':'s','route_cycle_completed':1,'client_wait_seconds':60.2,'planned_wait_seconds':60.1}
        rows,waits=collect_transport('/a',[('l',{'event':'route_failed','request_id':'a','sdk_request_id':'s','status_code':429}),('l',event),('l',event)])
        self.assertEqual(len(rows),1);self.assertEqual(len(waits),1);self.assertTrue(waits[0]['followed_cycle_with_429']);self.assertEqual(waits[0]['client_wait_seconds'],60.2)
    def test_same_http_id_in_different_prediction_attempts_stays_distinct(self):
        event={'event':'stream_complete','request_id':'r','raw_provider_usage':RAW}
        a,_=collect_transport('/one',[('l',event)]);b,_=collect_transport('/two',[('l',event)])
        self.assertEqual(aggregate(a+b)['observations'],2)
    def test_private_judge_cost_separate_and_output_json_serializable(self):
        with tempfile.TemporaryDirectory()as root:
            root=Path(root);prediction=root/'prediction';out=root/'grading';job={'job_id':'hermes/visual/q','harness':'hermes'}
            self.write(prediction/'jobs'/job['job_id']/'attempts/attempt_001/native/metrics/transport-phases-v3.jsonl',[
                {'event':'stream_complete','request_id':'r','route':'route','raw_provider_usage':RAW}])
            private=out/'cells/c/jobs'/job['job_id'];private.mkdir(parents=True);(private/'request-started.json').write_text('{}');(private/'grade.json').write_text(json.dumps({'api_calls':1,'raw_provider_usage':RAW}))
            value=resources({'c':{'root':prediction,'plan':{'jobs':[job]}}},out);json.dumps(value)
            self.assertEqual(value['cells']['c']['new_prediction_all_attempts']['fields']['total']['complete_total'],110)
            self.assertEqual(value['cells']['c']['judge']['fields']['total']['complete_total'],110)
if __name__=='__main__':unittest.main()
