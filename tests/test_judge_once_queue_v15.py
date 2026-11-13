import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import judge_once_queue_v15 as queue


class QueueTests(unittest.TestCase):
    def test_completed_queue_drains_without_full_scan_per_grade(self):
        calls = []; scans = []
        candidates = [{'directory': str(i)} for i in range(20)]
        def scan(cost):
            scans.append(cost)
            return candidates + candidates, {'all_terminal': True}
        result = queue.run_queue(scan, lambda c: calls.append(c['directory']),
            lambda *a: self.fail('Unexpected error'), lambda x: None, allowed=lambda c: True,
            scan_interval=100, poll=.001)
        self.assertEqual(len(calls), 20)
        self.assertEqual(len(set(calls)), 20)
        self.assertEqual(result['inventory_scans'], 1)

    def test_slow_inventory_does_not_block_available_queue(self):
        entered = threading.Event(); release = threading.Event(); fourth = threading.Event()
        scans = [0]; graded = []
        candidates = [{'directory': str(i)} for i in range(12)]
        def scan(cost):
            scans[0] += 1
            if scans[0] == 2:
                entered.set()
                self.assertTrue(release.wait(2))
            return candidates, {'all_terminal': scans[0] >= 2}
        def grade(c):
            time.sleep(.015); graded.append(c['directory'])
            if len(graded) >= 8: fourth.set()
        def observer():
            self.assertTrue(entered.wait(2))
            self.assertTrue(fourth.wait(2))
            release.set()
        observer_thread = threading.Thread(target=observer)
        observer_thread.start()
        queue.run_queue(scan, grade, lambda *a: self.fail('Unexpected error'), lambda x: None,
            allowed=lambda c: True, scan_interval=.001, poll=.001)
        observer_thread.join(2)
        self.assertEqual(len(graded), len(set(graded)))
        self.assertEqual(len(graded), 12)

    def test_unknown_and_failed_claims_are_not_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = []
            for i, name in enumerate(['request-started.json', 'grade.json', 'local-error.json', None]):
                p = Path(tmp) / str(i); p.mkdir()
                if name: (p / name).write_text('{}')
                rows.append({'directory': p})
            called = []
            queue.run_queue(lambda cost: (rows, {'all_terminal': True}), lambda c: called.append(c['directory']),
                lambda *a: self.fail('Unexpected error'), lambda x: None, poll=.001)
            self.assertEqual(called, [rows[-1]['directory']])

    def test_exception_consumes_attempt_and_stop_drains_without_dispatch(self):
        failed = []; calls = []; stopped = threading.Event()
        rows = [{'directory': str(i)} for i in range(20)]
        def grade(c):
            calls.append(c['directory']); stopped.set(); raise ValueError('synthetic')
        result = queue.run_queue(lambda cost: (rows, {'all_terminal': False}), grade,
            lambda c, e: failed.append(c['directory']), lambda x: None, concurrency=1,
            allowed=lambda c: True, stop=stopped.is_set, scan_interval=.001, poll=.001)
        self.assertEqual(len(calls), 1)
        self.assertEqual(failed, calls)
        self.assertTrue(result['stopped'])


if __name__ == '__main__': unittest.main()
