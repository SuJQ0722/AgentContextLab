import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import watch_controlled_bounded_pilot_v2 as watcher
from prepare_controlled_bounded_v1 import MODEL,ENCODING
from run_controlled_bounded_v1 import PROTOCOL

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.plan={'prefixes':[{'key':ds+'/q_001_r01','pilot':True,'eligible':True} for ds in ('bc','mmbc')],'jobs':[]}
        for p in self.plan['prefixes']:
            for method in ('visual','summary','window'):
                jid=p['key']+'/'+method;out=self.root/'jobs'/jid;out.mkdir(parents=True)
                (out/'spec.json').write_text(json.dumps({'bounded_transport_encoding':ENCODING}))
                self.plan['jobs'].append({'job_id':jid,'prefix_key':p['key'],'method':method,'eligible':True,'out':str(out),'spec_path':str(out/'spec.json')})
    def finish(self,key,method,status='completed',passed=True):
        out=self.root/'jobs'/key/method
        (out/'trial-status.json').write_text(json.dumps({'status':status,'worker_reaped':True}))
        c={'passed':passed,'method':method,'native_identity_verified':passed,'first_actual_prompt_tokens':10000,
            'native_hashes':['native'],'prefix_sha256':'prefix','actual_route':MODEL,
            'bounded_native_protocol':PROTOCOL,'bounded_transport_encoding':ENCODING}
        (out/'compression-control.json').write_text(json.dumps(c))
    def known_mixed(self):
        self.finish('bc/q_001_r01','visual','failed',False)
        for m in ('visual','summary','window'):self.finish('mmbc/q_001_r01',m)
    def test_failed_visual_with_two_unstarted_text_arms_allows_unrelated_groups(self):
        self.known_mixed();r=watcher.evaluate(self.root,self.plan)
        self.assertEqual(r['state'],'ready');self.assertFalse(r['all_pilot_groups_passed'])
        self.assertFalse(r['groups']['bc/q_001_r01']['passed']);self.assertTrue(r['groups']['mmbc/q_001_r01']['passed'])
        self.assertEqual(r['pilot_states']['bc/q_001_r01/summary'],'not_run_visual_gate_unavailable')
        self.assertEqual(len(r['bindings']),6)
    def test_failed_text_gate_does_not_globally_block_or_become_passed(self):
        for p in self.plan['prefixes']:
            for m in ('visual','summary','window'):self.finish(p['key'],m,'budget_infeasible' if m=='summary' else 'failed',m!='summary')
        r=watcher.evaluate(self.root,self.plan);self.assertEqual(r['state'],'ready');self.assertFalse(r['all_pilot_groups_passed'])
    def test_unknown_orphan_attempt_blocks(self):
        self.known_mixed();(self.root/'jobs/bc/q_001_r01/summary/dispatch.json').write_text('{}')
        self.assertEqual(watcher.evaluate(self.root,self.plan)['state'],'blocked')
    def test_cleanup_unknown_blocks(self):
        self.known_mixed();p=self.root/'jobs/mmbc/q_001_r01/visual/trial-status.json';p.write_text('{"status":"completed","worker_reaped":false}')
        self.assertEqual(watcher.evaluate(self.root,self.plan)['reason'],'worker_cleanup_unconfirmed')
    def test_active_waits_without_launching(self):
        self.known_mixed()
        with patch.object(watcher,'alive',return_value=True):self.assertEqual(watcher.evaluate(self.root,self.plan)['state'],'waiting')
    def test_unstarted_ready_pilot_is_not_terminal(self):
        self.assertEqual(watcher.evaluate(self.root,self.plan)['state'],'waiting')
    def test_unknown_terminal_status_blocks(self):
        self.known_mixed();p=self.root/'jobs/mmbc/q_001_r01/visual/trial-status.json';p.write_text('{"status":"interrupted_unknown","worker_reaped":true}')
        self.assertEqual(watcher.evaluate(self.root,self.plan)['reason'],'unknown_pilot_execution')

if __name__=='__main__':unittest.main()
