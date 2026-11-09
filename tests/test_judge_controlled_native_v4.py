import io,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import judge_controlled_native_v4 as judge
class Response(io.BytesIO):
    status=200;headers={}
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
class JudgeTests(unittest.TestCase):
    def candidate(self,folder):
        root=Path(folder);native=root/'native';native.mkdir();binding={}
        for name in ('result','conversation','spec','prefix','control'):
            path=native/(name+'.json');path.write_text('{}');binding[name+'_path']=str(path);binding[name+'_sha256']=judge.shared.sha(path)
        return {'directory':root/'private-grade','binding':binding,'question':'Fixture question','prediction':'fixture response','answer':'PRIVATE_GOLD_ONLY'},native
    def config(self):return {'judge_model':judge.shared.MODEL,'max_tokens':8192,'temperature':0,'top_p':1,'timeout_seconds':5}
    def test_one_request_strict_score_isolated_gold_and_raw_cache_zero(self):
        with tempfile.TemporaryDirectory() as f:
            candidate,native=self.candidate(f);calls=[]
            def opener(request,timeout):
                calls.append(json.loads(request.data));return Response(json.dumps({'model':'deepseek-v4-1-flash-261017','choices':[{'finish_reason':'stop','message':{'content':'{"score":1,"reason":"same"}'}}],'usage':{'prompt_tokens':10,'prompt_tokens_details':{'cached_tokens':0},'completion_tokens':2,'total_tokens':12}}).encode())
            env={'TOKENHUB_BASE_URL':'http://127.0.0.1/v1','TOKENHUB_API_KEY':'fixture'}
            result=judge.grade_bound(candidate,self.config(),env,opener);self.assertEqual(result['score'],1)
            self.assertEqual(result['usage']['noncache_input_tokens'],10)
            self.assertEqual(judge.grade_bound(candidate,self.config(),env,opener)['status'],'already_claimed');self.assertEqual(len(calls),1)
            self.assertFalse(any('PRIVATE_GOLD_ONLY' in p.read_text() for p in native.iterdir()))
            self.assertIn('PRIVATE_GOLD_ONLY',(candidate['directory']/'request.json').read_text())
    def test_prefix_mutation_blocks_all_network(self):
        with tempfile.TemporaryDirectory() as f:
            candidate,_=self.candidate(f);Path(candidate['binding']['prefix_path']).write_text('{"changed":true}')
            with self.assertRaises(ValueError):judge.grade_bound(candidate,self.config(),{},lambda *args: self.fail('Network must not be called'))
    def test_unmatched_or_unknown_gate_excluded(self):
        controls=[{'passed':True,'native_identity_verified':True,'first_actual_prompt_tokens':n,'native_hashes':['a'],'prefix_sha256':'fixed','actual_route':judge.shared.MODEL} for n in (5229,5267,5236)]
        self.assertTrue(judge.group_gate(controls));controls[1]['first_actual_prompt_tokens']=None;self.assertFalse(judge.group_gate(controls))
        self.assertIsNone(judge.shared.strict_score('{"reason":"missing score"}'))
if __name__=='__main__':unittest.main()
