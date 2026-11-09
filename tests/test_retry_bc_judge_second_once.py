import json
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import retry_bc_judge_second_once as retry
import judge_bc_v3_completed as judge
from report_bc_v3_scored import observation

class SecondJudgeRetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'source';self.root.mkdir();self.grading=Path(self.tmp.name)/'grading';self.grading.mkdir()
        self.job={'job_id':retry.JOB,'harness':'hermes','strategy':'none','question_id':'q_096','question':'Q','repeat':1}
        self.attempt=self.root/'jobs'/retry.JOB/'attempts/attempt_001';self.attempt.mkdir(parents=True);self.result=self.attempt/'result.json'
        self.result.write_text(json.dumps({'status':'completed','final':{'text':'P'},'slot_released':True,'unconfirmed_child_termination':[]}))
        (self.root/'cohort.jsonl').write_text(json.dumps({'id':'q_096','question':'Q','answer':'SECRET-GOLD'})+'\n')
        self.base=self.grading/'sources'/judge.namespace(self.root)/'jobs'/retry.JOB;self.base.mkdir(parents=True)
        self.binding={'job_id':retry.JOB,'root':str(self.root),'question_id':'q_096','result_path':str(self.result),'result_sha256':judge.sha(self.result),
            'attempt_path':str(self.attempt),'cohort_sha256':judge.sha(self.root/'cohort.jsonl')}
        (self.base/'binding.json').write_text(json.dumps(self.binding))
        self.config={'judge_model':judge.MODEL,'max_tokens':8192,'temperature':0,'top_p':1,'timeout_seconds':180}
        (self.grading/'protocol.json').write_text(json.dumps(self.config))
        self.payload={'model':judge.MODEL,'messages':[{'role':'user','content':judge.build_judge_prompt('Q','P','SECRET-GOLD')}],
            'max_tokens':8192,'temperature':0,'top_p':1};self.reqsha=judge.sha_bytes(json.dumps(self.payload,ensure_ascii=False).encode())
        (self.base/'request.json').write_text(json.dumps(self.payload));(self.base/'request-dispatched.json').write_text(json.dumps({'request_sha256':self.reqsha}))
        self.old={'status':'judge_error','error_type':'URLError','score':None,'request_sha256':self.reqsha}
        (self.base/'grade.json').write_text(json.dumps(self.old))
    def test_identical_payload_separate_directory_and_original_retained(self):
        candidate,config,auth=retry.prepare(self.grading,self.root)
        self.assertNotEqual(candidate['directory'],self.base);self.assertEqual(candidate['prediction'],'P');self.assertEqual(config,self.config)
        self.assertEqual(json.loads((self.base/'grade.json').read_text()),self.old);self.assertEqual(auth['max_additional_requests'],1)
    def test_changed_request_or_result_rejected(self):
        altered=dict(self.payload,max_tokens=100);(self.base/'request.json').write_text(json.dumps(altered))
        with self.assertRaisesRegex(ValueError,'identical'):retry.prepare(self.grading,self.root)
        (self.base/'request.json').write_text(json.dumps(self.payload));self.result.write_text('{}')
        with self.assertRaisesRegex(ValueError,'Prediction changed'):retry.prepare(self.grading,self.root)
    def test_unknown_extra_attempt_never_resubmitted_and_fixed_selection(self):
        candidate,config,auth=retry.prepare(self.grading,self.root);directory=candidate['directory'];directory.mkdir(parents=True)
        (directory/'request-started.json').write_text('{}')
        def forbidden(*a,**k):raise AssertionError('Must never call model again')
        self.assertEqual(judge.grade(candidate,config,{},opener=forbidden)['status'],'already_claimed')
        row=observation(self.job,self.attempt,self.grading);self.assertIsNone(row['score']);self.assertIn('fixed_additional',row['judge_selection'])
        (directory/'grade.json').write_text(json.dumps({'status':'scored','score':0,'result_sha256':judge.sha(self.result),'attempt_path':str(self.attempt)}))
        self.assertEqual(observation(self.job,self.attempt,self.grading)['score'],0)

if __name__=='__main__':unittest.main()
