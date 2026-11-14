"""Source-proof tests for conditional, provider-measured controlled cohorts."""
import copy
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_controlled_vera_cohort_v17 as m


class ControlledSourceProofTests(unittest.TestCase):
    def test_literal_cohort_includes_failed_and_wrong_answers(self):
        rows = [dict(benchmark='mmbc100', harness='hermes', method='visual', question_id=f'q{i//3}', repeat=i%3,
                     status='completed_scored', score=0) for i in range(300)]
        rows[0]['status'] = 'timeout_unresolved'
        rows[1]['status'] = 'system_or_unclassified_failed'
        selected = m.select_cohort({'observations': rows})
        self.assertEqual(len(selected), 299)
        self.assertEqual(sum(r['status']=='system_or_unclassified_failed' for r in selected), 1)
        self.assertTrue(all(r['score']==0 for r in selected))

    def test_duplicate_cohort_rejected(self):
        with self.assertRaises(ValueError):
            m.select_cohort({'observations': []})

    def test_controlled_alias_rejected_by_metadata(self):
        row = {'question_id':'q', 'repeat':1, 'question_sha256':m.digest(b'question')}
        job = dict(harness='hermes', strategy='visual', question_id='q', repeat=1,
                   job_id='hermes/visual/q_r01', question='question', benchmark='mmbc100')
        self.assertTrue(m.core_job_valid(job, row))
        for mutation in [{'experiment_kind':'controlled'}, {'controlled_spec_path':'spec'}, {'calibration_not_scored':True}]:
            self.assertFalse(m.core_job_valid(job | mutation, row))

    def test_wire_subsequence_reindexed_default_detail(self):
        archived = [dict(sha256=x, detail=None, message_index=2, part_index=i) for i,x in enumerate('abc')]
        retained = [dict(sha256=x, detail='auto', message_index=2, original_part_index=i) for i,x in enumerate('bc')]
        proof = m.bind_wire_images(archived, retained)
        self.assertEqual([r['archive_part_index'] for r in proof], [1,2])

    def test_wire_changed_order_bytes_or_detail_rejected(self):
        archived = [dict(sha256=x, detail='high', message_index=2, part_index=i) for i,x in enumerate('ab')]
        for retained in [[dict(sha256='b',detail='high'),dict(sha256='a',detail='high')],
                         [dict(sha256='x',detail='high')], [dict(sha256='a',detail='low')]]:
            with self.assertRaises(ValueError): m.bind_wire_images(archived, retained)

    def test_prefix_uses_response_bound_fresh_tool_round(self):
        previous = dict(call_id='prior', model='model', messages=[dict(role='user',content='question')])
        tail = [dict(role='assistant',tool_calls=[dict(id='new')]), dict(role='tool',tool_call_id='new',content='source')]
        post = dict(call_id='post',messages=[dict(role='user',content='rendered')] + tail)
        prefix, proof = m.reconstruct_prefix(previous, post, {'new'})
        self.assertEqual(prefix['messages'],previous['messages']+tail)
        self.assertEqual(proof['new_tool_call_ids'], ['new'])
        with self.assertRaises(ValueError): m.reconstruct_prefix(previous, post, {'different'})
        with self.assertRaises(ValueError): m.reconstruct_prefix(previous, post | {'messages':post['messages']+[dict(role='assistant',content='answer')]}, {'new'})

    def test_null_stream_tool_calls_and_binding(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'trace.gz'
            rows=[dict(type='request',call_id='one',messages=[]),dict(type='stream_chunk',call_id='one',chunk={'choices':[{'delta':{'tool_calls':None}}]}),
                  dict(type='stream_chunk',call_id='one',chunk={'choices':[{'delta':{'tool_calls':[{'id':'tool'}]}}]}),dict(type='request',call_id='two',messages=[])]
            with gzip.open(p,'wt') as f: f.write('\n'.join(json.dumps(r) for r in rows))
            previous,post,ids,ordinal=m.archived_pair(p,'two')
            self.assertEqual((previous['call_id'],post['call_id'],ids,ordinal),('one','two',{'tool'},2))

    def test_no_compression_reuse_requires_completion(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,'noncompleted'):
                m.no_compression_proof(Path(td), {'status':'system_or_unclassified_failed'})

    def test_frozen_artifact_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'frozen.json'
            self.assertEqual(m.save(p, {'value':1}),m.save(p, {'value':1}))
            with self.assertRaises(ValueError): m.save(p, {'value':2})

if __name__ == '__main__': unittest.main()
