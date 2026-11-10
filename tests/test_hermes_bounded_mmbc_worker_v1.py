import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import hermes_bounded_mmbc_worker_v1 as worker


def sha(raw): return hashlib.sha256(raw).hexdigest()


def write_png(path, dimensions):
    buffer = io.BytesIO(); Image.new('RGB', dimensions, 'white').save(buffer, format='PNG')
    raw = buffer.getvalue(); path.write_bytes(raw)
    return {'sha256': sha(raw), 'dimensions': list(dimensions), 'bytes': len(raw)}


class BoundedMMBCWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.out = self.root / 'new-bounded-attempt'
        self.config = {'bounded_visual_protocol': worker.PROTOCOL,
            'shared_policy': {'strategy_configs': {'visual': {'font_size': 16,
                'history_scale': .75, 'image_width': 1024, 'max_image_height': 2048,
                'history_max_image_height': 2048}}}, 'visual_renderer': {'history_scale': .75}}
        self.cp = self.root / 'config.json'; self.cp.write_text(json.dumps(self.config))
        self.spec = {'bounded_visual_protocol': worker.PROTOCOL, 'strategy': 'visual',
                     'config_path': str(self.cp), 'config_sha256': sha(self.cp.read_bytes())}

    def manifest(self):
        directory = self.out / 'context_images'; directory.mkdir(parents=True)
        source = directory / 'source.pdf'; source.write_bytes(b'fixture-pdf-bytes')
        raw = directory / 'raw.png'; final = directory / 'page.png'
        before = write_png(raw, (16, 20)); after = write_png(final, (12, 15))
        manifest = {'version': worker.PROTOCOL,
            'layout': {'width': 1024, 'max_page_side': 2048, 'font_size': 16, 'dpi': 72,
                'far_scale': .75, 'recent_scale': 1., 'vertical_merge': False,
                'far_pre_enlargement': False, 'fit_to_content_height': False},
            'source_pdfs': [{'segment': 'history', 'path': str(source),
                'sha256': sha(source.read_bytes()), 'page_dimensions': [[1024, 2048]]}],
            'pages': [{'segment': 'history', 'page_index': 1, 'segment_pages': 1,
                'scale': .75, 'detail': 'high', 'raw_path': str(raw), 'raw': before,
                'path': str(final), 'output': after}],
            'output_image_count': 1, 'output_total_png_bytes': after['bytes']}
        path = directory / 'compact_1_bounded_manifest.json'; path.write_text(json.dumps(manifest))
        return directory, path, manifest

    def test_new_namespace_and_optional_campaign_root(self):
        self.assertTrue(worker.validate(self.spec, self.config, self.out))
        self.assertNotIn('campaign_root', self.spec)
        with patch.object(worker, 'ROOT', self.root):
            for name in ('mmbc100-hermes-deepseek-v1', 'mmbc100-hermes-vanilla-v1'):
                old = self.root / 'outputs/campaigns' / name
                with self.assertRaisesRegex(ValueError, 'immutable'):
                    worker.validate(self.spec, self.config, old / 'jobs/attempt')
                for key in ('campaign_root', 'config_path'):
                    with self.assertRaisesRegex(ValueError, 'immutable'):
                        worker.validate({**self.spec, key: str(old / 'something')}, self.config, self.out)
                old.mkdir(parents=True)
                link = self.root / ('link-' + name); link.symlink_to(old, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, 'immutable'):
                    worker.validate(self.spec, self.config, link / 'attempt')

    def test_explicit_scale_geometry_and_protocol(self):
        for target in ('shared', 'legacy'):
            cfg = copy.deepcopy(self.config)
            if target == 'shared': cfg['shared_policy']['strategy_configs']['visual']['history_scale'] = 1.
            else: cfg['visual_renderer']['history_scale'] = 1.
            with self.assertRaises(ValueError): worker.validate(self.spec, cfg, self.out)
        with self.assertRaises(ValueError): worker.validate({**self.spec, 'bounded_visual_protocol': 'old'}, self.config, self.out)
        with self.assertRaises(ValueError): worker.validate({**self.spec, 'config_sha256': '0' * 64}, self.config, self.out)
        with self.assertRaises(ValueError): worker.validate({**self.spec, 'harness': 'dsh'}, self.config, self.out)

    def test_existing_attempt_not_overwritten(self):
        self.out.mkdir()
        for name in ('attempt-started.json', 'native-result.json', 'bounded-protocol.json'):
            marker = self.out / name; marker.write_text('original')
            with self.assertRaisesRegex(ValueError, 'overwritten'): worker.validate(self.spec, self.config, self.out)
            self.assertEqual(marker.read_text(), 'original'); marker.unlink()

    def test_registry_checks_source_raw_final_sha_and_full_coverage(self):
        directory, path, manifest = self.manifest()
        self.assertEqual(worker.registered_pages(directory), {manifest['pages'][0]['output']['sha256']})
        for artifact in [Path(manifest['source_pdfs'][0]['path']),
                         Path(manifest['pages'][0]['raw_path']), Path(manifest['pages'][0]['path'])]:
            original = artifact.read_bytes(); artifact.write_bytes(original + b'tampered')
            with self.assertRaisesRegex(ValueError, 'SHA mismatch'): worker.registered_pages(directory)
            artifact.write_bytes(original)
        bad = copy.deepcopy(manifest); bad['source_pdfs'][0]['page_dimensions'].append([1024, 2048])
        bad['pages'][0]['segment_pages'] = 2; path.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError, 'page missing'): worker.registered_pages(directory)

    def test_registry_rejects_path_escape_layout_and_wrong_dimensions(self):
        directory, path, manifest = self.manifest()
        bad = copy.deepcopy(manifest); bad['source_pdfs'][0]['path'] = str(self.cp)
        with self.assertRaisesRegex(ValueError, 'outside'):
            path.write_text(json.dumps(bad)); worker.registered_pages(directory)
        bad = copy.deepcopy(manifest); bad['layout']['vertical_merge'] = True
        with self.assertRaisesRegex(ValueError, 'layout'):
            path.write_text(json.dumps(bad)); worker.registered_pages(directory)
        bad = copy.deepcopy(manifest); bad['pages'][0]['output']['dimensions'] = [13, 15]
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            path.write_text(json.dumps(bad)); worker.registered_pages(directory)

    def encoded_manifest(self):
        import bounded_lossless_transport_v1 as encoder
        directory, source_manifest, bounded = self.manifest()
        page = bounded['pages'][0]; raw = Path(page['path']).read_bytes()
        encoded, record = encoder.encode(raw); output = directory / 'page.webp'; output.write_bytes(encoded)
        manifest = {'version': encoder.VERSION, 'native_images_encoded': 0,
            'source_bounded_manifest': str(source_manifest),
            'source_bounded_manifest_sha256': sha(source_manifest.read_bytes()),
            'pages': [{**record, 'source_path': page['path'], 'path': str(output),
                       'segment': page['segment'], 'page_index': 1, 'detail': 'high'}]}
        path = directory / 'compact_1_transport_manifest.json'; path.write_text(json.dumps(manifest))
        return directory, path, manifest, bounded

    def test_webp_registry_success_and_actual_wrong_pixels_rejected(self):
        directory, path, manifest, bounded = self.encoded_manifest()
        hashes = worker.registered_pages(directory)
        self.assertIn(manifest['pages'][0]['output_sha256'], hashes)
        self.assertIn(bounded['pages'][0]['output']['sha256'], hashes)
        # A forged matching byte SHA must not hide decoded-pixel modification.
        output = Path(manifest['pages'][0]['path'])
        Image.new('RGB', (12, 15), 'black').save(output, format='WEBP', lossless=True, exact=True)
        manifest['pages'][0]['output_sha256'] = sha(output.read_bytes()); path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'pixel identity'): worker.registered_pages(directory)

    def test_webp_missing_page_and_substitute_source_manifest_rejected(self):
        directory, path, manifest, bounded = self.encoded_manifest()
        original = copy.deepcopy(manifest); manifest['pages'] = []; path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'omitted a page'): worker.registered_pages(directory)
        substitute = directory / 'unverified-subset.json'
        substitute.write_text(json.dumps({'pages': bounded['pages']}))
        original['source_bounded_manifest'] = str(substitute)
        original['source_bounded_manifest_sha256'] = sha(substitute.read_bytes()); path.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, 'fully verified'): worker.registered_pages(directory)

    def test_main_installs_bounded_before_guard_and_restores_native_hooks(self):
        sp = self.root / 'spec.json'; sp.write_text(json.dumps(self.spec)); events = []
        def original(engine, strategy, policy): engine._history_scale = .75; events.append('native-configure')
        old_stage = object()
        fake = types.SimpleNamespace(configure_engine=original, stage_images=old_stage)
        def native_main():
            fake.configure_engine(types.SimpleNamespace(_text_only=False), 'visual', {})
            events.append('native-after-configure')
        fake.main = native_main
        render = object()
        def install_guard(path, *, rendered_registry):
            events.append('guard'); self.assertEqual(rendered_registry(), set())
            self.assertEqual(path, self.out / 'metrics/bounded-request-guard.jsonl')
        with patch.dict(sys.modules, {'hermes_bc_worker_v3': fake,
                'plugins.context_engine.visual': types.SimpleNamespace(render=render)}), \
             patch('bounded_multimodal_renderer_v1.install', side_effect=lambda r: events.append('bounded')), \
             patch('bounded_visual_request_guard_v1.install', side_effect=install_guard), \
             patch.object(sys, 'argv', ['worker', '--spec', str(sp), '--out', str(self.out), '--live']):
            worker.main()
        self.assertEqual(events, ['native-configure', 'bounded', 'guard', 'native-after-configure'])
        self.assertIs(fake.configure_engine, original); self.assertIs(fake.stage_images, old_stage)
        ledger = json.loads((self.out / 'bounded-protocol.json').read_text())
        self.assertEqual(ledger['far_scale'], .75); self.assertFalse(ledger['vertical_merge'])
        self.assertEqual(ledger['implementation_sha256']['bounded_visual_request_guard_v1.py'],
                         sha((worker.ROOT / 'scripts/bounded_visual_request_guard_v1.py').read_bytes()))


if __name__ == '__main__': unittest.main()
