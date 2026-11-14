import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from probe_qa_v24 import fit_summary

class MeasuredBudgetTests(unittest.TestCase):
    def test_budget_fit_retains_all_three_source_sections(self):
        class Client:
            def call(self,key,prompt,**kw):return {'usage':{'prompt_tokens':len(prompt.split('ARCHIVE:\n')[1])+10}}
        parts=['AAAA'+'x'*496,'BBBB'+'y'*496,'CCCC'+'z'*496]
        text,proof=fit_summary(Client(),'fixture',{},'\n\n'.join(parts),160,partitions=parts)
        self.assertTrue(proof['matched'])
        for prefix in ('AAAA','BBBB','CCCC'):self.assertIn(prefix,text)

    def test_fit_requires_actual_usage_within_tolerance(self):
        class Client:
            def call(self,key,prompt,**kw):
                return {'usage':{'prompt_tokens':len(prompt.split('ARCHIVE:\n')[1])+10}}
        text,proof=fit_summary(Client(),'fixture',{},'x'*300,110)
        self.assertTrue(proof['matched']);self.assertLessEqual(abs(len(text)+10-110),2.2)

    def test_short_summary_is_not_padded_or_declared_matched(self):
        class Client:
            def call(self,*a,**kw):return {'usage':{'prompt_tokens':20}}
        text,proof=fit_summary(Client(),'fixture',{},'short',100)
        self.assertFalse(proof['matched']);self.assertEqual(text,'short')

    def test_missing_provider_usage_cannot_claim_parity(self):
        class Client:
            def call(self,*a,**kw):return {'status':'transport_failed'}
        _,proof=fit_summary(Client(),'fixture',{},'archive',100)
        self.assertFalse(proof['matched'])
