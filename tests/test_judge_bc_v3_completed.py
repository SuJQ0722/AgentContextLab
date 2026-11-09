import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import judge_bc_v3_completed as judge


class Reply(io.StringIO):
    status=200
    headers={'x-request-id':'fixture-request'}


class CompletedJudgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'campaign';self.root.mkdir();self.output=Path(self.temp.name)/'grading'
        row={'id':'q_001','question':'What is the colour?','answer':'purple'}
        (self.root/'cohort.jsonl').write_text(json.dumps(row)+'\n');self.cohort=judge.sha(self.root/'cohort.jsonl')
        self.job={'job_id':'hermes/none/q_001_r01','harness':'hermes','strategy':'none','question_id':'q_001','question':row['question'],'repeat':1,'model':judge.MODEL}
        (self.root/'plan.json').write_text(json.dumps({'definition':{'cohort_sha256':self.cohort},'jobs':[self.job]}))
        (self.root/'experiment.json').write_text(json.dumps({'model':judge.MODEL}))
        self.attempt=self.root/'jobs'/self.job['job_id']/'attempts/attempt_001';self.attempt.mkdir(parents=True)
        self.result={**self.job,'status':'completed','slot_released':True,'unconfirmed_child_termination':[],'final':{'text':'It is purple.'}}
        (self.attempt/'result.json').write_text(json.dumps(self.result))
        self.config={'judge_model':judge.MODEL,'max_tokens':8192,'temperature':0,'top_p':1,'timeout_seconds':3}
        self.env={'TOKENHUB_BASE_URL':'https://fixture.invalid/v1','TOKENHUB_API_KEY':'LOCAL_TEST_SECRET'}

    def candidate(self):return judge.source_inventory(self.root,self.output,self.cohort)[0][0]

    def reply(self,score=1,usage=None):
        return Reply(json.dumps({'model':'deepseek-v4-1-flash-261017','choices':[{'finish_reason':'stop','message':{'content':json.dumps({'reason':'same meaning','score':score})}}],
            'usage':usage if usage is not None else {'prompt_tokens':20,'completion_tokens':5,'total_tokens':25}}))

    def test_complete_grade_binds_sources_and_preserves_missing_cache(self):
        candidate=self.candidate();calls=[]
        def opener(request,timeout):calls.append(json.loads(request.data));return self.reply()
        record=judge.grade(candidate,self.config,self.env,opener)
        self.assertEqual(record['score'],1);self.assertEqual(record['api_calls'],1)
        self.assertIsNone(record['usage']['cached_input_tokens']);self.assertIsNone(record['usage']['noncache_input_tokens'])
        self.assertTrue(record['usage']['conservation']);self.assertEqual(calls[0]['model'],judge.MODEL)
        self.assertIn('[Standard Answer]: purple',calls[0]['messages'][0]['content'])
        self.assertEqual(list(self.attempt.iterdir()),[self.attempt/'result.json'])
        self.assertNotIn('LOCAL_TEST_SECRET',(candidate['directory']/'request.json').read_text())
        self.assertEqual(judge.grade(candidate,self.config,self.env,opener)['status'],'already_claimed');self.assertEqual(len(calls),1)

    def test_unknown_started_request_is_not_resent_or_assigned_zero(self):
        candidate=self.candidate();directory=candidate['directory'];directory.mkdir(parents=True)
        (directory/'request-started.json').write_text('{}')
        with patch.object(judge.urllib.request,'urlopen',side_effect=AssertionError('must not call')):
            result=judge.grade(candidate,self.config,self.env)
        self.assertEqual(result['status'],'already_claimed');self.assertFalse((directory/'grade.json').exists())
        candidates,report=judge.source_inventory(self.root,self.output,self.cohort)
        self.assertEqual(candidates,[]);self.assertEqual(report['existing_grades']['request_outcome_unresolved'],1)

    def test_nonbinary_judge_score_is_invalid_not_silently_incorrect(self):
        result=judge.grade(self.candidate(),self.config,self.env,lambda *a,**k:self.reply(score=2))
        self.assertEqual(result['status'],'invalid_judge_response');self.assertIsNone(result['score'])
        self.assertIsNone(judge.strict_score('{"score":true}'))

    def test_noncompleted_cleanup_and_changed_sources_are_not_graded(self):
        self.result['slot_released']=False;(self.attempt/'result.json').write_text(json.dumps(self.result))
        self.assertEqual(judge.source_inventory(self.root,self.output,self.cohort)[0],[])
        self.result['slot_released']=True;(self.attempt/'result.json').write_text(json.dumps(self.result));candidate=self.candidate()
        self.result['final']={'text':'changed'};(self.attempt/'result.json').write_text(json.dumps(self.result))
        with self.assertRaisesRegex(ValueError,'Prediction changed'):
            judge.grade(candidate,self.config,self.env,lambda *a,**k:self.reply())
        (self.root/'cohort.jsonl').write_text('changed')
        with self.assertRaisesRegex(ValueError,'cohort differs'):self.candidate()

    def test_empty_completed_answer_scores_zero_without_api(self):
        self.result['final']={'text':''};(self.attempt/'result.json').write_text(json.dumps(self.result))
        result=judge.grade(self.candidate(),self.config,self.env,lambda *a,**k:(_ for _ in ()).throw(AssertionError('no API')))
        self.assertEqual((result['status'],result['score'],result['api_calls']),('scored',0,0))
        self.assertEqual(judge.usage_fields({'prompt_tokens':20,'completion_tokens':5,'total_tokens':25,'prompt_tokens_details':{'cached_tokens':0}})['cached_input_tokens'],0)


if __name__=='__main__':unittest.main()
