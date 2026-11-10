import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import diagnose_controlled_calibration_v1 as diagnostic

class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        self.out=root/'diag';self.out.mkdir();self.source=root/'source';self.source.mkdir();(self.source/'metrics').mkdir()
        self.patches=[patch.object(diagnostic,'OUT',self.out),patch.object(diagnostic,'SOURCE',self.source)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.old={'model':diagnostic.MODEL,'messages':[{'role':'user','content':'same exact archived question'}],
            'tools':[{'type':'function','function':{'name':'web_search','parameters':{'type':'object'}}}], 'max_tokens':1,'stream':False}
        captured=copy.deepcopy(self.old);captured['messages']=[{'role':'user','content':'different live workspace path'}]
        (self.out/'captured-body.json').write_bytes(diagnostic.body(captured))
        with gzip.open(self.source/'metrics/requests-responses.jsonl.gz','wt') as f:f.write(json.dumps(dict(type='request',model=diagnostic.MODEL,messages=self.old['messages'],max_tokens=1))+'\n')
        (self.source/'bounded-protocol.json').write_text('{}');(self.source/'spec.json').write_text('{"config_path":"config.json"}')
        (self.source/'bounded-wire-guard.jsonl').write_text(json.dumps({'body_sha256':diagnostic.digest(diagnostic.body(self.old)),'body_bytes':len(diagnostic.body(self.old))})+'\n')
    def test_full_wire_identity_and_exactly_three_changes(self):
        report=diagnostic.prepare();new=json.loads((self.out/'diagnostic-body.json').read_text())
        self.assertEqual(set(report['changes']),{'max_tokens','tool_choice','thinking'})
        self.assertEqual(new['messages'],self.old['messages']);self.assertEqual(new['tools'],self.old['tools'])
        self.assertTrue(report['original_body_matches_wire_sha']);self.assertFalse(report['guard']['violations'])
    def test_mismatched_tools_fail_before_any_network(self):
        captured=json.loads((self.out/'captured-body.json').read_text());captured['tools']=[]
        (self.out/'captured-body.json').write_text(json.dumps(captured))
        with self.assertRaises(ValueError):diagnostic.prepare()
        self.assertFalse((self.out/'started.json').exists())
    def test_existing_started_marker_never_replays(self):
        diagnostic.prepare();(self.out/'started.json').write_text('{}')
        with patch.object(diagnostic,'environment') as env:
            with self.assertRaises(ValueError):diagnostic.live()
            env.assert_not_called()
    def test_fake_single_http_response_has_raw_usage(self):
        class Response:
            status_code=200;headers={};is_success=True
            def json(self):return {'model':diagnostic.MODEL,'choices':[{'finish_reason':'stop'}],
                'usage':{'prompt_tokens':42,'completion_tokens':2,'total_tokens':44}}
        class Client:
            calls=0
            def __init__(self,**kwargs):self.kwargs=kwargs
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def post(self,*a,**kw):Client.calls+=1;return Response()
        with patch('httpx.Client',Client),patch.object(diagnostic,'environment',return_value=({'TOKENHUB_BASE_URL':'https://tokenhub.sensetime.com/v1','TOKENHUB_API_KEY':'fixture'},{})):
            result=diagnostic.live();self.assertEqual(result['raw_provider_usage']['total_tokens'],44)
            with self.assertRaises(ValueError):diagnostic.live()
        self.assertEqual(Client.calls,1);self.assertIsNone(result['provider_latency_seconds'])

if __name__=='__main__':unittest.main()
