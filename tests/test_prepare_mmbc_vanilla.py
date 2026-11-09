import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_mmbc100_campaign as base
import prepare_mmbc_vanilla as m
from mmbc_input_images import image_info


class VanillaScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.parent, self.root = self.path / 'parent', self.path / 'vanilla'
        source = self.path / 'source.jsonl'
        self.url = 'https://raw.githubusercontent.com/fixture/image.png'
        source.write_bytes(base.jsonl([{'id': f'mmbc_{i:03}', 'question': f'Q{i}',
            'image': [self.url] if i % 2 else [], 'answer': f'PRIVATE GOLD {i}'} for i in range(400)]))
        args = {'source': source, 'grading_root': self.path / 'private-grading', 'expected_source_sha': base.sha(source)}
        base.prepare_inputs(self.parent, **args)
        data = io.BytesIO()
        Image.new('RGB', (3, 2), 'red').save(data, format='PNG')
        self.asset_relative = 'image-assets/original.image'
        base.immutable(self.parent / self.asset_relative, data.getvalue())
        base.immutable_json(self.parent / 'image-assets/manifest.json', {
            'version': 'mmbc-original-input-images-v1', 'cohort_sha256': base.sha(self.parent / 'cohort.jsonl'),
            'images': {self.url: {'relative_path': self.asset_relative, **image_info(data.getvalue())}}})
        with patch.object(base, 'implementation_hashes', return_value={}):
            base.prepare(self.parent, **args)
        self.parent_plan_sha = base.sha(self.parent / 'plan.json')
        self.source_patch = patch.object(m, 'new_source_hashes', return_value={})
        self.source_patch.start()
        self.addCleanup(self.source_patch.stop)

    def test_same_cohort_original_bytes_and_fixed300_not_extra_seeds(self):
        manifest = m.prepare(self.root, self.parent)
        plan, _ = m.load_validate(self.root)
        self.assertEqual(len(plan['jobs']), 300)
        self.assertEqual({j['repeat'] for j in plan['jobs']}, {1, 2, 3})
        self.assertEqual({j['strategy'] for j in plan['jobs']}, {'visual'})
        self.assertEqual({j['method_label'] for j in plan['jobs']}, {'vanilla_visual'})
        parent_jobs = [j for j in base.read(self.parent / 'plan.json')['jobs'] if j['strategy'] == 'visual']
        self.assertEqual([j['job_id'] for j in plan['jobs']], [j['job_id'] for j in parent_jobs])
        for name in ('cohort.jsonl', 'cohort-manifest.json', 'image-assets/manifest.json', self.asset_relative):
            self.assertEqual((self.root / name).read_bytes(), (self.parent / name).read_bytes())
        self.assertNotEqual((self.root / self.asset_relative).stat().st_ino,
                            (self.parent / self.asset_relative).stat().st_ino)
        self.assertEqual(base.sha(self.parent / 'plan.json'), self.parent_plan_sha)
        self.assertEqual(manifest, m.prepare(self.root, self.parent))
        self.assertNotIn('PRIVATE GOLD', json.dumps(plan))
        self.assertFalse((self.root / 'private').exists())

    def test_only_authorized_config_difference(self):
        m.prepare(self.root, self.parent)
        parent_cfg = base.read(self.parent / 'experiment.json')
        cfg = base.read(self.root / 'experiment.json')
        self.assertTrue(cfg['shared_policy']['strategy_configs']['visual'].pop('text_only'))
        self.assertEqual(cfg.pop('vanilla_visual_protocol'), m.PROTOCOL)
        cfg['campaign_version'] = parent_cfg['campaign_version']
        self.assertEqual(cfg, parent_cfg)
        self.assertEqual(cfg['execution_version'], 'hermes-parity-v3')

    def test_unauthorized_budget_change_rejected_even_with_rehashed_config(self):
        m.prepare(self.root, self.parent)
        plan = base.read(self.root / 'plan.json')
        cfg = base.read(self.root / 'experiment.json')
        cfg['max_output_tokens'] += 1
        (self.root / 'experiment.json').write_text(json.dumps(cfg))
        plan['definition']['config_sha256'] = base.sha(self.root / 'experiment.json')
        with self.assertRaisesRegex(ValueError, 'more than the authorized'):
            m.validate_sources(plan, self.root)

    def test_changed_job_label_or_parent_plan_rejected(self):
        m.prepare(self.root, self.parent)
        plan = base.read(self.root / 'plan.json')
        plan['jobs'][0]['method_label'] = 'VERA'
        plan['definition']['jobs_sha256'] = base.digest(plan['jobs'])
        with self.assertRaisesRegex(ValueError, 'fixed parent'):
            m.validate_sources(plan, self.root)
        p = self.parent / 'plan.json'
        p.write_text(p.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'manifest/plan'):
            m.load_validate(self.root)

    def test_separate_root_and_no_overwrite_guards(self):
        with self.assertRaisesRegex(ValueError, 'separate'):
            m.prepare_inputs(self.parent, self.parent)
        m.prepare(self.root, self.parent)
        (self.root / self.asset_relative).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Refusing to overwrite'):
            m.prepare(self.root, self.parent)

    def test_new_source_lineage_must_remain_frozen(self):
        m.prepare(self.root, self.parent)
        plan = base.read(self.root / 'plan.json')
        with patch.object(m, 'new_source_hashes', return_value={'scripts/lab.py': base.sha(base.ROOT / 'scripts/lab.py')}):
            with self.assertRaisesRegex(ValueError, 'source lineage changed'):
                m.validate_sources(plan, self.root)


if __name__ == '__main__':
    unittest.main()
