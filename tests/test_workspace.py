import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('lab', ROOT / 'scripts/lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


class WorkspaceTests(unittest.TestCase):
    def test_env_layers_and_no_shell_execution(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=True):
            root = Path(td)
            (root / 'hermes-agent').mkdir(); (root / 'configs').mkdir()
            (root / 'configs/experiment.json').write_text((ROOT / 'configs/experiment.json').read_text())
            (root / '.env').write_text('TOKENHUB_API_KEY="test-only-secret"\nTOKENHUB_BASE_URL=https://example.test/v1\n')
            (root / 'hermes-agent/.env').write_text('OPENAI_API_KEY=stale-key\nHERMES_API_KEY=stale-key\nLOCAL_VALUE="a b"\n')
            env, cfg = lab.environment(root, 'hermes')
            self.assertEqual(env['OPENAI_API_KEY'], 'test-only-secret')
            self.assertEqual(env['HERMES_API_KEY'], 'test-only-secret')
            self.assertEqual(env['LOCAL_VALUE'], 'a b')
            self.assertEqual(env['HERMES_HOME'], str(root / '.state/hermes'))
            self.assertEqual(env['ACL_MODEL'], cfg['model'])
            self.assertNotIn('test-only-secret', json.dumps(lab.command(root, 'hermes', 'task', env)))
            os.environ['TOKENHUB_API_KEY'] = 'process-test-key'
            self.assertEqual(lab.environment(root, 'hermes')[0]['OPENAI_API_KEY'], 'process-test-key')
            (root / '.env').write_text('X="$(touch sentinel)"\n')
            self.assertEqual(lab.read_env(root / '.env')['X'], '$(touch sentinel)')
            self.assertFalse((root / 'sentinel').exists())

    def test_dsh_lock_matches_checkout(self):
        lock = json.loads((ROOT / 'harness-lock.json').read_text())['deepseek']
        actual = subprocess.check_output(['git', '-C', str(ROOT / lock['path']), 'rev-parse', 'HEAD'], text=True).strip()
        self.assertEqual(actual, lock['commit'])
        package = json.loads((ROOT / lock['path'] / 'package.json').read_text())
        self.assertEqual(lock['tag'], 'dsh-v' + package['version'])

    def test_envs_are_ignored_and_template_contains_no_key(self):
        for path in ['.env', 'hermes-agent/.env']:
            result = subprocess.run(['git', 'check-ignore', '-q', path], cwd=ROOT)
            self.assertEqual(result.returncode, 0)
        result = subprocess.run(['git', 'check-ignore', '-q', '.env'], cwd=ROOT / 'deepseekHarness')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(lab.read_env(ROOT / '.env.example')['TOKENHUB_API_KEY'], '')

    def test_hermes_package_inputs_survive_relocation(self):
        for name in ['README.md', 'LICENSE', 'pyproject.toml', 'AGENTS.md']:
            self.assertTrue((ROOT / 'hermes-agent' / name).is_file())

    def test_dry_run_launches_no_harness_and_hides_keys(self):
        for harness in ('hermes', 'dsh'):
            env = dict(os.environ, TOKENHUB_API_KEY='test-only-secret')
            result = subprocess.run([os.sys.executable, str(ROOT / 'scripts/lab.py'), 'run', harness,
                                     '--prompt', 'test task', '--dry-run'], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('test-only-secret', result.stdout + result.stderr)
            self.assertTrue(json.loads(result.stdout)['credential_configured'])


if __name__ == '__main__':
    unittest.main()
