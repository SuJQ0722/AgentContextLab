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
import dsh_inline_bc_worker_v4 as worker
import prepare_dsh_cli_separator_retry_v1 as preparation
import wait_dsh_cli_separator_retry_v1 as waiter
import run_bc_campaign_v3 as original
from lab import runtime_path


def job():
    return {'job_id': 'dsh/visual/q_043_r02', 'harness': 'dsh', 'strategy': 'visual',
            'question_id': 'q_043', 'repeat': 2, 'model': 'deepseek-v4.1-flash-1017/huoshan/huoshan',
            'question': '- Actor fixture'}


class SeparatorTests(unittest.TestCase):
    def test_actual_launcher_and_headless_parsers_preserve_dash_question(self):
        code = """
import assert from 'node:assert/strict';import {parseDshArgs}from './deepseekHarness/apps/cli/src/args.ts';
import {apply,HEADLESS_STARTUP_SERVICE}from './deepseekHarness/packages/bundle/headless/lib/startup.js';
const task='- Actor A fixture';const invocation=parseDshArgs(['--profile','headless','--patch','fixture.json','--json','--permission-mode','workspace-write','--approval-policy','never','--',task],'fixture');let value;
const ctx={get:key=>key==='cmdlineArgs'?{get:()=>invocation.args}:key==='appExit'?(code=>{throw Error('Parser exit '+code)}):undefined,provide:(key,v)=>{assert.equal(key,HEADLESS_STARTUP_SERVICE);value=v;}};
apply(ctx);assert.equal(value.task,task);assert.equal(value.json,true);
"""
        run = subprocess.run(['node', '--input-type=module', '-e', code], cwd=ROOT,
                             env={**os.environ, 'PATH': runtime_path(ROOT)}, capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_final_command_only_and_idempotent_separator(self):
        command = ['node', str(ROOT / 'deepseekHarness/apps/cli/lib/bin.js'), '--profile', 'headless', '--json', '--approval-policy', 'never', '- Actor fixture']
        result = worker.separate_prompt(command)
        self.assertEqual(result[-2:], ['--', '- Actor fixture'])
        self.assertNotEqual(command, result)
        self.assertEqual(worker.separate_prompt(result), result)
        unrelated = ['python', 'helper.py', '-x']
        self.assertIs(worker.separate_prompt(unrelated), unrelated)

    def test_cancel_wins_after_controller_slot_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);j = job();real_atomic = original.atomic;interleaved = []
            def atomic(path, value):
                real_atomic(path, value)
                if '/slots/' in str(path) and path.name == 'owner.json':
                    interleaved.append(preparation.defer_unclaimed(root, j, plan_sha256='fixture'))
            with patch.object(original, 'atomic', atomic):
                result = original.acquire_claim(root, j, {'controller_id': 'fixture'}, cap=1)
            self.assertIsNone(result)
            self.assertTrue(interleaved[0]['deferred'])
            self.assertEqual(list((root / 'cells/dsh/visual/slots').iterdir()), [])
            value = json.loads((root / 'jobs' / j['job_id'] / 'attempts/attempt_001/result.json').read_text())
            self.assertEqual(value['status'], 'not_started');self.assertEqual(value['api_calls'], 0)
            self.assertEqual(value['failure_category'], 'CLI_separator_deferred')

    def test_controller_wins_claim_cancellation_is_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);j = job();owned = original.acquire_claim(root, j, {'controller_id': 'fixture'}, cap=1)
            directory = root / 'jobs' / j['job_id'];before = (directory / 'claim/owner.json').read_bytes()
            result = preparation.defer_unclaimed(root, j, plan_sha256='fixture')
            self.assertFalse(result['deferred'])
            self.assertEqual((directory / 'claim/owner.json').read_bytes(), before)
            self.assertFalse((directory / 'attempts').exists())
            self.assertIsNotNone(owned)

    def test_drain_gate_requires_matching_exit_and_no_remaining_slots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);run = root / 'controllers/dsh/fixture';run.mkdir(parents=True)
            (root / 'leases/dsh').mkdir(parents=True)
            (root / 'leases/dsh/owner.json').write_text(json.dumps({'controller_id': 'fixture', 'run_directory': str(run)}))
            self.assertFalse(waiter.drained(root))
            (run / 'exit.json').write_text(json.dumps({'controller_id': 'fixture', 'drained': True}))
            self.assertTrue(waiter.drained(root))
            (root / 'cells/dsh/visual/slots/00').mkdir(parents=True)
            self.assertFalse(waiter.drained(root))


if __name__ == '__main__':
    unittest.main()
