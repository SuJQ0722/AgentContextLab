import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bc_retry1 as retry


class Routes:
    def claim_metadata(self, job):
        return {'actual_route': 'exact-fixed-route'}


class RetryClaims(unittest.TestCase):
    def test_claim_is_complete_when_published_and_duplicate_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(retry, 'validate_entry'):
            root = Path(tmp)
            job = {'job_id': 'dsh/none/q_001_r01', 'harness': 'dsh', 'strategy': 'none'}
            real_rename = retry.os.rename
            def checked(src, dst):
                self.assertFalse(Path(dst).exists())
                self.assertEqual(json.loads((Path(src) / 'owner.json').read_text())['job_id'], job['job_id'])
                real_rename(src, dst)
            with patch.object(retry.os, 'rename', checked):
                got = retry.publish_claim(root, job, {'controller_id': 'controller'}, Routes())
            self.assertIsNotNone(got)
            self.assertIsNone(retry.publish_claim(root, job, {'controller_id': 'other'}, Routes()))
            self.assertEqual(len(list((root / 'cells/dsh/none/slots').iterdir())), 1)

    def test_incomplete_publication_does_not_recycle_slot(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(retry, 'validate_entry'):
            root = Path(tmp)
            job = {'job_id': 'dsh/none/q_001_r01', 'harness': 'dsh', 'strategy': 'none'}
            with patch.object(retry.os, 'rename', side_effect=OSError('filesystem failed')):
                with self.assertRaises(OSError):
                    retry.publish_claim(root, job, {}, Routes())
            self.assertEqual(len(list((root / 'cells/dsh/none/slots').iterdir())), 1)
            self.assertFalse((root / 'jobs' / job['job_id'] / 'claim').exists())

    def test_completed_parent_cannot_be_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            result = out / 'result.json'
            result.write_text(json.dumps({'status': 'completed'}))
            ledger = {'entries': [{'job_id': 'job', 'parent_attempt': str(out), 'parent_result_sha256': retry.sha(result)}]}
            with patch.object(retry, 'load_ledger', return_value=ledger):
                with self.assertRaisesRegex(ValueError, 'Completed'):
                    retry.validate_entry(out, 'job')

    def test_new_parent_result_requires_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / 'result.json').write_text('{}')
            ledger = {'entries': [{'job_id': 'job', 'parent_attempt': str(out), 'parent_result_sha256': None}]}
            with patch.object(retry, 'load_ledger', return_value=ledger):
                with self.assertRaisesRegex(ValueError, 'Previously unknown'):
                    retry.validate_entry(out, 'job')

    def test_unselected_job_rejected(self):
        with patch.object(retry, 'load_ledger', return_value={'entries': []}):
            with self.assertRaisesRegex(ValueError, 'not in'):
                retry.validate_entry(Path('/unused'), 'job')


if __name__ == '__main__':
    unittest.main()
