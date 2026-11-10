import base64
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bounded_multimodal_renderer_v1 as bounded


def module():
    spec = importlib.util.spec_from_file_location('bounded_test_hermes_renderer', ROOT / 'hermes-agent/plugins/context_engine/visual/render.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def png(color='red', width=80, height=60):
    output = io.BytesIO()
    Image.new('RGB', (width, height), color).save(output, format='PNG')
    return output.getvalue()


def part(raw):
    return {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(raw).decode()}}


def call(i, name='web_extract'):
    return {'role': 'assistant', 'content': f'REASON_{i}', 'tool_calls': [
        {'id': f't{i}', 'type': 'function', 'function': {'name': name, 'arguments': '{}'}}]}


def fixture(directory):
    p = Path(directory)
    first, second = p / 'search1.png', p / 'search2.png'
    first.write_bytes(png('purple')); second.write_bytes(png('orange'))
    red, blue = png('red'), png('blue')
    head = [{'role': 'system', 'content': 'PROTECTED_SYSTEM'},
            {'role': 'user', 'content': [{'type': 'text', 'text': 'PROTECTED_TASK'}, part(red)]}]
    long_text = lambda prefix: '\n'.join(f'{prefix}_{i:03} searchable fact number {900000+i}.' for i in range(180))
    bodies = [long_text('FAR_FACT'),
              [{'type': 'text', 'text': 'CROP_FACT actual returned crop'}, part(red), part(red)],
              {'_multimodal': True, 'content': [{'type': 'text', 'text': 'ZOOM_FACT actual returned zoom'}, part(blue)]},
              json.dumps({'tool': 'image_search', 'results': [
                  {'thumbnail_url': str(first), 'title': 'SEARCH_A'}, {'thumbnail_url': str(second), 'title': 'SEARCH_B'}]}),
              '\n'.join(['| item | exact value |', '|---|---|'] + [f'| ROW_{i:03} | CELL_{731000+i} |' for i in range(140)]),
              long_text('RECENT_A'), long_text('RECENT_B'), 'PROTECTED_TAIL']
    names = ['web_extract', 'image_crop', 'image_zoom_in', 'image_search', 'web_extract', 'web_extract', 'web_extract', 'web_extract']
    messages = list(head)
    for i, (name, body) in enumerate(zip(names, bodies)):
        messages += [call(i, name), {'role': 'tool', 'tool_call_id': f't{i}', 'content': body}]
    return messages


