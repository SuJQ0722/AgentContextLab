import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC=importlib.util.spec_from_file_location('once_metrics',Path(__file__).parents[1]/'scripts/once24h_metrics_v15.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)


def write(path,value,lines=False):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(r)+'\n'for r in value) if lines else json.dumps(value))
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.attempt=self.root/'jobs/hermes/visual/q_001_r01/attempts/attempt_001'
        self.native=self.attempt/'native';self.metrics=self.native/'metrics'
        self.result={'job_id':'hermes/visual/q_001_r01','harness':'hermes','strategy':'visual','question_id':'q_001','repeat':1,'model':'approved','status':'completed','native_artifact_root':str(self.native),'end_to_end_seconds':30}
        self.result_path=self.attempt/'result.json'
        self.obs={'harness':'hermes','method':'visual','selected_result_path':str(self.result_path),'selected_result_sha256':write(self.result_path,self.result)}
        self.index=m.MetricsIndex(self.root,[],archive_path=self.root/'no_archive')

    def wire(self,metrics=None,identity='r',known=True):
        metrics=metrics or self.metrics
        raw={'prompt_tokens':10,'completion_tokens':3,'total_tokens':13,'prompt_tokens_details':{'cached_tokens':4}}
        rows=[{'event':'request_started','request_id':identity,'route':'approved'},
              {'event':'stream_complete','request_id':identity,'route':'approved','raw_provider_usage':raw if known else None,'client_seconds':5}]
        write(metrics/'transport-phases-v3.jsonl',rows,True)
        return raw

    def test_transport_authoritative_sdk_not_double_counted(self):
        raw=self.wire()
        write(self.metrics/'calls.jsonl',[{'call_id':'sdk','raw_provider_usage':raw,'client_stream_seconds':7}],True)
        v=self.index.observe(self.obs)
        self.assertEqual(v['complete_tokens']['total'],13)
        self.assertEqual(v['sdk_usage_observations_suppressed'],1)
        self.assertEqual(v['client_http_seconds'],5)
        self.assertEqual(v['client_sdk_seconds'],7)
        self.assertEqual(v['cache_request_hit_rate'],1)
        self.assertEqual(v['cache_token_hit_rate'],.4)
        self.assertIsNone(v['render_seconds']);self.assertIsNone(v['compression_count'])

    def test_unknown_raw_usage_does_not_become_zero_cost(self):
        self.wire(known=False)
        v=self.index.observe(self.obs)
        self.assertIsNone(v['complete_tokens']['total']);self.assertFalse(v['tokens_complete'])
        self.assertEqual(v['unknown_usage_requests'],1)
        self.assertIsNone(v['cache_request_hit_rate'])

    def test_sha_mismatch_and_outside_native_are_quarantined(self):
        bad={**self.obs,'selected_result_sha256':'wrong'}
        self.assertFalse(self.index.observe(bad)['tokens_complete'])
        self.result['native_artifact_root']=str(self.root/'elsewhere/native')
        self.obs['selected_result_sha256']=write(self.result_path,self.result)
        self.assertTrue(any(r['kind']=='metrics_quarantined'for r in self.index.observe(self.obs)['issues']))

    def test_nested_selected_child_excludes_prior_timeout_and_outer_wall(self):
        selected=self.attempt/'runs/attempt_002';native=selected/'native'
        child={**self.result,'native_artifact_root':str(native),'end_to_end_seconds':20}
        h=write(selected/'result.json',child)
        old=self.attempt/'runs/attempt_001';write(old/'result.json',{**child,'status':'timeout','end_to_end_seconds':3600})
        self.wire(selected/'native/metrics');self.wire(old/'native/metrics',identity='failed_earlier')
        outer={**self.result,'native_artifact_root':str(native),'end_to_end_seconds':3620,'attempts':[{'result_path':str(selected/'result.json'),'result_sha256':h}]}
        self.obs['selected_result_sha256']=write(self.result_path,outer)
        v=self.index.observe(self.obs)
        self.assertEqual(v['complete_tokens']['total'],13);self.assertEqual(v['end_to_end_seconds'],20)
        self.assertEqual(v['usage_observations'],1)

    def test_compression_and_render_use_measured_fields(self):
        self.wire()
        write(self.metrics/'compression.jsonl',[{'count_delta':1},{'count_delta':2}],True)
        write(self.metrics/'render.jsonl',[{'render_seconds':.2},{'render_seconds':.3}],True)
        v=self.index.observe(self.obs)
        self.assertEqual(v['compression_count'],3);self.assertEqual(v['render_seconds'],.5)

    def test_archive_requires_single_native_and_matching_result_sha(self):
        fields={k:{'complete_total':v,'known_subtotal':v,'missing_count':0}for k,v in zip(m.FIELDS,(10,4,6,3,13))}
        row={'result_sha256':self.obs['selected_result_sha256'],'harness':'hermes','accounting':{'native_attempts':1,'usage':{'fields':fields},'http_or_fallback_observations':1,'http_latency_observations':0,'missing_instrumentation_attempts':0},'end_to_end_seconds':30}
        archive=self.root/'archive.json';write(archive,{'rows':[row]})
        idx=m.MetricsIndex(self.root,[],archive_path=archive)
        v=idx.observe(self.obs);self.assertEqual(v['complete_tokens']['total'],13);self.assertEqual(v['source_kind'],'sha_bound_single_native_archive')
        self.assertIsNone(v['cache_request_hit_rate']);self.assertIsNone(v['client_http_seconds'])
        row['accounting']['native_attempts']=2
        with self.assertRaises(ValueError):m.cached_metrics(row)
        idx.checkpoint();loaded=m.MetricsIndex(self.root,[],archive_path=self.root/'missing')
        self.assertEqual(loaded.observe(self.obs)['complete_tokens']['total'],13)

    def test_exact_native_truncation_failure_derivation_and_other_errors_refused(self):
        failed={**self.result,'status':'failed','failure_category':'execution_error'}
        self.obs['selected_result_sha256']=write(self.result_path,failed)
        conversation={'completed':False,'partial':True,'error':m.TRUNCATION_ERROR}
        write(self.native/'conversation.json',conversation)
        calls=[{'call_id':str(i),'purpose':'agent','error_type':None,'finish':{'kind':'length'},'raw_provider_usage':{'completion_tokens':8192}}for i in range(4)]
        write(self.metrics/'calls.jsonl',calls,True)
        v=m.classify_failure(self.result_path,self.obs['selected_result_sha256'])
        self.assertEqual(v['derived_failure_category'],'output_limit');self.assertEqual(len(v['proof']),3)
        self.assertEqual(json.loads(self.result_path.read_text())['failure_category'],'execution_error')
        m._FAILURE_CACHE.clear()
        calls[0]['raw_provider_usage']['completion_tokens']=16384
        calls[1]['raw_provider_usage']['completion_tokens']=32768
        write(self.metrics/'calls.jsonl',calls[1:],True)
        varied=m.classify_failure(self.result_path,self.obs['selected_result_sha256'])
        self.assertEqual(varied['derived_failure_category'],'output_limit')
        self.assertEqual(varied['evidence']['length_output_tokens_observed'],[32768,8192,8192])
        m._FAILURE_CACHE.clear()
        write(self.native/'conversation.json',{**conversation,'error':'Other response truncated'})
        self.assertIsNone(m.classify_failure(self.result_path,self.obs['selected_result_sha256'])['derived_failure_category'])
        write(self.native/'conversation.json',conversation)
        calls[-1]['finish']['kind']='stop';write(self.metrics/'calls.jsonl',calls,True)
        self.assertIsNone(m.classify_failure(self.result_path,self.obs['selected_result_sha256'])['derived_failure_category'])
        self.assertIsNone(m.classify_failure(self.result_path,'wrong')['derived_failure_category'])

if __name__=='__main__':unittest.main()
