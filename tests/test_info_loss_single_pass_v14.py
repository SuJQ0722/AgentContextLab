import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import info_loss_single_pass_v14 as v


class SinglePassTests(unittest.TestCase):
    def test_spans_cover_every_unicode_character(self):
        text = ('中文🙂 exact value 42.\n' * 80) + 'end'
        parts = v.spans(text)
        self.assertEqual(''.join(p['text'] for p in parts), text)
        self.assertTrue(all(p['text'] == text[p['start']:p['end']] for p in parts))

    def test_semantics_requires_real_evidence_id(self):
        facts = [{'id': 'f1'}, {'id': 'f2'}]
        result = {'facts': {'f1': {'supported': True, 'evidence_ids': ['s0001']},
                            'f2': {'supported': False, 'evidence_ids': []}}}
        response = {'status': 'completed', 'finish_reason': 'stop', 'content': json.dumps(result)}
        self.assertIsNotNone(v.judge_parse(response, facts, 'The scoped value is 42.'))
        result['facts']['f1']['evidence_ids'] = ['invented']
        response['content'] = json.dumps(result)
        self.assertIsNone(v.judge_parse(response, facts, 'The scoped value is 42.'))

    def test_unknown_start_never_sends_again(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); p = root / 'calls/q/canvas_1/qa'; p.mkdir(parents=True)
            (p / 'started.json').write_text('{}')
            with patch.object(v.httpx, 'Client', side_effect=AssertionError('No retry')):
                result = v.call_once(root, {'case': 'q', 'method': 'canvas_1'}, 'qa', 'prompt', [], 'fixture')
            self.assertEqual(result['status'], 'unknown_prior_start')

    def test_length_is_reused_and_never_credit_as_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'old.json'
            source.write_text(json.dumps({'status': 'completed', 'finish_reason': 'length', 'content': 'value 42'}))
            qa = root / 'qa.json'; qa.write_text(json.dumps({'status': 'completed', 'finish_reason': 'stop', 'content': '{"f1":"42"}'}))
            c = {'id': 'q/canvas_1', 'case': 'q', 'method': 'canvas_1', 'split': 'holdout',
                 'facts': [{'id': 'f1', 'answer': '42'}], 'reuse': {'qa': v.binding(qa), 'reconstruction': v.binding(source)},
                 'old_judge': None, 'representation': {}}
            with patch.object(v, 'call_once', return_value={'status': 'provider_error', 'content': ''}) as call:
                row = v.execute_condition(root, c, 'fixture')
            self.assertEqual(call.call_count, 1)
            self.assertEqual(call.call_args.args[2], 'judge')
            self.assertFalse(row['reconstruction_complete'])
            self.assertIsNone(row['supported_facts'])


if __name__ == '__main__': unittest.main()
