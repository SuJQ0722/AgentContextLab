import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import judge_seven_runtime_v11 as judge

class RuntimeJudgeTests(unittest.TestCase):
    def setUp(self):
        self.job=dict(job_id='hermes/visual/q_001_r01',harness='hermes',strategy='visual',question_id='q_001',repeat=1,model='route')
        self.clean=dict(slot_released=True,native_cleanup_confirmed=True,unconfirmed_child_termination=[])
    def test_partial_not_started_is_missing_not_zero(self):
        result=dict(job_id=self.job['job_id'],status='not_started',failure_category='dispatch_stopped',api_calls=0,attempts=[],**self.clean)
        reason,score,excluded,mismatch=judge.inspect_result(self.job,result)
        self.assertEqual(reason,'not_executed:dispatch_stopped');self.assertIsNone(score);self.assertTrue(excluded);self.assertEqual(len(mismatch),5)
    def test_partial_completed_or_conflicting_identity_is_quarantined(self):
        for result in [dict(job_id=self.job['job_id'],status='completed',**self.clean),dict(self.job,status='completed',**self.clean,final={'text':'fixture'})]:
            result['repeat']=9
            self.assertEqual(judge.inspect_result(self.job,result)[0],'identity_quarantined')
    def test_task_limit_zero_but_retry_budget_missing(self):
        result=dict(self.job,status='failed',failure_category='output_limit',**self.clean)
        self.assertEqual(judge.inspect_result(self.job,result)[1],0.)
        result=dict(job_id=self.job['job_id'],status='not_started',failure_category='prior_attempt_budget_exhausted',api_calls=0,attempts=[],**self.clean)
        self.assertIsNone(judge.inspect_result(self.job,result)[1])
    def test_system_failure_and_timeout_never_become_zero(self):
        for status in ('failed','timeout'):
            result=dict(self.job,status=status,failure_category='execution_error',**self.clean)
            self.assertIsNone(judge.inspect_result(self.job,result)[1])
    def test_valid_completed_still_goes_to_original_bound_grader(self):
        self.assertEqual(judge.inspect_result(self.job,dict(self.job,status='completed',**self.clean))[0],'completed')
    def test_zero_start_needs_no_calls_and_cleanup(self):
        result=dict(job_id=self.job['job_id'],status='not_started',api_calls=1,attempts=[],**self.clean)
        self.assertEqual(judge.inspect_result(self.job,result)[0],'identity_quarantined')

if __name__=='__main__':unittest.main()
