import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from prepare_visual_hosted_retry_v2 import drained


class DrainProof(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = {'jobs': [{'job_id': 'hermes/visual/q_001_r01'}]}

    def write(self, path, value):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value))

    def test_never_claimed_is_safe(self):
        self.assertEqual(drained(self.root, self.plan), {})

    def test_controller_must_have_matching_drained_exit(self):
        self.write('controllers/hermes/abc/maintenance.json', {'controller_id': 'abc'})
        with self.assertRaises(RuntimeError):
            drained(self.root, self.plan)
        self.write('controllers/hermes/abc/exit.json', {'controller_id': 'other', 'drained': True})
        with self.assertRaises(RuntimeError):
            drained(self.root, self.plan)
        self.write('controllers/hermes/abc/exit.json', {'controller_id': 'abc', 'drained': True})
        self.assertEqual(len(drained(self.root, self.plan)), 1)

    def test_claim_requires_result_and_confirmed_native_cleanup(self):
        base = 'jobs/hermes/visual/q_001_r01/'
        self.write(base + 'claim/owner.json', {})
        with self.assertRaises(RuntimeError):
            drained(self.root, self.plan)
        self.write(base + 'attempts/attempt_001/result.json',
                   {'status': 'failed', 'slot_released': True, 'unconfirmed_child_termination': [123]})
        with self.assertRaises(RuntimeError):
            drained(self.root, self.plan)
        self.write(base + 'attempts/attempt_001/result.json',
                   {'status': 'completed', 'slot_released': True, 'unconfirmed_child_termination': []})
        self.assertEqual(len(drained(self.root, self.plan)), 1)


if __name__ == '__main__':
    unittest.main()
