import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import monitor_visual_inline_canary_v6 as monitor


class MonitorTests(unittest.TestCase):
    def completed(self): return {'status': 'completed', 'slot_released': True, 'unconfirmed_child_termination': []}

    def test_waits_for_live_judge_then_records_unresolved_request(self):
        r = self.completed()
        self.assertFalse(monitor.grade_state(r, {}, {}, True, True)['done'])
        final = monitor.grade_state(r, {}, {}, True, False)
        self.assertTrue(final['done']); self.assertIsNone(final['score'])
        self.assertEqual(final['error_type'], 'UnresolvedJudgeRequest')

    def test_cleanup_and_score_are_required(self):
        r = self.completed(); r['slot_released'] = False
        self.assertFalse(monitor.grade_state(r, {'status': 'scored', 'score': 1}, {}, False, False)['done'])
        self.assertEqual(monitor.grade_state(self.completed(), {'status': 'scored', 'score': 0}, {}, False, False)['score'], 0)
        error = monitor.grade_state(self.completed(), {}, {'error_type': 'Timeout'}, True, False)
        self.assertTrue(error['done']); self.assertIsNone(error['score'])

    def test_reused_pid_never_signaled(self):
        with patch.object(monitor, 'process', return_value={'alive': True, 'start_identity': 'different'}), patch.object(monitor.os, 'kill') as kill:
            self.assertEqual(monitor.stop_observer({'start_identity': monitor.OBSERVER_START})['action'], 'not_signaled_identity_mismatch')
            kill.assert_not_called()


if __name__ == '__main__': unittest.main()
