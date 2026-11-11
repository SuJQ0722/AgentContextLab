import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import watch_visual_judge_recovery_v7 as module


class WatchTests(unittest.TestCase):
    def test_scored_zero_and_unknown_never_resubmitted(self):
        for state in ({'status': 'scored', 'score': 0}, {'status': 'scored', 'score': 1},
                      {'status': 'unknown_judge_acceptance_requires_audit'}, {'status': 'requires_audit'}):
            self.assertFalse(module.runnable(state, 1000))
        self.assertTrue(module.runnable({}, 1000))

    def test_retry_cooldown_is_persistent(self):
        state = {'status': 'retry_deadline', 'next_eligible_unix': 2000}
        self.assertFalse(module.runnable(state, 1999))
        self.assertTrue(module.runnable(state, 2000))

    def test_unknown_acceptance_stops_four_route_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); old = root / 'old.json'; old.write_text('{"status":"http_error","http_status":429}')
            candidate = {'cell': 'bc', 'job_id': 'h/visual/q1', 'directory': root / 'new',
                'old_grade_path': str(old), 'old_grade_sha256': module.base.sha(old),
                'binding': {'gold_sources_sha256': {}}, 'question': 'q', 'answer': 'a', 'prediction': 'p'}
            calls = []
            def call(*args): calls.append(1); return {'status': 'judge_error', 'error_type': 'TimeoutError'}
            value = module.recovery.recover(candidate, {}, call=module.preserve_unknown(call))
            self.assertEqual(value['status'], 'unknown_judge_acceptance_requires_audit')
            self.assertEqual(len(calls), 1)

    def test_format_verdict_not_changed_by_guard(self):
        value = {'status': 'invalid_judge_response'}
        self.assertEqual(module.preserve_unknown(lambda: value)(), value)

    def test_restart_preserves_unknown_accepted_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); attempt = root / 'attempts/attempt_001'
            attempt.mkdir(parents=True); (attempt / 'grade.json').write_text('{"status":"judge_error"}')
            candidate = {'directory': root, 'cell': 'bc', 'job_id': 'job'}
            with patch.object(module.recovery, 'recover', side_effect=AssertionError('must not repeat paid request')):
                value = module.recover_checked(candidate, {})
            self.assertEqual(value['status'], 'unknown_judge_acceptance_requires_audit')
