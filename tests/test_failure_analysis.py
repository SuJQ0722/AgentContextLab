import unittest
from scripts.analyze_failures import classify,bucket

class FailureEvidenceTests(unittest.TestCase):
    def test_retrieved_context_claim_is_not_runtime_error(self):
        r=classify({'messages':[{'role':'tool','content':'maximum context length exceeded'}]}, {}, None)
        self.assertFalse(r['context_limit_evidence']);self.assertTrue(r['unscored']);self.assertFalse(r['wrong_answer'])
    def test_positive_runtime_and_finish_evidence(self):
        r=classify({}, {'error':'Error code: 400 context_length_exceeded','history':[{'finish_reason':'length'}]},0)
        self.assertTrue(r['context_limit_evidence']);self.assertTrue(r['api_error_evidence']);self.assertTrue(r['truncation_evidence']);self.assertTrue(r['wrong_answer'])
    def test_bins(self):
        self.assertEqual(bucket(None),'missing');self.assertEqual(bucket(10),'0–10');self.assertEqual(bucket(11),'11–30');self.assertEqual(bucket(101),'101+')
