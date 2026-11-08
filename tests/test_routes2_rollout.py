import copy
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import roll_sco_bc_v3_routes2 as rollout
import bootstrap_bc_v3_node_routes2 as bootstrap
from types import SimpleNamespace


class RoutesRevisionRolloutTests(unittest.TestCase):
    def submission(self):
        name = 'acl-bc-v3-dsh-visual-ops4'
        return {'name': name, 'argv': ['sco', 'acp', 'jobs', 'create',
            '--workspace-name', 'rl', '--worker-nodes', '1',
            '--worker-spec', 'N4lS.Iu.I80.8c32g', '--job-name', name,
            '--name', name, '--container-image-url', 'reviewed-image',
            '--storage-mount', 'reviewed-afs', '--command',
            'exec python ' + str(ROOT / 'scripts/bootstrap_bc_v3_node.py') +
            ' --harness dsh --strategy visual --live']}

    def test_only_names_and_explicit_runtime_entry_change(self):
        old = self.submission()
        before = copy.deepcopy(old)
        argv = rollout.create_argv(old, 'acl-bc-v3-dsh-visual-ops5')
        changed = [i for i, (a, b) in enumerate(zip(old['argv'], argv)) if a != b]
        self.assertEqual(changed, [old['argv'].index(k) + 1 for k in
                                  ('--job-name', '--name', '--command')])
        self.assertEqual(old, before)
        self.assertIn('/bootstrap_bc_v3_node_routes2.py', argv[-1])

    def test_canary_routes1_parent_uses_routes2_without_resource_changes(self):
        old = self.submission()
        old['name'] = 'acl-bc-v3-hermes-visual-ops5'
        old['argv'] = [v.replace('acl-bc-v3-dsh-visual-ops4', old['name']).replace(
            '/bootstrap_bc_v3_node.py', '/bootstrap_bc_v3_node_routes1.py') for v in old['argv']]
        argv = rollout.create_argv(old, 'acl-bc-v3-hermes-visual-ops6')
        self.assertIn('/bootstrap_bc_v3_node_routes2.py', argv[-1])
        self.assertEqual(argv[argv.index('--worker-spec') + 1], 'N4lS.Iu.I80.8c32g')
        self.assertEqual(argv[argv.index('--storage-mount') + 1], 'reviewed-afs')

    def test_unexpected_command_fails_before_create(self):
        old = self.submission()
        old['argv'][-1] = 'unexpected'
        with self.assertRaises(ValueError):
            rollout.create_argv(old, 'new')

    def test_bootstrap_selects_routes_controller(self):
        args = SimpleNamespace(reader_python='python', root=Path('/campaign'),
                               harness='dsh', strategy='visual', controller_concurrency=16)
        cmd = bootstrap.commands(args)['controller']
        self.assertEqual(cmd[1], str(ROOT / 'scripts/run_bc_campaign_v3_routes2.py'))
        self.assertEqual(cmd[cmd.index('--concurrency') + 1], '16')
        self.assertEqual(cmd[cmd.index('--dispatch-role') + 1], 'cloud')


if __name__ == '__main__':
    unittest.main()
