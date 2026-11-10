import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import run_bounded_window_five_arm_v1 as module

class FiveArmTests(unittest.TestCase):
    def test_questions_exclude_references(self):
        facts=[{'id':'f1','type':'numeral','question':'What was the recorded count?','answer':'846231','quote':'The count was 846231.'}]
        prompt=module.qa_prompt(facts)
        self.assertNotIn('846231',prompt)
        self.assertNotIn('quote',prompt)
        self.assertIn('What was the recorded count?',prompt)
        with self.assertRaises(ValueError): module.qa_prompt([{**facts[0],'question':'Was it 846231?'}])

    def test_unknown_cache_stays_unknown(self):
        counts=module.token_counts({'prompt_tokens':100,'completion_tokens':10,'total_tokens':110})
        self.assertIsNone(counts['cached_input']); self.assertIsNone(counts['non_cache_input'])
        self.assertEqual(module.token_counts({'prompt_tokens':100,'prompt_tokens_details':{'cached_tokens':20}})['non_cache_input'],80)
        self.assertIsNone(module.token_counts({'prompt_tokens':100,'prompt_cache_hit_tokens':120})['cached_input'])

    def test_truncation_and_reasoning_invalid(self):
        good={'status':'completed','finish_reason':'stop','content':'answer','reasoning_tokens':0}
        self.assertTrue(module.valid_response(good))
        for key,value in [('status','provider_error'),('finish_reason','length'),('reasoning_tokens',10)]:
            self.assertFalse(module.valid_response({**good,key:value}))

    def test_qa_missing_not_wrong(self):
        facts=[{'id':'f1','answer':'Paris'}]
        self.assertIsNone(module.score_qa('broken',facts)['exact_matches']['f1'])
        self.assertFalse(module.score_qa('{"answers":[{"id":"f1","answer":"London"}]}',facts)['exact_matches']['f1'])
        self.assertTrue(module.score_qa('{"answers":[{"id":"f1","answer":" PARIS "}]}',facts)['exact_matches']['f1'])

    def test_judge_schema(self):
        facts=[{'id':'f1'}]
        with self.assertRaises(ValueError): module.validate_judge('{"facts":[{"id":"f1","reconstruction_supported":"true","qa_correct":true}]}',facts)
        result=module.validate_judge('{"facts":[{"id":"f1","reconstruction_supported":true,"qa_correct":false}]}',facts)
        self.assertTrue(result['facts'][0]['reconstruction_supported'])

    def test_empty_facts_retained_and_no_qa(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=root/'source.txt'; source.write_text('Opaque original source')
            reps=root/'reps.json'; reps.write_text(json.dumps({m:[{'type':'text','text':'representation'}] for m in module.METHODS if m!='summary'}))
            window={'id':'q_009_late','split':'holdout','question_id':'q_009','position':'late','source_message_positions':[{'distance_rounds':4}], 'source_window_path':str(source),'representations_path':str(reps)}
            called=[]
            def fake_stage(root,key,payload,env):
                called.append((key,payload)); content='{"facts":[]}' if key.endswith('__facts') else 'Opaque original source'
                return {'finish_reason':'stop'},content
            with patch.object(module,'stage',fake_stage): result=module.process_window(root,{'model':'test'},window,{})
            self.assertEqual(len(called),7)
            self.assertTrue(all(row['qa_status']=='empty_facts' for row in result['rows']))
            self.assertTrue(all(x[1]['max_tokens']==768 and x[1]['thinking']=={'type':'disabled'} for x in called))
            self.assertEqual(result['rows'][0]['source_message_positions'][0]['distance_rounds'],4)

    def test_unresolved_call_never_replays(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); module.save(root/'calls'/'example'/'started.json',{'attempt':1})
            with self.assertRaisesRegex(ValueError,'Unresolved paid'):
                module.call(root,'example',module.make_request('test','hello'),{})

if __name__=='__main__': unittest.main()
