import sys
import threading
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import judge_once_queue_io_v16 as io_queue


class AsyncStatusTests(unittest.TestCase):
    def test_blocked_status_write_does_not_block_multiple_grading_batches(self):
        entered = threading.Event(); release = threading.Event(); written = []; calls = []
        def write(row):
            if not written:
                entered.set(); self.assertTrue(release.wait(3))
            written.append(row)
        writer = io_queue.LatestStatusWriter(write, interval=0)
        writer.publish({'at': 'initial'})
        self.assertTrue(entered.wait(1))
        candidates = [{'directory': str(i)} for i in range(12)]
        result = io_queue.run_queue(lambda cost: (candidates, {'all_terminal': True}),
            lambda c: calls.append(c['directory']), lambda *a: self.fail('Unexpected failure'),
            writer.publish, allowed=lambda c: True, scan_interval=100, poll=.001)
        self.assertEqual(result['returned'], 12)
        self.assertEqual(len(calls), 12)
        writer.publish({'at': 'final'})
        release.set(); writer.close()
        self.assertEqual(written[-1], {'at': 'final'})
        self.assertEqual(len(written), 2)

    def test_late_claim_is_checked_in_worker_without_rejudging(self):
        calls = []
        result = io_queue.run_queue(lambda cost: ([{'directory': 'claimed'}], {'all_terminal': True}),
            lambda c: calls.append(c), lambda *a: self.fail('Unexpected failure'),
            lambda r: None, allowed=lambda c: False, poll=.001)
        self.assertEqual(calls, [])
        self.assertEqual(result['returned'], 1)

    def test_close_surfaces_failed_final_status_write(self):
        def write(row): raise OSError('synthetic disk failure')
        writer = io_queue.LatestStatusWriter(write)
        writer.publish({'finished': True})
        with self.assertRaisesRegex(RuntimeError, 'OSError'):
            writer.close()


if __name__ == '__main__': unittest.main()
