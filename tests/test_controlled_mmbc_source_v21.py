import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import controlled_mmbc_source_v21 as v


class Version21ControllerTests(unittest.TestCase):
    def make(self, root, action='matched_continuation'):
        out=root/'cells/summary/jobs/q1_r01/attempt_001'
        job={'job_id':'summary/q1_r01','question_id':'q1','repeat':1,'method':'summary',
            'action':action,'source_result_path':'source','source_result_sha256':'sha',
            'output_path':str(out)}
        plan={'jobs':[job],'stop_new_at_unix':time.time()+3600}
        v.save(root/'plan.json',plan)
        return plan,job,out

    def test_timeout_terminal_consumes_one_attempt_without_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan,job,out=self.make(root)
            calls=[];clock_calls=[0]
            def clock():
                clock_calls[0]+=1
                return 0 if clock_calls[0]==1 else 4000
            def popen(*args,**kwargs):
                calls.append(1)
                return subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],
                    start_new_session=True,stdout=kwargs['stdout'],stderr=kwargs['stderr'])
            with patch.object(v,'environment',return_value=(dict(os.environ),{})),patch.object(v.time,'sleep',return_value=None):
                v.run_controller(root,plan,'summary',popen=popen,clock=clock)
                v.run_controller(root,plan,'summary',popen=popen,clock=clock)
            self.assertEqual(len(calls),1)
            result=v.read(out/'terminal.json')
            self.assertEqual(result['status'],'timeout')
            self.assertFalse(result['will_retry'])
            self.assertTrue(result['native_cleanup_confirmed'])
            self.assertTrue(v.read(root/'cells/summary/status.json')['drained'])

    def test_canary_release_requires_actual_budget_and_native_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'target.json';v.save(target,{'source_first_post_prompt_tokens':10000,'baseline_native_hashes':['native']})
            job={'target_path':str(target),'prefix_sha256':'prefix'}
            gate={'passed':True,'native_identity_verified':True,'final_wire_native_identity_preserved':True,
                  'prefix_sha256':'prefix','native_hashes':['native'],'first_actual_prompt_tokens':10100}
            self.assertTrue(v.canary_gate_valid(job,gate))
            self.assertFalse(v.canary_gate_valid(job,{**gate,'first_actual_prompt_tokens':10300}))
            self.assertFalse(v.canary_gate_valid(job,{**gate,'native_hashes':['changed']}))
            self.assertFalse(v.canary_gate_valid(job,{**gate,'prefix_sha256':'other'}))

    def test_failed_canary_never_dispatches_second_paid_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan,job,out=self.make(root)
            second={**job,'job_id':'summary/q2_r01','question_id':'q2','output_path':str(root/'cells/summary/jobs/q2_r01/attempt_001')}
            plan['jobs'].append(second);plan['canary_job_id']=job['job_id'];v.save(root/'plan.json',plan)
            calls=[];ticks=[0]
            def clock():
                ticks[0]+=1;return 0 if ticks[0]==1 else 4000
            def popen(*a,**kw):
                calls.append(1);return subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True,stdout=kw['stdout'],stderr=kw['stderr'])
            with patch.object(v,'environment',return_value=(dict(os.environ),{})),patch.object(v.time,'sleep',return_value=None):
                v.run_controller(root,plan,'summary',popen=popen,clock=clock)
            self.assertEqual(len(calls),1)
            self.assertFalse((Path(second['output_path'])/'dispatch.json').exists())
            self.assertEqual(v.read(root/'cells/summary/status.json')['pending'],1)

    def test_unknown_prior_claim_never_dispatched(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan,job,out=self.make(root)
            v.save(out/'dispatch.json',{'prior_unknown':True})
            with patch.object(v,'environment',return_value=(dict(os.environ),{})),patch.object(v,'python_for',side_effect=AssertionError('dispatch')):
                v.run_controller(root,plan,'summary')
            status=v.read(root/'cells/summary/status.json')
            self.assertFalse(status['drained'])
            self.assertEqual(status['unknown_prior_claims'],[job['job_id']])
            self.assertFalse((out/'terminal.json').exists())

    def test_no_intervention_reuse_is_not_new_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan,job,out=self.make(root,'no_compression_reuse')
            with patch.object(v,'environment',return_value=(dict(os.environ),{})),patch.object(v,'python_for',side_effect=AssertionError('dispatch')):
                v.run_controller(root,plan,'summary')
            result=v.read(out/'terminal.json')
            self.assertEqual(result['status'],'no_compression_reuse')
            self.assertEqual(result['new_attempts'],0)
            self.assertTrue(v.read(root/'cells/summary/status.json')['drained'])

    def test_changed_source_result_rejected_before_paid_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.json';source.write_text('{}')
            job={'source_result_path':str(source),'source_result_sha256':v.sha(source),'action':'blocked'}
            source.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,'Source result changed'):v.validate_job(job)

    def test_worker_binds_real_spec_to_legacy_recorder_argv(self):
        import visual_transport_runtime_v4, inline_visual_transport_v1
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'out';spec=root/'spec.json';cfg=root/'config.json'
            v.save(spec,{'frozen_input_images':[]})
            v.save(cfg,{'transport_runtime_policy':{},'model_route_policy':{},'gateway_proxy':{}})
            job={'action':'matched_continuation','method':'summary','job_id':'summary/q1_r01',
                 'spec_path':str(spec),'config_path':str(cfg),'output_path':str(out),
                 'source_result_sha256':'source','spec_sha256':v.sha(spec)}
            prior=list(sys.argv);seen=[]
            def native_run(specification,directory):
                seen.append(Path(sys.argv[sys.argv.index('--spec')+1]))
                self.assertEqual(sys.argv[sys.argv.index('--out')+1],str(out))
            with patch.object(v,'validate_job'),patch.object(v,'environment',return_value=({'TOKENHUB_BASE_URL':'http://127.0.0.1:1'},{})), \
                    patch.object(visual_transport_runtime_v4,'install',return_value={'uninstall':lambda:None}), \
                    patch.object(inline_visual_transport_v1,'install',return_value={'uninstall':lambda:None}), \
                    patch.object(v.engine,'run',native_run):
                v.worker(root,{},job)
            self.assertEqual(seen,[spec]);self.assertEqual(sys.argv,prior)

    def test_deep_validation_runs_native_review_gate(self):
        import review_execution
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            plan={'version':v.VERSION,'attempts_per_slot':1,'cohort_path':'cohort',
                  'cohort_sha256':'sha','harness_lock_sha256':'sha','source_sha256':{},
                  'jobs':[],'config_sha256':'sha','pending_manifest_path':'pending','pending_manifest_sha256':'sha','previous_root':str(root),'previous_plan_sha256':'sha'}
            with patch.object(v,'sha',return_value='sha'),patch.object(review_execution,'ROOT',root):
                with patch.object(v,'read',side_effect=lambda p:{'never_dispatched':[],'stop_path':'stop','stop_sha256':'sha','controller_pause_snapshot_path':'pause','controller_pause_snapshot_sha256':'sha'} if str(p)=='pending' else {'review_approved':True}):
                    with self.assertRaisesRegex(ValueError,'separately versioned'):
                        v.validate_plan(root,plan,deep=True)
                with patch.object(v,'read',side_effect=lambda p:{'never_dispatched':[],'stop_path':'stop','stop_sha256':'sha','controller_pause_snapshot_path':'pause','controller_pause_snapshot_sha256':'sha'} if str(p)=='pending' else {'execution_version':'hermes-parity-v3','review_approved':True}):
                    v.validate_plan(root,plan,deep=True)

    def test_configured_method_concurrency_is_exactly_16(self):
        with self.assertRaisesRegex(ValueError,'exactly16'):
            v.run_controller(Path('/not-created'),{'jobs':[]},'summary',concurrency=8)

if __name__=='__main__':unittest.main()
