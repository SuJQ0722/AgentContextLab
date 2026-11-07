import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from controlled_native_preflight import budget_check, image_ids, prefix_messages, text_only, actual_native_ledger, Client


class NativeControlTests(unittest.TestCase):
    def test_missing_usage_or_native_evidence_cannot_pass(self):
        rows=[{'prompt_tokens':100} for _ in range(3)]
        self.assertTrue(budget_check(rows,100,[['a']]*3,True)['formal_gate_passed'])
        self.assertFalse(budget_check(rows,100,[['a']]*3,False)['formal_gate_passed'])
        self.assertFalse(budget_check(rows[:2]+[{}],100,[['a']]*3,True)['formal_gate_passed'])
        self.assertFalse(budget_check(rows,99,[['a']]*3,True)['formal_gate_passed'])
        self.assertFalse(budget_check(rows,100,[['a'],['b'],['a']],True)['formal_gate_passed'])

    def test_native_identity_includes_detail_and_pixels(self):
        a={'type':'image_url','image_url':{'url':'data:image/png;base64,AAA','detail':'auto'}}
        b={'type':'image_url','image_url':{'url':'data:image/png;base64,AAA','detail':'low'}}
        self.assertNotEqual(image_ids([a]),image_ids([b]))

    def test_native_pixels_never_enter_text_summary(self):
        value=[{'role':'tool','content':[{'type':'text','text':'source number 42'},
               {'type':'image_url','image_url':{'url':'data:image/png;base64,AAAA'}}]},
               {'role':'tool','content':'embedded data:image/jpeg;base64,BBBB number 7'}]
        result=text_only(value)
        self.assertNotIn('base64',str(result));self.assertIn('42',str(result));self.assertIn('number 7',str(result))

    def test_reuse_checks_actual_request_without_calling_gateway(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);folder=out/'calls'/'x';folder.mkdir(parents=True)
            payload={'model':'fixture','messages':[{'role':'user','content':[{'type':'text','text':'old'}]}],'max_tokens':1}
            (folder/'request.json').write_text(json.dumps(payload));(folder/'result.json').write_text('{"status":"completed"}')
            client=object.__new__(Client);client.out=out;client.manifest={'model':'fixture'}
            self.assertEqual(client.call('x',payload['messages'][0]['content'],1)['status'],'completed')
            with self.assertRaisesRegex(RuntimeError,'fingerprint mismatch'):client.call('x',[{'type':'text','text':'new'}],1)

    def test_prefix_does_not_admit_final_answer(self):
        messages=[{'role':'user','content':'task'},
          {'role':'assistant','tool_calls':[{'id':'a'}],'content':''},
          {'role':'tool','content':'source'},
          {'role':'assistant','content':'gold-derived final answer'}]
        result=prefix_messages(messages,10000)
        self.assertEqual([r['role'] for r in result],['assistant','tool'])
        self.assertNotIn('gold-derived',str(result))


if __name__=='__main__':unittest.main()