class BoundedRendererTests(unittest.TestCase):
    def research(self):
        try:
            import pymupdf
            return False
        except ImportError:
            from lab import python_for, environment
            executable = python_for(ROOT)
            self.assertNotEqual(Path(executable).resolve(), Path(sys.executable).resolve())
            env, _ = environment(ROOT, 'hermes')
            code = "import importlib.util,sys,unittest;s=importlib.util.spec_from_file_location('bounded_tests',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);r=unittest.TextTestRunner().run(unittest.TestSuite([m.BoundedRendererTests(sys.argv[2])]));sys.exit(not r.wasSuccessful())"
            result = subprocess.run([executable, '-c', code, str(Path(__file__).resolve()), self._testMethodName],
                                    env=env, cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr[-7000:])
            return True

    def test_actual_pdf_multi_pages_all_images_table_and_head_tail_preserved(self):
        if self.research(): return
        import pymupdf
        render = module()
        bounded.install(render)
        with tempfile.TemporaryDirectory() as directory:
            messages = fixture(directory)
            original = json.dumps(messages)
            stats = {}
            with (patch.object(render, '_merge_images_vertical', side_effect=AssertionError('No image merge')),
                  patch.object(render, '_text_to_images_fallback', side_effect=AssertionError('No fallback'))):
                result = render.render_visual_compression(messages, head_end=2, font_size=16,
                    max_image_height=4096, history_max_image_height=6144, history_scale=.75,
                    recent_rounds=2, keep_rounds=1, stats=stats, save_dir=directory)
            self.assertEqual(json.dumps(messages), original)
            self.assertEqual(result[:2], messages[:2]); self.assertEqual(result[-2:], messages[-2:])
            self.assertIs(result[0], messages[0]); self.assertIs(result[-1], messages[-1])
            self.assertEqual(stats['renderer_version'], bounded.VERSION)
            self.assertEqual(stats['source_image_input_occurrences'], 5)
            self.assertEqual(stats['rendered_source_images'], 4)
            self.assertEqual(stats['deduplicated_source_occurrences'], 1)
            self.assertTrue(stats['source_image_coverage_verified'])
            self.assertEqual(stats['structured_tables_submitted'], 1)
            self.assertGreaterEqual(stats['table_cells_submitted'], 280)
            pages = stats['bounded_pages']
            recent = [p for p in pages if p['segment'] == 'recent']
            history = [p for p in pages if p['segment'] == 'history']
            self.assertGreater(len(recent), 1); self.assertGreater(len(history), 1)
            wire = [p for p in result[2]['content'] if p['type'] == 'image_url']
            self.assertEqual(len(wire), len(pages))
            for image_part, page in zip(wire, pages):
                self.assertEqual(image_part['image_url']['detail'], 'high')
                self.assertEqual(base64.b64decode(image_part['image_url']['url'].split(',', 1)[1]), Path(page['path']).read_bytes())
                self.assertLessEqual(page['raw']['dimensions'][0], 1024)
                self.assertLessEqual(page['raw']['dimensions'][1], 2048)
                if page['segment'] == 'recent': self.assertEqual(page['raw']['sha256'], page['output']['sha256'])
                else:
                    self.assertLessEqual(page['output']['dimensions'][0], 768)
                    self.assertLessEqual(page['output']['dimensions'][1], 1536)
            metadata = json.loads(Path(stats['bounded_page_manifest']).read_text())
            all_text, pdf_images = '', 0
            for source in metadata['source_pdfs']:
                with pymupdf.open(source['path']) as doc:
                    all_text += '\n'.join(page.get_text() for page in doc)
                    pdf_images += sum(len(page.get_image_info()) for page in doc)
                    self.assertTrue(all(page.rect.width <= 1024 and page.rect.height <= 2048 for page in doc))
            self.assertEqual(pdf_images, 4)
            for prefix in ('FAR_FACT', 'RECENT_A', 'RECENT_B'):
                for i in range(180): self.assertIn(f'{prefix}_{i:03}', all_text)
            for i in range(140):
                self.assertIn(f'ROW_{i:03}', all_text); self.assertIn(f'CELL_{731000+i}', all_text)
            self.assertNotIn('PROTECTED_TAIL', all_text)
            self.assertFalse(metadata['layout']['far_pre_enlargement'])
            self.assertFalse(metadata['layout']['vertical_merge'])
            self.assertFalse(metadata['layout']['fit_to_content_height'])

    def test_vanilla_same_bounded_pages_preserve_table_text_explicit_omission(self):
        if self.research(): return
        import pymupdf
        from mmbc_vanilla_renderer import install as vanilla
        render = module(); bounded.install(render, max_page_side=1536); vanilla(render)
        with tempfile.TemporaryDirectory() as directory:
            messages = fixture(directory); stats = {}
            result = render.render_visual_compression(messages, head_end=2, font_size=16,
                max_image_height=4096, history_max_image_height=6144, history_scale=.75,
                recent_rounds=2, keep_rounds=1, text_only=True, stats=stats, save_dir=directory)
            self.assertEqual(result[:2], messages[:2]); self.assertEqual(result[-2:], messages[-2:])
            self.assertEqual(stats['rendered_source_images'], 0)
            self.assertEqual(stats['omitted_source_image_occurrences'], 5)
            self.assertFalse(stats['source_image_coverage_verified'])
            self.assertTrue(stats['visual_evidence_intentionally_omitted'])
            self.assertTrue(all(max(p['output']['dimensions']) <= 1536 for p in stats['bounded_pages']))
            metadata = json.loads(Path(stats['bounded_page_manifest']).read_text()); text = ''
            for source in metadata['source_pdfs']:
                with pymupdf.open(source['path']) as doc:
                    self.assertEqual(sum(len(page.get_image_info()) for page in doc), 0)
                    text += '\n'.join(page.get_text() for page in doc)
            for i in range(140): self.assertIn(f'CELL_{731000+i}', text)

    def test_process_local_idempotence_and_unsafe_variants_rejected(self):
        render, untouched = module(), module()
        original = untouched.render_visual_compression
        bounded.install(render); self.assertEqual(bounded.install(render)['max_page_side'], 2048)
        self.assertIs(untouched.render_visual_compression, original)
        for overrides in ({'layout': 'highlight_no_wrap'}, {'image_width': 3000}, {'history_scale': 0}, {'text_only': True}):
            with self.assertRaises(ValueError): render.render_visual_compression([], 0, **overrides)
        with self.assertRaises(ValueError): bounded.install(render, max_page_side=1536)
        with self.assertRaises(ValueError): bounded.install(module(), far_detail='low')

    def test_no_eligible_span_is_identity(self):
        render = module(); bounded.install(render)
        messages = [{'role': 'user', 'content': 'Keep this intact'}, call(0), {'role': 'tool', 'tool_call_id': 't0', 'content': 'Tail'}]
        self.assertIs(render.render_visual_compression(messages, 1, keep_rounds=1), messages)

    def test_pdf_failure_never_drops_far_history_or_uses_fallback(self):
        render = module(); bounded.install(render)
        messages = [call(0), {'role': 'tool', 'content': 'FAR'}, call(1), {'role': 'tool', 'content': 'RECENT'}]
        with (tempfile.TemporaryDirectory() as directory, patch.object(render, '_blocks_to_pdf_bytes', side_effect=RuntimeError('Table cannot safely split')),
              patch.object(render, '_text_to_images_fallback', side_effect=AssertionError('No fallback'))):
            with self.assertRaisesRegex(RuntimeError, 'safely split'):
                render.render_visual_compression(messages, 0, keep_rounds=0, recent_rounds=1, save_dir=directory)

    def test_oversized_pdf_is_rejected_before_rasterization(self):
        if self.research(): return
        import pymupdf
        with pymupdf.open() as document:
            document.new_page(width=1024, height=9000); raw = document.tobytes()
        render = module(); bounded.install(render)
        with (tempfile.TemporaryDirectory() as directory, patch.object(render, '_blocks_to_pdf_bytes', return_value=raw),
              patch.object(render, '_pdf_bytes_to_image_b64_list', side_effect=AssertionError('Raster must not run'))):
            with self.assertRaisesRegex(ValueError, 'refusing rasterization'):
                render.render_visual_compression([call(0), {'role': 'tool', 'content': 'Fact'}], 0, keep_rounds=0, save_dir=directory)

    def test_oversized_raster_is_not_silently_resized(self):
        render = module(); bounded.install(render)
        huge = base64.b64encode(png(width=1024, height=2049)).decode()
        with (tempfile.TemporaryDirectory() as directory,
              patch.object(render, '_blocks_to_pdf_bytes', return_value=b'geometry-validated-fixture'),
              patch.object(bounded, '_pdf_geometry', return_value=[[1024, 2048]]),
              patch.object(render, '_pdf_bytes_to_image_b64_list', return_value=[huge]),
              patch.object(render, '_downscale_image_b64', side_effect=AssertionError('Cannot repair an oversized raw page by resizing'))):
            with self.assertRaisesRegex(ValueError, 'no implicit shrink'):
                render.render_visual_compression([call(0), {'role': 'tool', 'content': 'Fact'}], 0,
                                                 keep_rounds=0, recent_rounds=0, save_dir=directory)


if __name__ == '__main__':
    unittest.main()
