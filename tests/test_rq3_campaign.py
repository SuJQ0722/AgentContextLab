import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_rq3_campaign import make_plan, directory

class RQ3Tests(unittest.TestCase):
    def test_identical_questions_repeats_and_readonly_control_reuse(self):
        cfg={'bc100_campaign':{'models':{'hermes':'model'},'timeout_seconds':1800,'shuffle_seed':7}}
        rows=[{'id':'q1','question':'question 1','answer':'DO NOT LEAK'}, {'id':'q2','question':'question 2','answer':'GOLD'}]
        jobs=make_plan(rows,cfg,Path('/out'),Path('/core'))
        self.assertEqual(len(jobs),42);self.assertEqual(len({j['job_id'] for j in jobs}),42)
        self.assertNotIn('DO NOT LEAK',json.dumps(jobs))
        self.assertEqual(len([j for j in jobs if j.get('external_job_dir')]),6)
        for j in jobs:
            if j['scale']==1:
                self.assertTrue(str(directory(Path('/out'),j)).startswith('/core/jobs/hermes/visual/'))
            else:self.assertNotIn('external_job_dir',j)
        self.assertEqual(jobs,make_plan(rows,cfg,Path('/out'),Path('/core')))

if __name__=='__main__':unittest.main()
