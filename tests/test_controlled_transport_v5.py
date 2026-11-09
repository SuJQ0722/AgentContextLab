import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from controlled_transport_v5 import cause_chain,fingerprint
class TransportTests(unittest.TestCase):
    def test_diagnostics_preserve_cause_types_without_secrets(self):
        inner=ConnectionResetError(104,'connection reset SECRET_AUTH_BODY');outer=RuntimeError('SECRET_AUTH_BODY')
        outer.__cause__=inner;result=cause_chain(outer)
        self.assertEqual([x['type'] for x in result],['RuntimeError','ConnectionResetError'])
        self.assertEqual(result[-1]['errno'],104);self.assertIn('connection_reset',result[-1]['hints'])
        self.assertNotIn('SECRET_AUTH_BODY',json.dumps(result));self.assertNotIn('message',result[0])
    def test_fingerprint_includes_scientific_inputs(self):
        request={'model':'approved','messages':[{'role':'user','content':'fixed'}],'max_tokens':8192,'stream':True}
        self.assertEqual(fingerprint(request),fingerprint(dict(request,extra_headers={'secret':'not_logged'},timeout=10)))
        self.assertNotEqual(fingerprint(request),fingerprint(dict(request,max_tokens=1)))
        self.assertNotEqual(fingerprint(request),fingerprint(dict(request,messages=[{'role':'user','content':'different'}])))
    def test_exception_context_cycle_is_bounded(self):
        a=RuntimeError();b=OSError();a.__cause__=b;b.__context__=a
        self.assertEqual(len(cause_chain(a)),2)
if __name__=='__main__':unittest.main()
