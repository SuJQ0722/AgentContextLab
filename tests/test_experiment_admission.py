import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from experiment_admission import capacity,is_worker
from resume_rq3_plan import eligible

class AdmissionTests(unittest.TestCase):
    def snapshot(self,n):return {i:{'ppid':0,'identity':str(i),'cmd':'ordinary'} for i in range(1,n+1)}
    def test_strict_cap_includes_core_reserve(self):
        ok,report,_=capacity(self.snapshot(60),[],4)
        self.assertFalse(ok);self.assertGreater(report['projected'],127)
    def test_reservations_account_for_future_children(self):
        snap=self.snapshot(10)
        reservation={'pid':1,'identity':'1','process_cost':4}
        ok,report,alive=capacity(snap,[reservation],4)
        self.assertEqual(report['supplement_reserved_growth'],3)
        snap[2]['ppid']=1;snap[3]['ppid']=2
        _,report,_=capacity(snap,[reservation],4)
        self.assertEqual(report['supplement_reserved_growth'],1)
    def test_recycled_pid_not_adopted(self):
        _,report,alive=capacity(self.snapshot(10),[{'pid':1,'identity':'stale','process_cost':4}],4)
        self.assertEqual(alive,[])
    def test_no_terminal_unknown_or_interrupted_retry(self):
        for state in ['terminal','interrupted','running','unknown']:self.assertFalse(eligible(state))
        self.assertTrue(eligible('pending'))

    def test_shell_substring_is_not_worker(self):
        self.assertFalse(is_worker({'argv':['bash','-c','python scripts/run_bc_trial.py --spec /x']},'run_bc_trial.py'))
        self.assertTrue(is_worker({'argv':['python','/root/scripts/run_bc_trial.py','--spec','/x']},'run_bc_trial.py'))
