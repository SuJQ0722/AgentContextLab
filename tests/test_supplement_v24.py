import copy,json,sys,tempfile,unittest,subprocess,shutil
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import supplement_recovery_v24 as recovery
import supplement_worker_v24 as worker

class SupplementTests(unittest.TestCase):
    def test_dsh_three_send_ceiling_and_third_send_success(self):
        root=Path(__file__).resolve().parents[1]
        node=root/'.tools/node-v24.11.0-linux-x64/bin/node'
        executable=str(node) if node.exists() else shutil.which('node')
        if not executable:self.skipTest('Node unavailable')
        result=subprocess.run([executable,str(root/'tests/supplement_wire_v24.mjs')],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_protocol_overrides_all_native_budgets_without_mutating_source(self):
        old={'max_output_tokens':8192,'transport_runtime_policy':{'max_failed_sends':99},
             **{k:{'max_rounds':500,'timeout_seconds':3600}for k in ('pilot','bc100','bc100_campaign','mmbc100_campaign')}}
        cfg=recovery.configuration(old);worker.validate(cfg,cfg)
        self.assertEqual(old['pilot']['max_rounds'],500)
        self.assertEqual(cfg['mmbc100_campaign']['timeout_seconds'],10800)
        for field,value in [('max_rounds',500),('timeout_seconds',3600),('max_http_sends',4)]:
            bad=copy.deepcopy(cfg);bad[field]=value
            with self.assertRaises(ValueError):worker.validate(bad,cfg)

    def test_actual_constructor_rejects_old_turn_limit(self):
        class Agent:
            def __init__(self,**kw):self.max_iterations=kw['max_iterations']
        with tempfile.TemporaryDirectory() as d:
            wrapped=worker.checked_init(Agent.__init__,Path(d));a=Agent(max_iterations=200)
            wrapped(a,max_iterations=200)
            self.assertEqual(json.loads((Path(d)/'metrics/turn-limit-v24.json').read_text())['actual_max_iterations'],200)
            with self.assertRaises(ValueError):wrapped(a,max_iterations=500)

    def test_transport_always_uses_three_hours_and_three_physical_sends(self):
        with patch.object(worker.bounded,'install',return_value={}) as install:
            worker.install_runtime({'max_failed_sends':99},Path('/tmp/unused'),deadline_seconds=3600)
            self.assertEqual(install.call_args.kwargs['deadline_seconds'],10800)
            self.assertEqual(install.call_args.kwargs['max_http_attempts'],3)
            self.assertEqual(install.call_args.args[0]['max_failed_sends'],3)

    def test_immutable_receipt_prevents_replay_with_different_identity(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'dispatch.json';recovery.immutable(p,{'id':1});recovery.immutable(p,{'id':1})
            with self.assertRaises(ValueError):recovery.immutable(p,{'id':2})
