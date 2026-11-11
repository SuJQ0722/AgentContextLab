import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from dsh_inline_bc_worker_v5 import adapt_patches, configure_proxy
from dsh_image_preservation import preservation_patches
from lab import ROOT, runtime_path

class BufferedWatchdogTests(unittest.TestCase):
    def fixture(self):
        return preservation_patches({'TOKENHUB_BASE_URL':'http://localhost/v1','ACL_MODEL':'approved',
            'ACL_INPUT_MODALITIES':'["text","image"]','ACL_CONTEXT_WINDOW':'131072',
            'ACL_MAX_OUTPUT_TOKENS':'8192'})

    def test_only_watchdog_changes_not_model_or_output_or_image_budgets(self):
        original=self.fixture(); before=copy.deepcopy(original)
        result=adapt_patches(original, timeout_seconds=1800)
        provider=result[1]['config']['providers']['tokenhub']
        self.assertEqual(provider.pop('streamIdleTimeoutMs'), 1800000)
        self.assertEqual(result, before)
        self.assertEqual(original, before)

    def test_pinned_provider_resolves_watchdog_without_budget_change(self):
        providers=adapt_patches(self.fixture(),timeout_seconds=1800)[1]['config']['providers']
        code="""
import assert from 'node:assert/strict';
import {resolveProfiles} from './deepseekHarness/packages/llm/llm-pi-ai/src/config.ts';
const providers=JSON.parse(process.argv[1]);
const profile=resolveProfiles(providers).get('tokenhub');
assert.equal(profile.streamIdleTimeoutMs,1800000);
assert.equal(profile.configuredMaxTokens.get('approved'),8192);
"""
        run=subprocess.run(['node','--input-type=module','-e',code,json.dumps(providers)],
            cwd=ROOT,env={**os.environ,'PATH':runtime_path(ROOT)},capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)

    def test_actual_proxy_resolver_rejects_gateway_bypass(self):
        env={'PATH':runtime_path(ROOT),'TOKENHUB_BASE_URL':'https://gateway.example/v1',
             'NO_PROXY':'localhost,127.0.0.1','ALL_PROXY':'socks5://unused:9'}
        configure_proxy(env,'http://10.120.0.246:7890')
        self.assertNotIn('ALL_PROXY',env)
        self.assertEqual(env['HTTPS_PROXY'],env['https_proxy'])
        env['NO_PROXY']='*'
        with self.assertRaises(ValueError):configure_proxy(env,'http://10.120.0.246:7890')

    def test_task_deadline_not_extended(self):
        result=adapt_patches(self.fixture(), timeout_seconds=600)
        self.assertEqual(result[1]['config']['providers']['tokenhub']['streamIdleTimeoutMs'],600000)
        for timeout in (0,1801,3600,True,1800.0):
            with self.assertRaises(ValueError):adapt_patches(self.fixture(),timeout_seconds=timeout)

    def test_reject_ambiguous_or_preexisting_patch(self):
        fixture=self.fixture()
        with self.assertRaises(ValueError):adapt_patches([],timeout_seconds=1800)
        with self.assertRaises(ValueError):adapt_patches(fixture+fixture,timeout_seconds=1800)
        fixture[1]['config']['providers']['tokenhub']['streamIdleTimeoutMs']=300000
        with self.assertRaises(ValueError):adapt_patches(fixture,timeout_seconds=1800)

if __name__=='__main__':unittest.main()
