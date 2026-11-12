import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import dsh_inline_bc_worker_v6 as worker
from dsh_image_preservation import preservation_patches
from lab import runtime_path
from inline_route_contract_v2 import ROUTES


class TwoHourTests(unittest.TestCase):
    def fixture(self):
        return preservation_patches({'TOKENHUB_BASE_URL': 'http://localhost/v1', 'ACL_MODEL': ROUTES[0],
            'ACL_INPUT_MODALITIES': '["text","image"]', 'ACL_CONTEXT_WINDOW': '131072',
            'ACL_MAX_OUTPUT_TOKENS': '8192'})

    def node(self, code):
        env = {**os.environ, 'PATH': runtime_path(ROOT)}
        env.pop('ACL_INLINE_DSH_LEDGER', None)
        result = subprocess.run(['node', '--input-type=module', '-e', code], cwd=ROOT,
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sdk_budgets_and_single_retry_owner(self):
        source = self.fixture(); before = copy.deepcopy(source)
        changed = worker.adapt_patches(source, timeout_seconds=7200)
        provider = changed[1]['config']['providers']['tokenhub']
        self.assertEqual(provider.pop('timeoutMs'), 7200000)
        self.assertEqual(provider.pop('streamIdleTimeoutMs'), 7200000)
        self.assertEqual(provider.pop('retryPolicy'), {'mode':'normal','maxRetries':0})
        self.assertEqual(changed.pop(), {'id':'compaction-image-offload','disabled':True})
        self.assertEqual(changed, before)
        self.assertEqual(source, before)
        for value in (1800, 3600, 7201, 0, True, 7200.0):
            with self.assertRaises(ValueError): worker.validate_timeout(value)
        changed[1]['config']['providers']['tokenhub']['timeoutMs'] = 600000
        with self.assertRaises(ValueError): worker.adapt_patches(changed, timeout_seconds=7200)

    def test_real_provider_resolution(self):
        providers = worker.adapt_patches(self.fixture(), timeout_seconds=7200)[1]['config']['providers']
        self.node("""
import assert from 'node:assert/strict';
import {resolveProfiles} from './deepseekHarness/packages/llm/llm-pi-ai/src/config.ts';
const p=resolveProfiles(PROVIDERS).get('tokenhub');
assert.equal(p.retryPolicy.maxRetries,0);assert.equal(p.timeoutMs,7200000);assert.equal(p.streamIdleTimeoutMs,7200000);
assert.equal(p.configuredMaxTokens.get(MODEL),8192);
""".replace('PROVIDERS', json.dumps(providers)).replace('MODEL', json.dumps(ROUTES[0])))

    def test_wire_survives_1800_and_expires_at_7200_across_requests(self):
        self.node("""
import assert from 'node:assert/strict';
import {guardedFetch,ROUTES} from './scripts/dsh_hosted_wire_v4.mjs';
let time=0,calls=0;const rows=[];const endpoint='http://fixture/v1/chat/completions';
const f=guardedFetch({original:async()=>{calls++;return new Response('ok')},
transform:async body=>({wire:body,ledger:{}}),endpoint,emit:r=>rows.push(r),now:()=>time});
const init={method:'POST',body:JSON.stringify({model:ROUTES[0],messages:[]})};
time=1800001;assert.equal(await(await f(endpoint,init)).text(),'ok');
time=7199999;assert.equal(await(await f(endpoint,init)).text(),'ok');
time=7200000;await assert.rejects(()=>f(endpoint,init),/deadline/);
assert.equal(calls,2);assert(rows.some(r=>r.event==='trial_transport_deadline'));
""")

    def test_wrapper_chain_replaces_preload_and_protocol(self):
        cfg = {'model': ROUTES[0], 'approved_model_routes': ROUTES,
            'model_route_policy': 'four-route-rotation-v1', 'image_transport': 'inline-recent-ten-chunked-v1',
            'transport_delivery_version': 'inline-direct-v1', 'transport_runtime_version': 'visual-transport-runtime-v4',
            'gateway_proxy': 'http://10.120.0.246:7890', 'bounded_max_images': 10,
            'bounded_request_protocol': 'bounded-multimodal-recent-ten-v1',
            'bounded_bc_protocol': 'bc-bounded-pages-v1', 'bounded_transport_encoding': 'bounded-canvas-lossless-webp-v1',
            'visual_renderer': {'history_scale': .75},
            'shared_policy': {'strategy_configs': {'visual': {'history_scale': .75, 'font_size': 16,
                'image_width': 1024, 'max_image_height': 2048, 'history_max_image_height': 2048,
                'keep_rounds': 1, 'recent_rounds': 5, 'text_only': False}}}}
        cfg.update(timeout_seconds=7200, dsh_buffered_watchdog_version=worker.VERSION)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); config = base / 'config.json'; config.write_text(json.dumps(cfg))
            output = base / 'jobs/bc_dsh/q_test/attempts/attempt_001/native'
            workspace = output / 'visual_native/q_test/workspace'; workspace.mkdir(parents=True)
            env = {'ACL_WORKSPACE': str(workspace), 'NODE_OPTIONS': '--import ' + str(ROOT / 'scripts/dsh_wire_image_guard.mjs')}
            overlay = [{'insert': [{'id': 'acl-hermes-shared-compaction',
                'name': str(ROOT / 'plugins/dsh-context/hermes-policy-v3.mjs'),
                'config': {'python': sys.executable, 'sharedPolicy': str(ROOT / 'scripts/shared_context_policy.py'),
                    'policyConfig': {'strategy_config': {'bounded_bc_protocol': 'bc-bounded-pages-v1'}}}}]}]
            (workspace.parent / 'research.patch.yml').write_text(json.dumps(overlay))
            def native_main(): worker.native.command(ROOT, 'dsh', '-prompt', env)
            with patch.object(sys, 'argv', ['worker', '--config', str(config), '--timeout', '7200',
                    '--output-root', str(output), '--dataset', 'bc100', '--strategies', 'visual_native']), \
                    patch.object(worker.native, 'main', native_main), patch.object(worker.native, 'command', return_value=[]):
                worker.main()
            self.assertIn('dsh_hosted_wire_v4.mjs', env['NODE_OPTIONS'])
            self.assertNotIn('dsh_hosted_wire_v3.mjs', env['NODE_OPTIONS'])
            self.assertEqual(env['ACL_INLINE_DSH_TIMEOUT_SECONDS'], '7200')
            record = json.loads((workspace.parent / 'inline-dsh-protocol.json').read_text())
            self.assertEqual(record['outer_trial_timeout_seconds'], 7200)
            self.assertEqual(record['transport_deadline_seconds'], 7200)
            self.assertEqual(record['approved_model_routes'], ROUTES)
            self.assertEqual(record['max_images'], 10)
            self.assertEqual(env['ACL_INLINE_DSH_RETAIN_IMAGES'], '10')
            self.assertEqual(record['canvas_page_budget'], {'history': 5, 'recent': 2})
            self.assertEqual(record['fetch_wall_timeout_seconds'], 300)


# Re-run the existing real SDK/dispatcher, route and inline-image behavioral
# contract against the new immutable wire implementation as well.
import test_dsh_hosted_transport_v3 as previous_transport_tests

class TwoHourTransportTests(previous_transport_tests.DSHInlineV3Tests):
    def node(self, code):
        return super().node(code.replace('dsh_hosted_wire_v3.mjs', 'dsh_hosted_wire_v4.mjs'))

if __name__ == '__main__': unittest.main()
