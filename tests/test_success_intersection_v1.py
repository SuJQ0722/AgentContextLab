import importlib.util
from pathlib import Path
import unittest
import tempfile
import json

P=Path(__file__).resolve().parents[1]/'scripts/analyze_success_intersection_v1.py'
S=importlib.util.spec_from_file_location('success_intersection_v1',P)
M=importlib.util.module_from_spec(S);S.loader.exec_module(M)

class SuccessIntersectionTests(unittest.TestCase):
    def row(self, method, q='q1', repeat=1, score=1, status='completed'):
        return dict(method=method, question_id=q, question_hash='hash-'+q, repeat=repeat, score=score,prediction_status=status)
    def test_failure_excludes_whole_pair_not_only_failed_method(self):
        x=[self.row('a'),self.row('b'),self.row('a','q2'),self.row('b','q2',status='timeout',score=0)]
        y=M.analyze(x,('a','b'),audit=False)
        self.assertEqual(y['completed_and_scored']['slots'],1)
        self.assertEqual(y['completed_and_scored']['methods']['a']['denominator'],1)
    def test_missing_grade_is_not_zero_or_unpaired_denominator(self):
        x=[self.row('a'),self.row('b',score=None)]
        y=M.analyze(x,('a','b'),audit=False)
        self.assertEqual(y['all_completed_slots'],1)
        self.assertEqual(y['completed_but_missing_any_grade'],1)
        self.assertIsNone(y['completed_and_scored']['methods']['a']['accuracy'])
    def test_wrong_completed_retained(self):
        x=[self.row('a'),self.row('b',score=0)]
        y=M.analyze(x,('a','b'),audit=False)
        self.assertEqual(y['completed_and_scored']['methods']['b']['accuracy'],0)
    def test_repeats_must_match(self):
        y=M.analyze([self.row('a'),self.row('b',repeat=2)],('a','b'),audit=False)
        self.assertEqual(y['all_completed_slots'],0)
    def test_question_content_mismatch_fails(self):
        a=self.row('a');b=self.row('b');b['question_hash']='different'
        with self.assertRaisesRegex(ValueError,'identity'): M.analyze([a,b],('a','b'),audit=False)
    def test_duplicate_attempt_does_not_double_count(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'): M.analyze([self.row('a'),self.row('a'),self.row('b')],('a','b'),audit=False)

    def test_logged_recovered_error_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'native/metrics').mkdir(parents=True)
            (p/'result.json').write_text(json.dumps({'status':'completed','exit_code':0}))
            for name,records in [('calls.jsonl',[{'call_id':'c','error_type':'ReadTimeout'}]),('call-starts.jsonl',[{'call_id':'c'}]),('web.jsonl',[])]:
                (p/'native/metrics'/name).write_text(''.join(json.dumps(x)+'\n' for x in records))
            self.assertEqual(M.audit_attempt(d)['state'],'observed_error')
    def test_missing_metrics_not_certified_clean(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'result.json').write_text(json.dumps({'status':'completed'}))
            self.assertEqual(M.audit_attempt(d)['state'],'coverage_unknown')
    def test_no_observed_errors_does_not_certify_wire(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'native/metrics').mkdir(parents=True)
            (p/'result.json').write_text(json.dumps({'status':'completed','exit_code':0}))
            for name,records in [('calls.jsonl',[{'call_id':'c','error_type':None}]),('call-starts.jsonl',[{'call_id':'c'}]),('web.jsonl',[])]:
                (p/'native/metrics'/name).write_text(''.join(json.dumps(x)+'\n' for x in records))
            r=M.audit_attempt(d)
            self.assertEqual(r['state'],'no_observed_error')
            self.assertFalse(r['strict_zero_wire_errors_certified'])

if __name__=='__main__':unittest.main()
