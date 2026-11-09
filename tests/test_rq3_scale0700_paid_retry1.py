import json,os,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import test_rq3_scale0700_resume_ops5 as fixture_module
import run_rq3_scale0700_resume_ops5 as pending
import run_rq3_scale0700_paid_retry1 as retry
import run_rq3_paid_retry1_trial as trial
import judge_rq3_scale0700_paid_retry1 as judge
import report_rq3_final_seven_v2 as report

class PaidRetryTests(unittest.TestCase):
    def setUp(self):
        f=fixture_module.ResumeTests();f.setUp();self.addCleanup(f.doCleanups);self.parent=f.root;self.f=f;self.root=self.parent.parent/'retry';self.grading=self.parent.parent/'grading'
        p=patch.object(retry.base,'acquire_scale_slot',retry.base.acquire_scale_slot);p.start();self.addCleanup(p.stop)
        for job in f.jobs[66:81]:
            d=self.parent/'jobs'/job['job_id'];claim=pending.read(d/'claim/owner.json');spec={**job,'campaign_root':str(self.parent),'plan_sha256':pending.sha(self.parent/'plan.json'),
                'cohort_sha256':f.plan['definition']['cohort_sha256'],'controller_id':claim['controller_id'],'slot_path':claim['slot']}
            f.write(d/'spec.json',spec);f.write(d/'claim/spec.json',spec)
        self.parent_auth=f.prepared();self.auth=retry.prepare(self.parent,self.root,self.grading)
    def test_scope_exact15_paid_one_fixed_retry_science_identical(self):
        plan,a=retry.validate_scope(self.root);self.assertEqual(len(a['authorized_job_ids']),15);self.assertEqual(len(plan['jobs']),2100)
        self.assertEqual(a['max_additional_native_attempts_per_job'],1)
        for e in a['entries']:
            self.assertTrue(e['original_api_calls_were_started']);self.assertFalse((Path(e['parent_attempt'])/'result.json').exists());self.assertNotEqual(e['parent_attempt'],e['retry_attempt'])
        self.assertEqual((self.parent/'experiment.json').read_bytes(),(self.root/'experiment.json').read_bytes())
    def test_parent16_full_blocks_retry_and_freed_slot_shared_validate(self):
        allocator=retry.parent_slot_allocator(self.parent,self.parent_auth);owner={**self.f.owner,'controller_id':'parentnew'}
        slots=[allocator(None,pending.LABEL,owner,'parent'+str(i),16) for i in range(16)];self.assertTrue(all(slots))
        retry.install(self.root);jobs=retry.base.jobs_for_scale(pending.read(self.root/'plan.json'),.7)
        self.assertIsNone(retry.base.publish_claim(self.root,jobs[0],owner,.7,15))
        retry.base.release_slot(slots[-1]);claim=retry.base.publish_claim(self.root,jobs[0],owner,.7,15);self.assertIsNotNone(claim)
        directory,slot,attempt,spec=claim;self.assertEqual(slot.parent,Path(self.auth['shared_slot_root']));trial.guarded_validator(spec,attempt)
        self.assertEqual(len(list(slot.parent.glob('*/owner.json'))),16)
        self.assertIsNone(retry.base.publish_claim(self.root,jobs[0],owner,.7,16))
    def test_native_guard_rejects_unapproved_placeholder(self):
        job=next(j for j in pending.read(self.root/'plan.json')['jobs'] if j['job_id'] not in self.auth['authorized_job_ids'])
        with self.assertRaisesRegex(ValueError,'outside15'):trial.guarded_validator({**job,'campaign_root':str(self.root)},self.root/'unused')
    def test_grader_checks_same_attempt_and_scope_before_call(self):
        guard=judge.ScopeGuard(self.root);jid=self.auth['authorized_job_ids'][0];a=self.root/'jobs'/jid/'attempts/attempt_001'
        c={'binding':{'root':str(self.root),'job_id':jid,'attempt_path':str(a),'result_path':str(a/'result.json')}}
        guard.candidate(c);c['binding']['job_id']='hermes/scale_0700/q_099_r01'
        if c['binding']['job_id'] in self.auth['authorized_job_ids']:c['binding']['job_id']='hermes/scale_0000/q_001_r01'
        with self.assertRaises(ValueError):guard.candidate(c)
    def test_final_report_replaces15_only_and_sums_old_cost(self):
        previous=self.parent.parent/'previous';out=self.parent.parent/'new-report';entries=[]
        for j in self.f.plan['jobs']:
            scale=.75 if j['scale']==.125 else j['scale'];jid=j['job_id'].replace('scale_0125','scale_0750');a=str(self.parent/'jobs'/jid/'attempts/attempt_001')
            entries.append({'job_id':jid,'scale':scale,'original_attempt':a,'selected_attempt':a,'grading_root':'old','original_grading_root':'old'})
        self.f.write(previous/'comparison-plan.json',{'scales':list(report.original.SCALES),'planned_observations':2100,'legacy_root':str(self.parent),'entries':entries,'source_files_sha256':{},'selection_policy':'original'})
        c=report.prepare_comparison(previous,self.root,out);changed=[r for r in c['entries'] if r['original_attempt']!=r['selected_attempt']]
        self.assertEqual(len(changed),15);self.assertEqual(len(c['entries']),2100)
        costs=report.cumulative_cost(c);self.assertEqual(len(costs['jobs']),15)
        self.assertTrue(all(j['phases'][0]['starts_without_return']==1 for j in costs['jobs']))
        self.assertIsNone(costs['prediction_usage_cumulative']['observed_subtotals']['total_tokens'])
    def test_stop_drains_one_new_prediction_no_repeat_and_actual_trial_entry(self):
        created=[]
        class Child:
            pid=os.getpid();polls=0
            def poll(self):self.polls+=1;return 0 if self.polls>=3 else None
        def spawn(command,**kwargs):
            self.assertIn(str(retry.ROOT/'scripts/run_rq3_paid_retry1_trial.py'),command)
            c=Child();created.append(c);(self.root/'STOP').write_text('fixture');return c
        with patch('preflight_bc_v3_web.preflight',return_value={'passed':True}),patch.object(retry.base.time,'sleep',return_value=None):retry.dispatch(self.root,15,popen=spawn)
        self.assertEqual(len(created),1);self.assertGreaterEqual(created[0].polls,3)

if __name__=='__main__':unittest.main()
