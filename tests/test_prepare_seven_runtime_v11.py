"""Continuation must preserve predictions and conservative model-attempt accounting."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_seven_runtime_v11 as prepare


class ContinuationTests(unittest.TestCase):
    def test_local_rejection_then_model_request_consumes_attempt(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            native = root / 'native'; native.mkdir()
            ledger = native / 'inline-images-wire-v1.jsonl'
            attempt = {'native_artifact_root': str(native), 'result_path': str(root / 'result.json')}
            ledger.write_text(json.dumps({'decision': 'reject', 'network_send_authorized': False}) + '\n')
            self.assertFalse(prepare.attempt_has_model_or_unknown(attempt)[0])
            with ledger.open('a') as out:
                out.write(json.dumps({'decision': 'allow'}) + '\n')
            self.assertTrue(prepare.attempt_has_model_or_unknown(attempt)[0])

    def test_missing_request_evidence_is_not_assumed_free(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            attempt = {'native_artifact_root': str(root / 'native'), 'result_path': str(root / 'result.json')}
            self.assertTrue(prepare.attempt_has_model_or_unknown(attempt)[0])
            (root / 'worker.log').write_text('ValueError: Explicit one-hour retry version required')
            self.assertFalse(prepare.attempt_has_model_or_unknown(attempt)[0])

    def test_completed_wrong_answer_is_preserved_without_reading_score(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); old = root / 'old/cells/example'; old.mkdir(parents=True)
            (old / 'cohort.jsonl').write_text('')
            (old / 'experiment.json').write_text('{}')
            (old / 'campaign-manifest.json').write_text(json.dumps({'harness': 'hermes'}))
            plan = {'definition': {'one_hour_retry_version': 'fixture'}, 'jobs': [{'job_id': 'wrong'}]}
            (old / 'plan.json').write_text(json.dumps(plan))
            result = old / 'jobs/wrong/attempts/attempt_001/result.json'; result.parent.mkdir(parents=True)
            result.write_text(json.dumps({'status': 'completed', 'score': 0}))
            with patch.object(prepare, 'SOURCE', root / 'old'), patch.object(prepare, 'DEST', root / 'new'), patch.object(prepare.subprocess, 'check_output', return_value=b''):
                manifest = prepare.prepare('example')
            self.assertEqual(manifest['planned_runs'], 0)
            self.assertEqual(manifest['retained_completed'], 1)
            selected = json.loads((root / 'new/cells/example/selection.json').read_text())
            self.assertFalse(selected['selection_uses_answers'])
            self.assertTrue(selected['records'][0]['retained_completed'])

    def test_unreleased_native_blocks_continuation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); attempt = root / 'jobs/a/attempts/attempt_001'; attempt.mkdir(parents=True)
            (attempt / 'controller-dispatched.json').write_text('{}')
            self.assertFalse(prepare.drained(root))
            (attempt / 'result.json').write_text(json.dumps({'slot_released': True, 'unconfirmed_child_termination': []}))
            self.assertTrue(prepare.drained(root))


if __name__ == '__main__':
    unittest.main()
