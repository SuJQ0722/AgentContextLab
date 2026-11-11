import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import judge_inline_retry5_v8 as judge

class JudgeV8Tests(unittest.TestCase):
    def test_calibration_filtered_before_candidate_enumeration(self):
        cells={'one':{'plan':{'jobs':[{'job_id':'cal','calibration_not_scored':True},{'job_id':'normal'}]},'answers':{}}}
        with patch.object(judge,'_original_prepare',return_value=(cells,{})):
            result,_=judge.prepare(Path('/unused-source'),Path('/unused-private'))
        self.assertEqual([j['job_id'] for j in result['one']['plan']['jobs']],['normal'])
        self.assertEqual(len(result['one']['all_jobs']),2)
        self.assertEqual(result['one']['calibration_jobs'][0]['job_id'],'cal')

    def test_explicit_http_failure_rotates_with_all_attempt_usage(self):
        calls=[]
        def opener(request,timeout):
            calls.append(json.loads(request.data)['model'])
            if len(calls)==1:
                raise urllib.error.HTTPError(request.full_url,429,'fixture',{},io.BytesIO(b'{"usage":{"total_tokens":7}}'))
            result=io.BytesIO(b'{"usage":{"total_tokens":11},"choices":[]}');result.status=200;result.headers={};return result
        with tempfile.TemporaryDirectory() as directory:
            request=urllib.request.Request('http://fixture/chat/completions',data=json.dumps({'model':judge.ROUTES[0],'messages':[]}).encode())
            with judge.route_opener(Path(directory),opener)(request,180) as response:
                self.assertEqual(json.load(response)['usage']['total_tokens'],11)
            rows=[json.loads(p.read_text()) for p in sorted(Path(directory).glob('http-attempts/*/terminal.json'))]
            self.assertEqual(calls,list(judge.ROUTES[:2]));self.assertEqual([r['raw_provider_usage']['total_tokens'] for r in rows],[7,11])

    def test_unknown_acceptance_never_retried(self):
        count=0
        def opener(*args,**kwargs):
            nonlocal count;count+=1;raise TimeoutError('fixture')
        with tempfile.TemporaryDirectory() as directory:
            request=urllib.request.Request('http://fixture/chat/completions',data=json.dumps({'model':judge.ROUTES[0]}).encode())
            with self.assertRaises(TimeoutError):judge.route_opener(Path(directory),opener)(request,180)
            row=json.loads(next(Path(directory).glob('http-attempts/*/terminal.json')).read_text())
            self.assertEqual(count,1);self.assertIsNone(row['raw_provider_usage']);self.assertEqual(row['status'],'acceptance_unknown')

    def test_missing_control_is_excluded_not_scored_zero(self):
        job={'experiment_kind':'controlled'}
        self.assertEqual(judge.blocked_reason(job,{'status':'blocked'}),'blocked')
        self.assertIsNone(judge.blocked_reason({'experiment_kind':'bc'},{'status':'timeout'}))

if __name__=='__main__':unittest.main()
