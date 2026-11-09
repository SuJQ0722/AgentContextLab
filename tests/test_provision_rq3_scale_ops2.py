import copy
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from provision_rq3_scale_ops2 import request_args, SCALES


def template():
    return {'name': 'prior-reviewed', 'argv': ['sco', 'acp', 'jobs', 'create',
        '--workspace-name', 'rl', '--worker-nodes', '1', '--worker-spec', 'N4lS.Iu.I80.8c32g',
        '--job-name', 'prior-reviewed', '--name', 'prior-reviewed',
        '--container-image-url', 'registry.cn-tj-01.sensecore.cn/ccr-zuhu2026/sjq-dev-cpu:sjq-dev-20261108063401',
        '--storage-mount', 'afs-agents-volume:/mnt/afs_agents', '--command', 'old entry']}


class ProvisionRQ3Tests(unittest.TestCase):
    def test_seven_independent_allocations_keep_reviewed_resources(self):
        source = template()
        before = copy.deepcopy(source)
        names = set()
        for scale in SCALES:
            name, argv = request_args(source, scale)
            names.add(name)
            for flag in ('--workspace-name', '--worker-nodes', '--worker-spec', '--storage-mount', '--container-image-url'):
                self.assertEqual(argv[argv.index(flag)+1], source['argv'][source['argv'].index(flag)+1])
            command = shlex.split(argv[argv.index('--command')+1])
            self.assertEqual(command[command.index('--scale')+1], str(scale))
            self.assertIn('--live', command)
            self.assertNotIn('--harness', command)
        self.assertEqual(len(names), 7)
        self.assertEqual(source, before)

    def test_unplanned_scale_or_resource_change_rejected(self):
        with self.assertRaises(ValueError):
            request_args(template(), .3)
        for flag, value in [('--worker-spec', 'larger'), ('--storage-mount', 'other:/data'),
                            ('--container-image-url', 'unreviewed')]:
            source = template()
            source['argv'][source['argv'].index(flag)+1] = value
            with self.assertRaises(ValueError):
                request_args(source, .5)

    def test_cloud_auto_retry_and_env_inheritance_rejected(self):
        for extra in (['--enable-fault-tolerance'], ['--retry-times', '3'], ['--env', 'EXAMPLE:value']):
            source = template()
            source['argv'].extend(extra)
            with self.assertRaises(ValueError):
                request_args(source, 1.)


if __name__ == '__main__':
    unittest.main()
