import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import judge_inline_model_alias_v9 as judge


class ModelAliasTests(unittest.TestCase):
    def grade(self, response):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            attempt = directory / 'http-attempts/attempt_001'
            attempt.mkdir(parents=True)
            (attempt / 'started.json').write_text('{}')
            candidate = {'directory': directory, 'binding': {
                'result_path': '/fixture', 'result_sha256': 'digest',
                'gold_sources_sha256': {}}}
            with patch.object(judge.v8.parent, 'sha', return_value='digest'), \
                 patch.object(judge.v8.parent.base.bc, 'grade', return_value=copy.deepcopy(response)):
                result = judge.grade_bound(candidate, {}, {})
            self.assertEqual(json.loads((directory / 'grade.json').read_text()), result)
            return result

    def test_exact_returned_alias_preserves_score_raw_model_and_usage(self):
        usage = {'prompt_tokens': 10, 'completion_tokens': 4,
                 'prompt_tokens_details': {'cached_tokens': 3}}
        result = self.grade({'status': 'scored', 'score': 1.0, 'api_calls': 1,
            'finish_reason': 'stop', 'returned_model': judge.CANONICAL,
            'raw_provider_usage': usage})
        self.assertEqual(result['status'], 'scored')
        self.assertEqual(result['score'], 1.0)
        self.assertEqual(result['returned_model'], judge.CANONICAL)
        self.assertEqual(result['raw_provider_usage'], usage)
        self.assertEqual(len(judge.v8.ROUTES), 4)
        self.assertNotIn(judge.CANONICAL, judge.v8.ROUTES)

    def test_unknown_model_or_truncated_response_still_rejected(self):
        for model, finish, status in [('unknown', 'stop', 'judge_model_identity_unverified'),
                                     (judge.CANONICAL, 'length', 'incomplete_judge_response')]:
            with self.subTest(model=model, finish=finish):
                result = self.grade({'status': 'scored', 'score': 1.0, 'api_calls': 1,
                    'finish_reason': finish, 'returned_model': model})
                self.assertEqual(result['status'], status)
                self.assertIsNone(result['score'])

    def test_preexisting_grade_is_never_overwritten_or_called_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            previous = {'status': 'judge_model_identity_unverified', 'score': None,
                        'returned_model': judge.CANONICAL}
            p = directory / 'grade.json'
            p.write_text(json.dumps(previous))
            before = p.read_bytes()
            with patch.object(judge.v8.parent.base.bc, 'grade') as call:
                self.assertEqual(judge.grade_bound({'directory': directory}, {}, {}), previous)
                call.assert_not_called()
            self.assertEqual(p.read_bytes(), before)

    def test_sidecar_preserves_original_protocol_and_four_request_routes(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            protocol = output / 'protocol.json'
            protocol.write_text('{"version":"original-frozen-protocol"}')
            before = protocol.read_bytes()
            with patch.object(judge, '_original_prepare', return_value=({}, {})):
                judge.prepare('/unused-source', output)
                judge.prepare('/unused-source', output)
            self.assertEqual(protocol.read_bytes(), before)
            sidecar = json.loads((output / 'model-alias-protocol.json').read_text())
            self.assertEqual(sidecar['request_routes'], list(judge.v8.ROUTES))
            self.assertEqual(len(sidecar['request_routes']), 4)
            self.assertIn(judge.CANONICAL, sidecar['accepted_returned_models'])


if __name__ == '__main__':
    unittest.main()
