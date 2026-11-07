import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from info_loss_eval import valid_facts, exact_score, condition

class InfoLossTests(unittest.TestCase):
    def test_fact_validation_requires_exact_evidence_and_no_answer_leak(self):
        source='Alice visited https://example.org in 1927.'
        good={'type':'number','answer':'1927','quote':source,'question':'Which year did Alice visit?'}
        bad=dict(good,quote='Not present')
        leak=dict(good,question='Did she visit in 1927?')
        self.assertEqual(len(valid_facts({'facts':[good,bad,leak]},source)),1)
    def test_exact_qa_does_not_reward_answer_embedded_in_wrong_long_text(self):
        self.assertEqual(exact_score({'f1':'1927 or 1928'},[{'id':'f1','answer':'1927'}]),0)
    def test_reconstruction_and_qa_never_receive_reference_answers(self):
        class Fake:
            def __init__(self):self.calls=[]
            def call(self,key,prompt,images=()):
                self.calls.append((key,prompt))
                return {'status':'completed','content':'{}','finish_reason':'stop'}
        fake=Fake();facts=[{'id':'f1','answer':'SECRET_123','quote':'SECRET_123','question':'What code?'}]
        condition(fake,'test',{'images':[]},facts,'original source SECRET_123')
        self.assertNotIn('SECRET_123',fake.calls[0][1]);self.assertNotIn('SECRET_123',fake.calls[1][1]);self.assertIn('SECRET_123',fake.calls[2][1])

if __name__=='__main__':unittest.main()
