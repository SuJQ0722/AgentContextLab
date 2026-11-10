import base64
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import controlled_native_worker_bounded_v1 as bounded
from PIL import Image


def image_part(size=(90, 120), color='red', detail='high'):
    buf = io.BytesIO(); Image.new('RGB', size, color).save(buf, format='PNG')
    return {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode(), 'detail': detail}}


class BoundedControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = image_part((2200, 20), detail='low')
        self.prefix = self.root / 'prefix.json'
        self.messages = [
            {'role': 'user', 'content': [{'type': 'text', 'text': 'Question'}, self.native]},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'x', 'type': 'function', 'function': {'name': 'web_search', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'x', 'content': 'Source paragraph 123.\n' * 700 + '\n| A | B |\n|---|---|\n| 7 | 8 |'},
        ]
        self.prefix.write_text(json.dumps({'messages': self.messages, 'model': 'fixture'}))
        self.spec = {'prefix_path': str(self.prefix), 'method': 'visual'}
        self.adapter = bounded.BoundedAdapter(self.spec, self.root / 'out')

    def test_final_fit_registered_native_exact(self):
        pages = [image_part(color='blue'), image_part(color='green')]
        self.adapter.set_pages(pages)
        fitted = [bounded.fit_part(p, .5) for p in pages]
        result = self.adapter.compose([{'role': 'user', 'content': 'Question'}], 'Question', [self.native], fitted)
        self.assertEqual(result[0]['content'][1], self.native)
        self.assertEqual(self.adapter.registry, {bounded.sha(bounded.raw(p)) for p in fitted})
        meta = self.adapter.annotate({'canvas_scale': .5})
        self.assertEqual(meta['effective_canvas_linear_scale'], .375)
        from bounded_visual_request_guard_v1 import inspect_payload
        record = inspect_payload(json.dumps({'messages': result}).encode(), rendered_registry=self.adapter.registry, strict_all_images=False)
        self.assertFalse(record['images'][0]['rendered_canvas'])
        self.assertTrue(record['images'][1]['rendered_canvas'])

    def test_missing_reordered_unknown_and_native_mutation_rejected(self):
        pages = [image_part(color='blue'), image_part(color='green')]; self.adapter.set_pages(pages)
        for invalid in (pages[:1], list(reversed(pages)), [image_part(color='black')]):
            with self.assertRaises(ValueError):
                self.adapter.compose([], 'q', [self.native], invalid)
        changed = copy.deepcopy(self.native); changed['image_url']['detail'] = 'high'
        with self.assertRaises(ValueError):
            self.adapter.compose([], 'q', [changed], [])

    def test_webp_after_fit_preserves_native_and_pixels(self):
        self.adapter.spec['bounded_transport_encoding'] = 'bounded-canvas-lossless-webp-v1'
        pages = [image_part((96, 120), color='blue')]; self.adapter.set_pages(pages)
        fitted = [bounded.fit_part(pages[0], .5)]
        result = self.adapter.compose([], 'q', [self.native], fitted)
        contents = result[0]['content']
        self.assertEqual(contents[1], self.native)
        encoded = contents[2]
        self.assertTrue(encoded['image_url']['url'].startswith('data:image/webp;base64,'))
        with Image.open(io.BytesIO(bounded.raw(encoded))) as a, Image.open(io.BytesIO(bounded.raw(fitted[0]))) as b:
            self.assertEqual(a.size, b.size); self.assertEqual(a.convert('RGBA').tobytes(), b.convert('RGBA').tobytes())
        self.assertIn(bounded.sha(bounded.raw(encoded)), self.adapter.registry)
        elapsed = self.adapter.encoding_seconds
        self.adapter.compose([], 'q', [self.native], fitted)
        self.assertEqual(self.adapter.encoding_seconds, elapsed)

    def test_new_namespace_and_original_cohort_binding(self):
        original = dict(self.spec, question='Q', question_id='q', dataset='bc', image=['frozen'], repeat=1, threshold=16384, max_rounds=60)
        plan = {'jobs': [{'job_id': 'original/visual', 'method': 'visual', 'prefix_key': 'original'}], 'prefixes': [{'key': 'original', 'spec': original}]}
        planpath = self.root / 'plan.json'; planpath.write_text(json.dumps(plan))
        spec = dict(original, bounded_native_protocol=bounded.PROTOCOL, source_parent_plan_path=str(planpath), source_parent_plan_sha256=bounded.sha(planpath.read_bytes()), source_parent_job_id='original/visual')
        with patch.object(bounded, 'OUTPUT_ROOT', self.root / 'new'):
            bounded.validate_spec(spec, self.root / 'new/job')
            with self.assertRaises(ValueError): bounded.validate_spec(spec, self.root / 'old/job')
            changed = dict(spec, question='different')
            with self.assertRaises(ValueError): bounded.validate_spec(changed, self.root / 'new/job')
            changed = dict(spec, bounded_native_protocol={})
            with self.assertRaises(ValueError): bounded.validate_spec(changed, self.root / 'new/job')

    def test_old_target_rejected_even_when_prefix_matches(self):
        original = dict(self.spec, method='summary', question='Q', question_id='q', dataset='bc', image=['frozen'], repeat=1, threshold=16384, max_rounds=60)
        plan = {'jobs': [{'job_id': 'original/summary', 'method': 'summary', 'prefix_key': 'original'}], 'prefixes': [{'key': 'original', 'spec': original}]}
        planpath = self.root / 'plan.json'; planpath.write_text(json.dumps(plan))
        ref = self.root / 'new/visual/compression-control.json'; ref.parent.mkdir(parents=True); ref.write_text(json.dumps({'passed': True, 'method': 'visual'}))
        spec = dict(original, bounded_native_protocol=bounded.PROTOCOL, source_parent_plan_path=str(planpath), source_parent_plan_sha256=bounded.sha(planpath.read_bytes()), source_parent_job_id='original/summary', target_reference_path=str(ref))
        with patch.object(bounded, 'OUTPUT_ROOT', self.root / 'new'):
            with self.assertRaisesRegex(ValueError, 'same new bounded'): bounded.validate_spec(spec, self.root / 'new/summary')

    def test_real_pdf_pages_not_merged_and_table_preserved(self):
        try:
            import pymupdf
        except ImportError:
            from lab import python_for, environment, ROOT
            env, _ = environment(ROOT, 'hermes')
            command = "import importlib.util,sys,unittest;s=importlib.util.spec_from_file_location('bounded_control_tests',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);r=unittest.TextTestRunner().run(unittest.TestSuite([m.BoundedControlTests('test_real_pdf_pages_not_merged_and_table_preserved')]));sys.exit(not r.wasSuccessful())"
            result = subprocess.run([python_for(ROOT), '-c', command, str(Path(__file__).resolve())], env=env, cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr[-6000:])
            return
        clean = bounded.v5.text_only(self.messages)
        pages, elapsed = self.adapter.render_prefix(clean, 16)
        self.assertGreaterEqual(len(pages), 2)
        self.assertGreater(elapsed, 0)
        for page in pages:
            with Image.open(io.BytesIO(bounded.raw(page))) as image:
                self.assertLessEqual(image.width, 768)
                self.assertLessEqual(image.height, 1152)
            self.assertEqual(page['image_url']['detail'], 'high')
        pdfs = list((self.root / 'out/bounded-render').glob('*.pdf'))
        self.assertTrue(pdfs)
        import pymupdf
        text = ''
        for path in pdfs:
            with pymupdf.open(path) as document:
                text += ''.join(page.get_text() for page in document)
        self.assertIn('Source paragraph 123', text)
        self.assertIn('7', text)
        self.assertIn('8', text)


if __name__ == '__main__': unittest.main()
