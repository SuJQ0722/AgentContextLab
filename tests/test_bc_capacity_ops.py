import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_bc_campaign_v3_capacity_ops as ops


class HotDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.config=self.root/'dispatch.json';self.control=self.root/'control'
    def config_write(self,cloud=1,local=2):
        self.config.write_text(json.dumps({'worker_ceiling_per_instance':32,'active_workers_per_cloud_instance':cloud,'local_target_workers':local}))
    def test_roles_are_explicit_and_hot_changes_are_audited_once(self):
        self.config_write();cloud=ops.DispatchPolicy(self.config,'cloud',self.control)
        self.assertEqual(cloud.refresh()['target'],1);cloud.refresh()
        self.assertEqual(len(list((self.control/'dispatch-decisions').glob('*.json'))),1)
        self.assertEqual(ops.DispatchPolicy(self.config,'local').refresh()['target'],2)
        self.config_write(cloud=4);self.assertEqual(cloud.refresh()['target'],4)
        self.assertEqual(len(list((self.control/'dispatch-decisions').glob('*.json'))),2)
        with self.assertRaises(ValueError):ops.DispatchPolicy(self.config,'guessed')
    def test_explicit_zero_is_valid_pause_but_invalid_policy_is_unknown(self):
        self.config_write(cloud=0);policy=ops.DispatchPolicy(self.config,'cloud',self.control)
        self.assertTrue(policy.refresh()['valid']);self.assertEqual(policy.refresh()['target'],0)
        self.assertFalse(ops.can_dispatch(policy.refresh(),0))
        self.config.write_text('{');decision=policy.refresh()
        self.assertFalse(decision['valid']);self.assertIsNone(decision['target'])
        self.config_write(cloud=1);self.assertTrue(ops.can_dispatch(policy.refresh(),0))
    def test_reduction_never_authorizes_new_dispatch_over_target(self):
        self.config_write(cloud=1);decision=ops.DispatchPolicy(self.config,'cloud').refresh()
        self.assertFalse(ops.can_dispatch(decision,2));self.assertFalse(ops.can_dispatch(decision,1))
        self.assertTrue(ops.can_dispatch(decision,0));self.assertFalse(ops.can_dispatch(decision,0,True))
        for invalid in (-1,33,True,1.5,None):
            self.config_write(cloud=invalid);self.assertFalse(ops.DispatchPolicy(self.config,'cloud').refresh()['valid'])
    def test_claim_held_through_invalid_config_without_repeat_or_worker_signal(self):
        job={'job_id':'dsh/visual/q_001_r01'};jobdir=self.root/'jobs'/job['job_id'];slot=self.root/'slot'
        self.control.mkdir();(self.root/'plan.json').write_text('{}')
        class Policy:
            count=0
            def refresh(self):
                self.count+=1
                return {'valid':self.count!=3,'target':None if self.count==3 else 1}
        class Child:
            def poll(self):return 0
            def send_signal(self,*_):raise AssertionError('No child signal permitted')
        policy=Policy();args=SimpleNamespace(limit=1,dispatch_role='cloud',concurrency=1)
        def claim(*_):jobdir.mkdir(parents=True);slot.mkdir();return jobdir,slot
        with patch.object(ops,'acquire_claim',side_effect=claim) as acquire,patch.object(ops,'validate_sources') as validate,\
             patch.object(ops,'job_state',return_value='pending'),patch.object(ops.subprocess,'Popen',return_value=Child()) as spawn,\
             patch.object(ops.signal,'signal'),patch.object(ops.time,'sleep'):
            result=ops.dispatch_loop(args,self.root,{'definition':{'cohort_sha256':'sha'}},[job],self.control,{},'controller',policy)
        self.assertEqual(acquire.call_count,1);self.assertEqual(spawn.call_count,1)
        self.assertEqual(result['new_launches'],1);self.assertGreaterEqual(policy.count,6)
        self.assertIn('run_bc_trial_v3_capacity1.py',spawn.call_args.args[0][1])
        self.assertFalse((jobdir/'attempts/attempt_001/result.json').exists())
    def test_stop_reserved_is_durable_terminal_not_retry(self):
        job={'job_id':'x'};jobdir=self.root/'job';attempt=jobdir/'attempts/attempt_001';attempt.mkdir(parents=True)
        slot=self.root/'slot';slot.mkdir()
        with patch.object(ops,'release_slot') as release:
            ops.retire_reserved((job,jobdir,slot,attempt));release.assert_called_once_with(slot)
        result=json.loads((attempt/'result.json').read_text())
        self.assertEqual(result['status'],'not_started');self.assertEqual(result['paid_calls'],0)

if __name__=='__main__':unittest.main()
