import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from run_bc_campaign import make_jobs,attempt_state
from run_bc_trial import process_identity


class CampaignTests(unittest.TestCase):
    def test_cross_product_is_unique_and_reproducible(self):
        cfg={'bc100_campaign':{'repeats':3,'strategies':['none','visual'],
             'models':{'hermes':'a','dsh':'b'},'shuffle_seed':4,'timeout_seconds':1800}}
        rows=[{'id':'q_001','question':'Q1'},{'id':'q_002','question':'Q2'}]
        jobs=make_jobs(rows,cfg)
        self.assertEqual(len(jobs),24);self.assertEqual(len({j['job_id'] for j in jobs}),24)
        self.assertEqual(jobs,make_jobs(rows,cfg))
        self.assertEqual({j['repeat'] for j in jobs},{1,2,3})

    def test_resume_skips_timeouts_and_finished_jobs_but_preserves_interruption(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a=root/'attempts/attempt_001';a.mkdir(parents=True)
            for status in ['completed','timeout','failed']:
                (a/'result.json').write_text(json.dumps({'status':status}))
                self.assertEqual(attempt_state(root)[0],'terminal')
            (a/'result.json').write_text(json.dumps({'status':'interrupted'}))
            self.assertEqual(attempt_state(root)[0],'interrupted')

    def test_resume_adopts_live_worker_and_checks_pid_identity(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a=root/'attempts/attempt_001';a.mkdir(parents=True)
            (a/'running.json').write_text(json.dumps({'pid':os.getpid(),'start_identity':process_identity(os.getpid())}))
            self.assertEqual(attempt_state(root)[0],'running')
            (a/'running.json').write_text(json.dumps({'pid':os.getpid(),'start_identity':'stale'}))
            (a/'lease.lock').touch();os.utime(a,(1,1))
            self.assertEqual(attempt_state(root)[0],'interrupted')
