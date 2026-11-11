"""Question-level retry aggregates must include every actual native attempt once."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from visual_inline_route_accounting_v5 import resources,native_attempts

RAW={'prompt_tokens':100,'prompt_tokens_details':{'cached_tokens':80},'completion_tokens':10,'total_tokens':110}
class RetryAccountingTests(unittest.TestCase):
    def write(self,path,rows):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(''.join(json.dumps(x)+'\n'for x in rows))
    def test_all_children_including_failed_unknown_and_in_progress_not_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);job={'job_id':'hermes/visual/q_r01','harness':'hermes'}
            parent=root/'jobs'/job['job_id']/'attempts/attempt_001'
            # Even if an outer summary/alias contains the last usage, it must not be counted twice.
            self.write(parent/'native/metrics/transport-phases-v3.jsonl',[{'event':'stream_complete','request_id':'same','raw_provider_usage':RAW}])
            for n in (1,2):
                self.write(parent/f'runs/attempt_{n:03d}/native/metrics/transport-phases-v3.jsonl',[
                    {'event':'request_started','request_id':'same','route':'r'},
                    {'event':'route_failed' if n==1 else 'stream_complete','request_id':'same','raw_provider_usage':RAW}])
            self.write(parent/'runs/attempt_003/native/metrics/transport-phases-v3.jsonl',[
                {'event':'request_started','request_id':'unknown','route':'r'},
                {'event':'route_failed','request_id':'unknown','usage_known':False}])
            # Child 3 deliberately has no result.json: a running/terminated attempt can already cost money.
            report=resources({'c':{'root':root,'plan':{'jobs':[job]}}},root/'grading')['cells']['c']
            self.assertEqual(report['observed_attempts'],3);self.assertEqual(report['http_attempts'],3)
            self.assertEqual(report['failed_attempts'],2);self.assertEqual(report['failed_attempts_with_unknown_cost'],1)
            fields=report['new_prediction_all_attempts']['fields']
            self.assertEqual(fields['total']['known_subtotal'],220);self.assertIsNone(fields['total']['complete_total'])
            self.assertEqual(fields['cached_input']['known_subtotal'],160);self.assertEqual(fields['noncache_input']['known_subtotal'],40)
            self.assertEqual(len({x['attempt_path'] for x in report['http_attempt_records']}),3)
    def test_all_dsh_strategy_metric_directories_are_accounted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);jobs=[]
            for strategy in ('visual_native','summarization','sliding_window','no_compression','discard_all'):
                job={'job_id':f'dsh/{strategy}/q','harness':'dsh'};jobs.append(job)
                metrics=root/'jobs'/job['job_id']/f'attempts/attempt_001/runs/attempt_001/native/{strategy}/q/workspace/metrics'
                self.write(metrics/'inline-images-wire-dsh-v1.jsonl',[
                    {'event':'final_inline_request','attempt_id':'same','actual_model':'r'},
                    {'event':'stream_complete','attempt_id':'same','raw_provider_usage':RAW}])
                self.write(metrics/'calls.jsonl',[{'call_id':'duplicate','raw_provider_usage':RAW}])
            report=resources({'c':{'root':root,'plan':{'jobs':jobs}}},root/'grading')['cells']['c']
            self.assertEqual(report['observed_attempts'],5);self.assertEqual(report['http_attempts'],5)
            self.assertEqual(report['new_prediction_all_attempts']['fields']['total']['complete_total'],550)
            self.assertEqual(report['sdk_fallback_observations'],0)
    def test_legacy_attempt_layout_preserved_and_empty_v8_parent_not_billable(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);self.assertEqual(native_attempts(path),[path])
            (path/'runs').mkdir();self.assertEqual(native_attempts(path),[])

    def test_missing_entire_attempt_instrumentation_invalidates_complete_total(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);job={'job_id':'hermes/visual/q','harness':'hermes'}
            parent=root/'jobs'/job['job_id']/'attempts/attempt_001/runs'
            self.write(parent/'attempt_001/native/metrics/transport-phases-v3.jsonl',[
                {'event':'stream_complete','request_id':'known','raw_provider_usage':RAW}])
            unknown=parent/'attempt_002';unknown.mkdir();(unknown/'worker-started.json').write_text('{}')
            report=resources({'c':{'root':root,'plan':{'jobs':[job]}}},root/'grading')['cells']['c']
            total=report['new_prediction_all_attempts'];self.assertEqual(total['observations'],1)
            self.assertEqual(total['fields']['total']['known_subtotal'],110)
            self.assertIsNone(total['fields']['total']['complete_total'])
            self.assertFalse(total['attempt_instrumentation_complete'])
            self.assertEqual(report['missing_instrumentation_attempts'],[str(unknown)])
            (unknown/'result.json').write_text(json.dumps({'status':'not_started','api_calls':0}))
            proven=resources({'c':{'root':root,'plan':{'jobs':[job]}}},root/'grading')['cells']['c']
            self.assertEqual(proven['proven_zero_model_call_attempts'],1)
            self.assertTrue(proven['new_prediction_all_attempts']['attempt_instrumentation_complete'])
            self.assertEqual(proven['new_prediction_all_attempts']['fields']['total']['complete_total'],110)
            # False is not an integer counter proving zero requests.
            (unknown/'result.json').write_text(json.dumps({'api_calls':False}))
            again=resources({'c':{'root':root,'plan':{'jobs':[job]}}},root/'grading')['cells']['c']
            self.assertFalse(again['new_prediction_all_attempts']['attempt_instrumentation_complete'])
