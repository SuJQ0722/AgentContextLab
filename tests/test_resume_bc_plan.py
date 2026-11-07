import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from resume_bc_plan import classify_result,eligible,GUARD

class ResumePlanTests(unittest.TestCase):
    def setUp(self):
        self.result={'status':'failed','harness':'dsh','failure_category':'execution_error'}
        self.native={'status':'failed','final':{'sessionId':'session-1','reason':{'kind':'error','error':{'message':GUARD,'code':'UNKNOWN'}}}}
        self.comp=[{'session_id':'session-1','valid':False,'budget':16384,'post_compression_tokens':16522,'token_measurement':'dsh_token_meter_estimate'}]
    def test_proven_guard_classified_without_mutation(self):
        import copy
        before=copy.deepcopy((self.result,self.native,self.comp))
        self.assertEqual(classify_result(self.result,self.native,self.comp),'budget_limit')
        self.assertEqual((self.result,self.native,self.comp),before)
    def test_tool_text_cannot_impersonate_guard(self):
        self.native['final']['reason']={'kind':'stop'}
        self.native['final']['text']=GUARD
        self.assertEqual(classify_result(self.result,self.native,self.comp),'unexpected_failure')
    def test_message_substring_and_missing_proof_rejected(self):
        self.assertEqual(classify_result(self.result,self.native,[]),'unexpected_failure')
        self.native['final']['reason']['error']['message']='Tool error: '+GUARD
        self.assertEqual(classify_result(self.result,self.native,self.comp),'unexpected_failure')
    def test_wrong_session_or_budget_not_exempted(self):
        self.comp[0]['session_id']='other'
        self.assertEqual(classify_result(self.result,self.native,self.comp),'unexpected_failure')
        self.comp[0]['session_id']='session-1';self.comp[0]['budget']=99999
        self.assertEqual(classify_result(self.result,self.native,self.comp),'unexpected_failure')
    def test_no_terminal_or_running_retry(self):
        self.assertFalse(eligible('terminal','job',{'job'}))
        self.assertFalse(eligible('running','job',{'job'}))
        self.assertFalse(eligible('interrupted','job',set()))
        self.assertTrue(eligible('pending','job',set()))
        self.assertTrue(eligible('interrupted','job',{'job'}))
    def test_provider_malformed_response_remains_unexpected(self):
        self.native['final']['reason']['error']={'code':'MALFORMED_RESPONSE','message':'Bad tool JSON'}
        self.assertEqual(classify_result(self.result,self.native,self.comp),'unexpected_failure')
