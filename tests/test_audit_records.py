import importlib.util
from pathlib import Path
import unittest
import tempfile
import json

SPEC = importlib.util.spec_from_file_location('audit_records', Path(__file__).parents[1] / 'scripts/audit_records.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
    def test_summary_timing_joins_exact_session_not_question(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'summary.jsonl').write_text(json.dumps({
                'session_id': 'attempt-one', 'question_id': 'q1', 'duration_seconds': 12.5}) + '\n')
            matched = audit.enrich({'group': directory, 'session_id': 'attempt-one'})
            other = audit.enrich({'group': directory, 'session_id': 'attempt-two'})
            self.assertEqual(matched['session_span_seconds'], 12.5)
            self.assertNotIn('end_to_end_seconds', matched)
            self.assertNotIn('end_to_end_seconds', other)

    def test_canonical_cache_buckets_are_disjoint(self):
        row = audit.extract(Path('/missing/conv/iter1/q1.json'), {
            'token_usage': {'input_tokens': 100, 'cache_read_tokens': 40,
                            'cache_write_tokens': 10, 'output_tokens': 20}})
        self.assertEqual(row['total_input'], 150)
        self.assertEqual(row['total_tokens'], 170)
        self.assertAlmostEqual(row['cache_hit_rate'], 40 / 150)

    def test_absent_instrumentation_does_not_become_zero(self):
        row = audit.extract(Path('/missing/conv/iter1/q1.json'), {'duration_seconds': 19})
        self.assertIsNone(row['cached_input'])
        self.assertIsNone(row['total_tokens'])
        self.assertIsNone(row['api_seconds'])
        self.assertIsNone(row['render_seconds'])
        self.assertIsNone(row['end_to_end_seconds'])
        self.assertEqual(row['session_span_seconds'], 19)

    def test_zero_input_has_no_hit_rate(self):
        row = audit.extract(Path('/missing/conv/iter1/q1.json'), {
            'token_usage': {'input_tokens': 0, 'cache_read_tokens': 0,
                            'cache_write_tokens': 0, 'output_tokens': 0}})
        self.assertEqual(row['total_tokens'], 0)
        self.assertIsNone(row['cache_hit_rate'])
