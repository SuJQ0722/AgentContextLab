import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_mmbc100_campaign as m


class MMBCScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.root = self.path / 'campaign'
        self.grading = self.path / 'grading'
        self.source = self.path / 'source.jsonl'
        self.source.write_bytes(m.jsonl([{'id': f'mmbc_{i:03}', 'question': f'Question {i}',
            'image': [f'https://example.org/{i}.png'] if i % 3 else [],
            'answer': f'PRIVATE GOLD {i}', 'checklist': ['PRIVATE CHECKLIST'], 'canary': 'PRIVATE CANARY'}
            for i in range(400)]))
        self.kw = {'source': self.source, 'grading_root': self.grading,
                   'expected_source_sha': m.sha(self.source)}
        # Exercise this frozen legacy protocol independently of current defaults.
        legacy = m.read(m.ROOT_CONFIG)
        legacy['mmbc100_campaign'].update(max_rounds=60, timeout_seconds=1800)
        legacy_path = self.path / 'legacy-config.json'
        legacy_path.write_text(json.dumps(legacy))
        self.kw['root_config'] = legacy_path
        self.fake_assets = types.SimpleNamespace(validate_assets=lambda root, deep=False: {})

    def test_selection_order_independent_no_image_or_result_filter(self):
        rows = m.select_rows(self.source, m.sha(self.source))
        self.assertEqual(len(rows), 100)
        self.assertTrue(any(not r['image'] for r in rows))
        self.assertTrue(any(r['image'] for r in rows))
        original = [json.loads(x) for x in self.source.read_text().splitlines()]
        self.source.write_bytes(m.jsonl(list(reversed(original))))
        again = m.select_rows(self.source, m.sha(self.source))
        self.assertEqual([r['id'] for r in rows], [r['id'] for r in again])

    def test_public_inputs_are_gold_isolated_and_idempotent(self):
        manifest = m.prepare_inputs(self.root, **self.kw)
        self.assertEqual(manifest, m.prepare_inputs(self.root, **self.kw))
        raw = (self.root / 'cohort.jsonl').read_text()
        self.assertNotIn('PRIVATE', raw)
        rows = [json.loads(x) for x in raw.splitlines()]
        self.assertTrue(all(set(r) == {'question_id', 'question', 'image'} for r in rows))
        self.assertFalse((self.root / 'plan.json').exists())
        gold = self.grading / 'private/selected-source.jsonl'
        self.assertEqual(gold.stat().st_mode & 0o777, 0o600)
        self.assertIn('PRIVATE GOLD', gold.read_text())
        with self.assertRaisesRegex(ValueError, 'outside'):
            m.prepare_inputs(self.root, source=self.source, grading_root=self.root / 'private', expected_source_sha=m.sha(self.source))

    def test_missing_assets_prevents_executable_plan(self):
        with self.assertRaisesRegex(ValueError, 'Freeze all initial image'):
            m.prepare(self.root, **self.kw)
        self.assertFalse((self.root / 'plan.json').exists())

    def test_exact_1500_jobs_asset_binding_and_no_vanilla(self):
        m.prepare_inputs(self.root, **self.kw)
        m.immutable_json(self.root / 'image-assets/manifest.json', {'test': True})
        with patch.object(m, 'implementation_hashes', return_value={}), patch.dict(sys.modules, {'mmbc_input_images': self.fake_assets}):
            first = m.prepare(self.root, **self.kw)
            self.assertEqual(first, m.prepare(self.root, **self.kw))
            plan, _ = m.load_validate(self.root)
            self.assertEqual(len(plan['jobs']), 1500)
            self.assertEqual(len({r['job_id'] for r in plan['jobs']}), 1500)
            self.assertEqual({r['repeat'] for r in plan['jobs']}, {1, 2, 3})
            self.assertEqual({r['strategy'] for r in plan['jobs']}, set(m.METHODS))
            self.assertEqual({r['harness'] for r in plan['jobs']}, {'hermes'})
            self.assertNotIn('PRIVATE', json.dumps(plan))
            (self.root / 'image-assets/manifest.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Frozen MMBC input changed'):
                m.validate(plan, self.root)

    def test_source_and_existing_cohort_cannot_be_silently_replaced(self):
        m.prepare_inputs(self.root, **self.kw)
        with self.assertRaisesRegex(ValueError, 'source SHA'):
            m.select_rows(self.source, 'wrong')
        (self.root / 'cohort.jsonl').write_text('{}\n')
        with self.assertRaisesRegex(ValueError, 'Refusing to overwrite'):
            m.prepare_inputs(self.root, **self.kw)

    def test_unapproved_method_or_route_rejected(self):
        cfg = m.read(m.ROOT_CONFIG)
        cfg['mmbc100_campaign']['strategies'].append('vanilla_visual')
        candidate = self.path / 'config.json'
        candidate.write_text(json.dumps(cfg))
        with self.assertRaisesRegex(ValueError, 'scope'):
            m.experiment_config(candidate)
        cfg = m.read(m.ROOT_CONFIG)
        cfg['mmbc100_campaign']['model'] = 'another-route'
        candidate.write_text(json.dumps(cfg))
        with self.assertRaisesRegex(ValueError, 'route'):
            m.experiment_config(candidate)


if __name__ == '__main__':
    unittest.main()
