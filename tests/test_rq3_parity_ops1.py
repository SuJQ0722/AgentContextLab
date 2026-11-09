import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_rq3_parity_ops1 as ops

class RQ3OpsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'plan.json').write_text('{}')
    def write_status(self,**changes):
        record={'at':100.,'controller_id':'original','stop_dispatch':True,'deferred_error':'BlockingIOError'};record.update(changes)
        (self.root/'status.json').write_text(json.dumps(record));return record
    def test_requires_fresh_stopped_original_with_exact_identity(self):
        self.write_status()
        with patch.object(ops,'owner_alive',return_value=True):
            self.assertEqual(ops.verify_cutover(self.root,120)['original_controller']['controller_id'],'original')
            with self.assertRaisesRegex(ValueError,'stale'):ops.verify_cutover(self.root,160)
            self.write_status(stop_dispatch=False)
            with self.assertRaisesRegex(ValueError,'exception drain'):ops.verify_cutover(self.root,120)
        self.write_status()
        with patch.object(ops,'owner_alive',return_value=False):
            with self.assertRaisesRegex(ValueError,'exact live'):ops.verify_cutover(self.root,120)
    def test_stale_stop_requires_matching_explicit_clean_exit(self):
        self.write_status();(self.root/'controller-exit.json').write_text(json.dumps({'controller_id':'original','drained':True,'stopped':True}))
        with patch.object(ops,'owner_alive',return_value=False):self.assertEqual(ops.verify_cutover(self.root,200)['version'],ops.VERSION)
    def test_adopts_live_original_trials_without_spawning_or_reclaiming(self):
        jobs=[{'job_id':'hermes/scale_0000/q_001_r01'},{'job_id':'hermes/scale_0000/q_002_r01'}]
        for i,job in enumerate(jobs):
            attempt=self.root/'jobs'/job['job_id']/'attempts/attempt_001';attempt.mkdir(parents=True)
            (attempt/'worker-started.json').write_text(json.dumps({'pid':i}))
        with patch.object(ops,'owner_alive',side_effect=lambda r:r['pid']==0):active=ops.adopt(self.root,{'jobs':jobs})
        self.assertEqual(list(active),[jobs[0]['job_id']]);self.assertIsNone(active[jobs[0]['job_id']]['process'])
    def test_error_artifact_has_frames_not_secret_message_or_locals(self):
        try:raise OSError('SECRET-PASSWORD')
        except OSError as error:value=ops.safe_error(error)
        self.assertNotIn('SECRET',json.dumps(value));self.assertTrue(value['trace_frames'])

if __name__=='__main__':unittest.main()
