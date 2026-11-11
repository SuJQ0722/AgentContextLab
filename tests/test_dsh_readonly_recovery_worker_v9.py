"""Nonpaid native CLI assembly regression for readonly-options runtime recovery."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import dsh_readonly_recovery_worker_v9 as worker
from inline_route_contract_v2 import ROUTES
from one_hour_timeout_retry_v1 import VERSION

class ReadonlyWorkerTests(unittest.TestCase):
    def test_real_baseline_wrapper_changes_only_observer_and_separates_final_negative_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);workspace=root/'native/discard/q/workspace';workspace.mkdir(parents=True)
            cfg={'timeout_seconds':3600,'one_hour_retry_version':VERSION,'model':ROUTES[0],'approved_model_routes':ROUTES,
                 'model_route_policy':'four-route-rotation-v1','transport_runtime_version':'visual-transport-runtime-v4',
                 'image_transport':'inline-recent-ten-chunked-v1','transport_delivery_version':'inline-direct-v1',
                 'gateway_proxy':'http://10.120.0.246:7890'}
            path=root/'config.json';path.write_text(json.dumps(cfg))
            plugins=[{'insert':[{'id':'acl-wire-expectations','name':str(worker.ROOT/'scripts/dsh_wire_expectations.mjs'),'config':{'expectedFile':str(workspace/'expected.json')}},
                               {'id':'other-plugin','name':'unchanged','config':{'value':1}}]}, {'id':'llm-pi-ai','config':{'same':'provider'}}]
            saved=copy.deepcopy(plugins);overlay=workspace.parent/'evaluation.patch.json';overlay.write_text(json.dumps(plugins))
            env={'ACL_WORKSPACE':str(workspace),'ACL_STRATEGY':'discard','ACL_PYTHON':sys.executable,
                 'NODE_OPTIONS':'--import '+str(worker.ROOT/'scripts/dsh_wire_image_guard.mjs')}
            cli=str(worker.ROOT/'deepseekHarness/apps/cli/lib/bin.js');prompt='- A negative-leading question'
            base_command=Mock(return_value=['node',cli,'--profile','headless',prompt]);spawn=Mock()
            def native_main():
                early=worker.native.command(worker.ROOT,'dsh',prompt,env)
                self.assertNotIn('--json',early)
                final=early[:-1]+['--json','--approval-policy','never',early[-1]]
                worker.native.subprocess.Popen(final)
            with patch.object(worker.native,'command',base_command),patch.object(worker.native.subprocess,'Popen',spawn), \
                 patch.object(worker.native,'main',native_main), \
                 patch.object(sys,'argv',['worker','--strategies','discard','--config',str(path),'--timeout','3600']):
                worker.main()
            spawn.assert_called_once();final=spawn.call_args.args[0]
            self.assertEqual(final[-3:],['never','--',prompt]);self.assertEqual(final.count('--'),1)
            actual=json.loads(overlay.read_text());expected=copy.deepcopy(saved)
            expected[0]['insert'][0]['name']=str(worker.ROOT/'scripts/dsh_wire_expectations_v9.mjs')
            self.assertEqual(actual,expected)
            self.assertIn('dsh_inline_wire_v5.mjs',env['NODE_OPTIONS'])
            self.assertEqual(env['ACL_INLINE_DSH_TIMEOUT_SECONDS'],'3600')
            self.assertEqual(env['ACL_INLINE_DSH_RETAIN_IMAGES'],'10')
            record=json.loads((workspace/'metrics/readonly-options-repair-v9.json').read_text())
            self.assertFalse(record['upstream_modified']);self.assertFalse(record['native_messages_mutated'])
