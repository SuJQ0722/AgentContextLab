import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_bounded_vera_retry_v1 as retry


class RetrySelectionTests(unittest.TestCase):
    def setup_files(self, directory, status='completed', score=1):
        root = Path(directory); parent = root / 'old'; grading = root / 'grades'
        job = {'job_id': 'hermes/visual/q_r01', 'harness': 'hermes', 'strategy': 'visual'}
        result = parent / 'jobs' / job['job_id'] / 'attempts/attempt_001/result.json'
        retry.immutable_json(parent / 'plan.json', {'old': True})
        retry.immutable_json(result, {'job_id': job['job_id'], 'status': status,
            'slot_released': True, 'unconfirmed_child_termination': []})
        grade = grading / 'jobs' / job['job_id'] / 'grade.json'
        if status == 'completed':
            retry.immutable_json(grade, {'status': 'scored', 'score': score,
                'result_sha256': retry.sha(result), 'plan_sha256': retry.sha(parent / 'plan.json')})
        return job, parent, grading, result, grade

    def test_correct_is_retained_and_archive_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            job, parent, grading, result, grade = self.setup_files(d)
            old = result.read_bytes(), grade.read_bytes()
            row = retry.classify(job, parent, grading)
            self.assertEqual(row['score'], 1)
            root = Path(d) / 'new'; retry.immutable_json(root / 'experiment.json', {})
            self.assertEqual(retry.make_jobs([job], [row], root), [])
            self.assertEqual((result.read_bytes(), grade.read_bytes()), old)

    def test_unknown_grade_or_unclean_failure_never_selected_as_wrong(self):
        with tempfile.TemporaryDirectory() as d:
            job, parent, grading, result, grade = self.setup_files(d)
            grade.unlink()
            with self.assertRaises(ValueError): retry.classify(job, parent, grading)
            result.write_text(json.dumps({'job_id': job['job_id'], 'status': 'timeout',
                                         'slot_released': False, 'unconfirmed_child_termination': [{'pid': 1}]}))
            with self.assertRaises(ValueError): retry.classify(job, parent, grading)

    def test_confirmed_failure_is_one_new_selected_attempt(self):
        with tempfile.TemporaryDirectory() as d:
            job, parent, grading, result, grade = self.setup_files(d, status='timeout')
            record = retry.classify(job, parent, grading)
            root = Path(d) / 'new'; retry.immutable_json(root / 'experiment.json', {})
            jobs = retry.make_jobs([job], [record], root)
            self.assertEqual(len(jobs), 1); self.assertEqual(jobs[0]['shard'], 0)
            self.assertNotIn('score', jobs[0]); self.assertNotIn('result_path', jobs[0])

    def test_shards_are_disjoint_and_no_answer_fields_reach_workers(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); retry.immutable_json(root / 'experiment.json', {})
            sources = [{'job_id': 'hermes/visual/q' + str(i)} for i in range(20)]
            records = [{'job_id': j['job_id'], 'score': int(i % 4 == 0)} for i, j in enumerate(sources)]
            jobs = retry.make_jobs(sources, records, root)
            self.assertEqual(len(jobs), 15)
            sets = [{j['job_id'] for j in jobs if j['shard'] == s} for s in range(3)]
            self.assertEqual([len(s) for s in sets], [5, 5, 5]); self.assertFalse(sets[0] & sets[1])
            self.assertTrue(all('score' not in j and 'answer' not in j for j in jobs))


if __name__ == '__main__': unittest.main()
