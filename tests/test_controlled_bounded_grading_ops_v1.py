import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import judge_controlled_bounded_v1 as judge
import watch_controlled_bounded_pilot_v1 as watcher
from prepare_controlled_bounded_v1 import MODEL, ENCODING
from run_controlled_bounded_v1 import PROTOCOL

class OpsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.plan={'prefixes':[{'key':ds+'/q_001_r01','pilot':True,'eligible':True} for ds in ('bc','mmbc')]}
    def control(self):
        return {'passed':True,'native_identity_verified':True,'first_actual_prompt_tokens':10000,
            'native_hashes':['same'],'prefix_sha256':'prefix','actual_route':MODEL,
            'bounded_native_protocol':PROTOCOL,'bounded_transport_encoding':ENCODING}
    def write_pilot(self,counts=None):
        for p in self.plan['prefixes']:
            for method in ('visual','summary','window'):
                out=self.root/'jobs'/p['key']/method;out.mkdir(parents=True,exist_ok=True)
                (out/'trial-status.json').write_text(json.dumps({'status':'failed','worker_reaped':True}))
                c=self.control()
                if counts and method in counts:c['first_actual_prompt_tokens']=counts[method]
                (out/'compression-control.json').write_text(json.dumps(c))
    def test_unknown_is_not_failure_zero(self):
        rows=[{'score':0.,'repeat':1},{'score':None,'repeat':1}]
        r=judge.summarize(rows);self.assertEqual(r['known'],1);self.assertIsNone(r['accuracy']);self.assertEqual(r['accuracy_bounds'],[0.,.5])
        self.assertIsNone(r['mean_repeat_accuracy'])
    def test_zero_is_known_and_std_only_all_repeats(self):
        r=judge.summarize([{'score':0.,'repeat':1},{'score':1.,'repeat':2},{'score':1.,'repeat':3}])
        self.assertEqual(r['known'],3);self.assertAlmostEqual(r['mean_repeat_accuracy'],2/3)
    def test_watch_gate_not_answer_success_selection(self):
        self.write_pilot();r=watcher.evaluate(self.root,self.plan)
        self.assertEqual(r['state'],'ready');self.assertFalse(r['selection_by_accuracy'])
    def test_unmatched_pilot_blocks_expansion(self):
        self.write_pilot({'summary':10300});r=watcher.evaluate(self.root,self.plan)
        self.assertEqual(r['state'],'blocked');self.assertIn('gate_failed',r['reason'])
    def test_live_worker_waits(self):
        self.write_pilot()
        with patch.object(watcher,'alive',return_value=True):self.assertEqual(watcher.evaluate(self.root,self.plan)['state'],'waiting')
    def test_orphan_paid_dispatch_does_not_relaunch(self):
        out=self.root/'jobs'/self.plan['prefixes'][0]['key']/'visual';out.mkdir(parents=True)
        (out/'dispatch.json').write_text('{}')
        self.assertEqual(watcher.evaluate(self.root,self.plan)['reason'],'pilot_interrupted_unknown_no_replay')
    def completed_fixture(self):
        out=self.root/'private-grades';out.mkdir()
        source=self.root/'jobs/bc/q1/visual';source.mkdir(parents=True)
        prefix=self.root/'prefix.json';prefix.write_text('{}')
        spec={'question':'Q','question_id':'q1','method':'visual','repeat':1,'model':MODEL,'prefix_path':str(prefix)}
        (source/'spec.json').write_text(json.dumps(spec))
        (source/'result.json').write_text(json.dumps({'status':'completed','question_id':'q1','method':'visual','repeat':1}))
        (source/'trial-status.json').write_text(json.dumps({'status':'completed','worker_reaped':True,'job_id':'bc/q1/visual'}))
        c=self.control();c['prefix_sha256']=judge.sha(prefix)
        (source/'compression-control.json').write_text(json.dumps(c));(source/'conversation.json').write_text(json.dumps({'final_response':'A'}))
        (self.root/'plan.json').write_text('{}');(self.root/'experiment.json').write_text('{}')
        job={'job_id':'bc/q1/visual','prefix_key':'bc/q1','dataset':'browsecomp_v3','method':'visual','eligible':True,'out':str(source),'spec_path':str(source/'spec.json')}
        plan={'jobs':[job],'prefixes':[{'key':'bc/q1'}],'definition':{'old_costs':{}}}
        gold={'bc/q1/visual':{'question':'Q','answer':'A','question_id':'q1','repeat':1}}
        cfg={'plan_sha256':judge.sha(self.root/'plan.json'),'config_sha256':judge.sha(self.root/'experiment.json'),'gold_sha256':'gold'}
        return out,source,plan,gold,cfg
    def test_all_completed_graded_even_unmatched_and_helper_version_binding(self):
        out,source,plan,gold,cfg=self.completed_fixture()
        candidates,summary=judge.inventory(self.root,out,plan,gold,cfg)
        self.assertEqual(len(candidates),1);self.assertFalse(summary['records'][0]['matched_group'])
        self.assertIsNone(summary['records'][0]['score'])
        c=candidates[0];c['directory'].mkdir(parents=True)
        (c['directory']/'grade.json').write_text(json.dumps(dict(c['binding'],version='approved-helper',status='scored',score=0.,api_calls=1)))
        candidates,summary=judge.inventory(self.root,out,plan,gold,cfg)
        self.assertFalse(candidates);self.assertEqual(summary['records'][0]['score'],0.)
        self.assertEqual(summary['records'][0]['score_reason'],'judged_completed')
    def test_confirmed_failure_vs_unconfirmed_interruption(self):
        out,source,plan,gold,cfg=self.completed_fixture()
        (source/'result.json').write_text(json.dumps({'status':'failed'}))
        for status,expected in [('failed',0.),('timeout',0.),('interrupted',None)]:
            (source/'trial-status.json').write_text(json.dumps({'status':status,'worker_reaped':True}))
            candidates,summary=judge.inventory(self.root,out,plan,gold,cfg)
            self.assertFalse(candidates);self.assertEqual(summary['records'][0]['score'],expected)
    def test_bound_grade_refuses_changed_source_before_api(self):
        path=self.root/'result.json';path.write_text('{}')
        candidate={'binding':{'result_path':str(path),'result_sha256':'wrong'}}
        with patch.object(judge.approved,'judge_one') as call:
            with self.assertRaises(ValueError):judge.grade_bound(candidate,{},{} )
            call.assert_not_called()

if __name__=='__main__':unittest.main()
