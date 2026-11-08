import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from lab import environment

ENTRY = ROOT / 'scripts/run_dsh_eval_v3_routes2_io3.py'


def final_command(prompt):
    """Execute the actual production argv splice, never start the native worker."""
    tree = ast.parse(ENTRY.read_text())
    assignments = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                   and isinstance(n.targets[0], ast.Subscript)
                   and isinstance(n.targets[0].value, ast.Name)
                   and n.targets[0].value.id == 'cmd'
                   and isinstance(n.targets[0].slice, ast.Slice)]
    if len(assignments) != 1:
        raise AssertionError('Expected exactly one final command splice')
    context = {'cmd': ['node', str(ROOT / 'deepseekHarness/apps/cli/lib/bin.js'),
                      '--profile', 'headless', '--patch', '/fixture/policy.yml', prompt],
               'observer': Path('/fixture/observer.json'),
               'args': SimpleNamespace(permission_mode='workspace-write'), 'prompt': prompt}
    exec(compile(ast.Module(body=assignments, type_ignores=[]), str(ENTRY), 'exec'), context)
    return context['cmd']


class DshCliIo3Tests(unittest.TestCase):
    def test_real_launcher_and_headless_parsers_preserve_literal_task(self):
        prompts = ['ordinary task', '--literal-task\n第二行', '- Actor fixture\n- fact two',
                   'normal text with -- and --json inside', '--']
        commands = [final_command(p) for p in prompts]
        for command, prompt in zip(commands, prompts):
            self.assertEqual(command[-2:], ['--', prompt])
            self.assertEqual(command[command.index('--approval-policy') + 1], 'never')
            self.assertLess(command.index('--json'), len(command) - 2)
        # The actual launcher parses argv and passes its result to the actual
        # headless startup parser. Only booting the runtime is substituted;
        # no agent, model, tools, network, config overlays, or paid API starts.
        script = r'''
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import {registerHooks} from 'node:module';
const input=JSON.parse(readFileSync(0,'utf8'));
const boot=pathToFileURL(input.root+'/deepseekHarness/apps/cli/lib/profile-boot.js').href;
registerHooks({load(url,context,next){
 if(url===boot)return {format:'module',shortCircuit:true,source:'export async function runProfile(options){return globalThis.captureBoot(options)}'};
 return next(url,context);
}});
globalThis.fetch=()=>{throw new Error('Network forbidden in parser fixture')};
const {apply}=await import(pathToFileURL(input.root+'/deepseekHarness/packages/bundle/headless/lib/startup.js').href);
const {runCli}=await import(pathToFileURL(input.root+'/deepseekHarness/apps/cli/lib/bin.js').href);
const results=[];
globalThis.captureBoot=async(options)=>{
 const record={profile:options.profile,patches:options.patchFiles,exits:[]};
 apply({get(name){if(name==='cmdlineArgs')return {get:()=>options.args};if(name==='appExit')return code=>record.exits.push(code)},
        provide(name,value){record.service=name;record.value=value}});
 results.push(record);
};
for(const command of input.commands){process.argv=command;await runCli()}
process.stdout.write(JSON.stringify(results));
'''
        env, _ = environment(ROOT, 'dsh')
        with tempfile.TemporaryDirectory() as directory:
            env['DSH_HOME'] = directory
            result = subprocess.run(['node', '--input-type=module', '-e', script],
                                    input=json.dumps({'root': str(ROOT), 'commands': commands}),
                                    capture_output=True, text=True, cwd=directory, env=env, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        records = json.loads(result.stdout)
        self.assertEqual(len(records), len(prompts))
        for record, prompt in zip(records, prompts):
            self.assertEqual(record['value']['task'].encode(), prompt.encode())
            self.assertEqual(record['profile'], 'headless')
            self.assertEqual(record['patches'], ['/fixture/policy.yml', '/fixture/observer.json'])
            self.assertTrue(record['value']['json'])
            self.assertEqual(record['value']['permissionMode'], 'workspace-write')
            self.assertEqual(record['value']['approvalPolicy'], 'never')
            self.assertEqual(record['exits'], [])

    def test_operational_source_must_match_sidecar_and_keeps_parent_frozen(self):
        module_spec = importlib.util.spec_from_file_location('io3_entry_test', ENTRY)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        parent = ROOT / 'scripts/run_dsh_eval_v3_routes1.py'
        parent_hash = hashlib.sha256(parent.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'operation.json'
            payload = {'version': 'bc-v3-claim-publication-io3', 'implementation_sha256': {
                str(ENTRY.relative_to(ROOT)): hashlib.sha256(ENTRY.read_bytes()).hexdigest()}}
            path.write_text(json.dumps(payload))
            with patch.dict(os.environ, {'ACL_OPERATIONAL_IO3_FILE': str(path)}):
                result = module.operational_record()
                self.assertEqual(result['native_entry_sha256'], payload['implementation_sha256'][str(ENTRY.relative_to(ROOT))])
                payload['implementation_sha256'][str(ENTRY.relative_to(ROOT))] = '0' * 64
                path.write_text(json.dumps(payload))
                with self.assertRaisesRegex(ValueError, 'source differs'):
                    module.operational_record()
        self.assertEqual(hashlib.sha256(parent.read_bytes()).hexdigest(), parent_hash)


if __name__ == '__main__':
    unittest.main()
