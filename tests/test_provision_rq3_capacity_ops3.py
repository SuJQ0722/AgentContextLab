from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from provision_rq3_capacity_ops3 import request_args, DEFAULT_ROOT, NEW_ROOT
from test_provision_rq3_scale_ops2 import template


class RQ3CapacityTests(unittest.TestCase):
    def source(self):
        value = template()
        value['argv'].extend(['--aec2-name', 'agents'])
        return value

    def test_pending_scales_keep_original_root_and_worker_protocol(self):
        for scale in (.8, 1.):
            name, root, entry, argv = request_args(self.source(), scale)
            self.assertEqual(root, DEFAULT_ROOT)
            self.assertEqual(entry, 'bootstrap_rq3_scale_ops2.py')
            self.assertEqual(argv[argv.index('--aec2-name')+1], 'agentic-rl')
            self.assertEqual(argv[argv.index('--worker-spec')+1], 'N4lS.Iu.I80.8c32g')
            self.assertTrue(name.endswith('-ops3'))

    def test_only_new_scale_uses_new_restricted_root(self):
        name, root, entry, argv = request_args(self.source(), .75)
        self.assertEqual(root, NEW_ROOT)
        self.assertEqual(name, 'acl-rq3-s0750-ops3')
        self.assertEqual(entry, 'bootstrap_rq3_scale0750_ops3.py')
        command = shlex.split(argv[argv.index('--command')+1])
        self.assertEqual(command[command.index('--root')+1], str(NEW_ROOT))
        self.assertEqual(command[command.index('--scale')+1], '0.75')

    def test_excluded_or_already_running_scales_cannot_be_reallocated(self):
        for scale in (0., .125, .25, .5, .7):
            with self.assertRaises(ValueError):
                request_args(self.source(), scale)


if __name__ == '__main__':
    unittest.main()
