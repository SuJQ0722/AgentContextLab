import sys,os,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import preflight_dsh_transport_v4 as p
class NodeReadinessTests(unittest.TestCase):
 def test_transient_retry_then_auth_challenge(self):
  with tempfile.TemporaryDirectory()as d,patch.dict(os.environ,{'TOKENHUB_BASE_URL':'https://fixture.invalid/v1'}),patch.object(p.subprocess,'run',side_effect=[SimpleNamespace(returncode=0,stdout='{"passed":false,"cause_code":"ECONNRESET"}'),SimpleNamespace(returncode=0,stdout='{"passed":true,"status":401}')])as invoke,patch.object(p.time,'sleep'):
   result=p.check(Path(d));self.assertTrue(result['passed']);self.assertEqual(invoke.call_count,2)
   self.assertNotIn('Authorization',p.PROBE);self.assertIn("'/models'",p.PROBE)
 def test_network_failure_blocks_dispatch(self):
  with tempfile.TemporaryDirectory()as d,patch.dict(os.environ,{'TOKENHUB_BASE_URL':'https://fixture.invalid/v1'}),patch.object(p.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{"passed":false,"cause_code":"ENETUNREACH"}'))as invoke,patch.object(p.time,'sleep'):
   with self.assertRaisesRegex(RuntimeError,'dispatch prohibited'):p.check(Path(d))
   self.assertEqual(invoke.call_count,5)
if __name__=='__main__':unittest.main()
