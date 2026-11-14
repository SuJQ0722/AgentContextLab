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
import controlled_mmbc_source_v17 as v


class ControllerTests(unittest.TestCase):
    def make(self, root, action='matched_continuation'):
        out=root/'cells/window/jobs/q1_r01/attempt_001'
        job={'job_id':'window/q1_r01','question_id':'q1','repeat':1,'method':'window',
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
                v.run_controller(root,plan,'window',popen=popen,clock=clock)
                v.run_controller(root,plan,'window',popen=popen,clock=clock)
            self.assertEqual(len(calls),1)
            result=v.read(out/'terminal.json')
            self.assertEqual(result['status'],'timeout')
            self.assertFalse(result['will_retry'])
            self.assertTrue(result['native_cleanup_confirmed'])
            self.assertTrue(v.read(root/'cells/window/status.json')['drained'])

    def test_unknown_prior_claim_never_dispatched(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan,job,out=self.make(root)
            v.save(out/'dispatch.json',{'prior_unknown':True})
            with patch.object(v,'environment',return_value=(dict(os.environ),{})),patch.object(v,'python_for',side_effect=AssertionError('dispatch')):
                v.run_controller(root,plan,'window')
            status=v.read(root/'cells/window/status.json')
            self.assertFalse(status['drained'])
            self.assertEqual(status['unknown_prior_claims'],[job['job_id']])
            self.assertFalse((out/'terminal.json').exists())

    def test_no_intervention_reuse_is_not_new_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan,job,out=self.make(root,'no_compression_reuse')
            with patch.object(v,'environment',return_value=(dict(os.environ),{})),patch.object(v,'python_for',side_effect=AssertionError('dispatch')):
                v.run_controller(root,plan,'window')
            result=v.read(out/'terminal.json')
            self.assertEqual(result['status'],'no_compression_reuse')
            self.assertEqual(result['new_attempts'],0)
            self.assertTrue(v.read(root/'cells/window/status.json')['drained'])

    def test_changed_source_result_rejected_before_paid_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.json';source.write_text('{}')
            job={'source_result_path':str(source),'source_result_sha256':v.sha(source),'action':'blocked'}
            source.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,'Source result changed'):v.validate_job(job)

    def test_configured_method_concurrency_is_exactly_16(self):
        with self.assertRaisesRegex(ValueError,'exactly16'):
            v.run_controller(Path('/not-created'),{'jobs':[]},'window',concurrency=8)

if __name__=='__main__':unittest.main()
