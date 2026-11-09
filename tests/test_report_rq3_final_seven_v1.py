import json
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import report_rq3_final_seven_v1 as final
import prepare_rq3_scale0750_v1 as new_scope
import run_rq3_parity_v3 as legacy

class FinalSevenTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)/'base';self.base.mkdir();self.old=Path(self.tmp.name)/'old';self.new=Path(self.tmp.name)/'new';self.out=Path(self.tmp.name)/'report'
        (self.base/'experiment.json').write_text(json.dumps(legacy.read(legacy.BASE/'experiment.json')));(self.base/'plan.json').write_text('{}')
        (self.base/'cohort.jsonl').write_text(''.join(json.dumps({'id':f'q_{i:03}','question':f'Question{i}','answer':'PRIVATE'})+'\n' for i in range(100)))
        with patch.object(legacy,'BASE',self.base),patch.object(legacy,'sources',return_value={}):legacy.prepare(self.old)
        new_scope.prepare(self.old,self.new)
        scope=self.old/'cloud-scale-ops2/scope-revision-20261109.json';scope.parent.mkdir()
        scope.write_text(json.dumps({'final_scales':list(final.SCALES),'excluded_scale':.125,'new_scale':.75,'planned_observations':2100}))
        self.grading=Path(self.tmp.name)/'grades';self.new_grading=Path(self.tmp.name)/'new-grades'
    def prepare(self,recoveries=()):return final.prepare_comparison(self.old,self.new,self.grading,self.new_grading,self.out,recovery_roots=recoveries)
    def rows(self):
        return [{'scale':s,'question_id':f'q{i:03}','repeat':r,'score':float(i<(70 if s==1 else 40+10*r if s==.75 else 50)),
            'compression_count':int(i%2==0),'prediction_status':'completed','score_reason':'judged_completed'}
            for s in final.SCALES for i in range(100) for r in (1,2,3)]
    def test_exact2100_six_reused_only075_new_and_no0125(self):
        p=self.prepare();self.assertEqual(len(p['entries']),2100)
        self.assertEqual(sum(e['source_root']==str(self.old) for e in p['entries']),1800)
        self.assertEqual(sum(e['source_root']==str(self.new) for e in p['entries']),300)
        self.assertEqual({e['scale'] for e in p['entries']},set(final.SCALES));self.assertNotIn(.125,{e['scale'] for e in p['entries']})
        self.assertEqual(p,self.prepare());self.assertFalse(any('question' in e or 'answer' in e for e in p['entries']))
    def test_fixed_recovery_replaces_same_question_without_adding_repeat(self):
        recovery=Path(self.tmp.name)/'recovery';recovery.mkdir();(recovery/'recovery-authorization.json').write_text('{}');(recovery/'plan.json').write_text('{}')
        jid='hermes/scale_0800/q_085_r03';attempt=recovery/'jobs'/jid/'attempts/attempt_001'
        with patch.object(final,'recovery_selection',return_value=({jid:(attempt,recovery/'grading')},{})):p=self.prepare([recovery])
        rows=[e for e in p['entries'] if e['job_id']==jid];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['repeat'],3)
        self.assertEqual(rows[0]['selected_attempt'],str(attempt));self.assertEqual(len(p['entries']),2100)
    def test_changed_cohort_or_config_cannot_be_pooled(self):
        (self.new/'cohort.jsonl').write_text('different')
        with self.assertRaisesRegex(ValueError,'cohorts differ'):self.prepare()
    def test_binding_detects_later_scope_edits(self):
        p=self.prepare();path=self.old/'cloud-scale-ops2/scope-revision-20261109.json';path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'Bound comparison source changed'):final.snapshot(p,self.out,draws=10)
    def test_avg3_sample_std_question_clusters_six_holm(self):
        data=final.analyze(self.rows(),draws=100);s=next(x for x in data['summary'] if x['scale']==.75)
        self.assertAlmostEqual(s['mean_accuracy'],.6);self.assertAlmostEqual(s['std_across_three_repeats'],.1)
        self.assertEqual(len(data['paired_tests']),6);self.assertTrue(all(p['question_clusters']==100 and 'holm_p_six_comparisons' in p for p in data['paired_tests']))
    def test_missing_or_excluded_scale_never_becomes_final_accuracy(self):
        rows=self.rows();next(r for r in rows if r['scale']==.75)['score']=None
        data=final.analyze(rows,draws=50);s=next(x for x in data['summary'] if x['scale']==.75)
        self.assertFalse(s['avg3_ready']);self.assertIsNone(s['mean_accuracy']);self.assertFalse(any('holm_p_six_comparisons' in p for p in data['paired_tests']))
        rows[0]['scale']=.125
        with self.assertRaisesRegex(ValueError,'Unexpected scale'):final.analyze(rows,draws=10)
    def test_excluded_cost_preserves_missing_cache_and_unreturned_call(self):
        p=self.prepare();job=next(j for j in legacy.read(self.old/'plan.json')['jobs'] if j['scale']==.125)
        metrics=self.old/'jobs'/job['job_id']/'attempts/attempt_001/native/metrics';metrics.mkdir(parents=True)
        calls=[{'call_id':'a','raw_provider_usage':{'prompt_tokens':100,'completion_tokens':2,'total_tokens':102}}, {'call_id':'b','raw_provider_usage':None,'error_type':'TimeoutError'}]
        (metrics/'calls.jsonl').write_text(''.join(json.dumps(c)+'\n' for c in calls));(metrics/'call-starts.jsonl').write_text(''.join(json.dumps({'call_id':i})+'\n' for i in ['a','b','c']))
        cost=final.excluded_cost(p);usage=cost['prediction_usage'];self.assertEqual(usage['observed_subtotals']['total_tokens'],102)
        self.assertIsNone(usage['observed_subtotals']['cached_input_tokens']);self.assertEqual(usage['missing_field_counts']['cached_input_tokens'],2)
        self.assertEqual(cost['prediction_starts_without_return'],1);self.assertIsNone(usage['usd']);self.assertTrue(cost['excluded_from_accuracy'])

if __name__=='__main__':unittest.main()
