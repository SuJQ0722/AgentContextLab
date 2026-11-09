import base64
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from mmbc_vanilla_renderer import install

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('vanilla_test_renderer', ROOT/'hermes-agent/plugins/context_engine/visual/render.py')
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


class VanillaRendererTests(unittest.TestCase):
    def image_part(self):
        b = io.BytesIO(); Image.new('RGB', (32, 32), 'red').save(b, format='PNG')
        return {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()}}

    def fixture(self):
        return {'role':'tool','tool_name':'image_crop','tool_call_id':'crop1','content':[
            {'type':'text','text':'Original crop metadata; not a generated caption.\n| item | amount |\n| --- | --- |\n| FACT_Q | 731942 |'}, self.image_part()]}

    def test_actual_pdf_omits_image_but_keeps_all_table_text(self):
        try:
            import pymupdf
        except ModuleNotFoundError:
            from lab import python_for
            executable = python_for(ROOT)
            self.assertNotEqual(Path(executable).resolve(), Path(sys.executable).resolve(), 'Research renderer Python must provide PyMuPDF')
            code = "import importlib.util,sys,unittest; s=importlib.util.spec_from_file_location('real_pdf_test',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); r=unittest.TextTestRunner().run(unittest.TestSuite([m.VanillaRendererTests('test_actual_pdf_omits_image_but_keeps_all_table_text')])); sys.exit(not r.wasSuccessful())"
            result = subprocess.run([executable, '-c', code, str(Path(__file__).resolve())], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            return
        renderer = module(); message = self.fixture()
        normal = renderer._format_message_block(message)
        self.assertTrue(normal['table_data']); self.assertTrue(normal['images'])
        install(renderer)
        block = renderer._format_message_block(message)
        self.assertIsNone(block['table_data']); self.assertIn('731942', block['body'])
        self.assertIn('FACT_Q', block['body']); self.assertTrue(block['images'])
        with tempfile.TemporaryDirectory() as cache:
            normal_pdf = renderer._blocks_to_pdf_bytes([normal], font_path=None, font_size=16, page_width=1600,
                max_image_height=2400, dpi=150, text_only=False, image_cache_dir=cache)
            vanilla_pdf = renderer._blocks_to_pdf_bytes([block], font_path=None, font_size=16, page_width=1600,
                max_image_height=2400, dpi=150, text_only=True, image_cache_dir=cache)
        with pymupdf.open(stream=normal_pdf, filetype='pdf') as doc:
            self.assertGreater(sum(len(page.get_images()) for page in doc), 0)
        with pymupdf.open(stream=vanilla_pdf, filetype='pdf') as doc:
            self.assertEqual(sum(len(page.get_images()) for page in doc), 0)
            text = '\n'.join(page.get_text() for page in doc)
            for value in ('731942', 'FACT_Q', 'Original crop metadata'):
                self.assertIn(value, text)

    def test_original_module_and_plain_text_are_unchanged(self):
        adapted, original = module(), module()
        message = {'role':'tool','tool_name':'web_search','content':'Existing textual title and URL https://example.org'}
        expected = original._format_message_block(message)
        install(adapted); install(adapted)
        self.assertEqual(adapted._format_message_block(message), expected)
        self.assertTrue(original._format_message_block(self.fixture())['table_data'])

    def test_visual_flag_required_and_omission_is_not_false_coverage(self):
        renderer = module()
        renderer.render_visual_compression = lambda **kwargs: kwargs['messages']
        install(renderer)
        with self.assertRaises(ValueError): renderer.render_visual_compression(messages=[])
        stats = {'source_image_input_occurrences':4,'rendered_source_images':0,'source_image_coverage_verified':False}
        head_tail = [{'role':'user','content':[self.image_part()]}, self.fixture()]
        result = renderer.render_visual_compression(messages=head_tail, text_only=True, stats=stats)
        self.assertIs(result, head_tail)
        self.assertFalse(stats['source_image_coverage_verified'])
        self.assertEqual(stats['omitted_source_image_occurrences'], 4)
        self.assertTrue(stats['visual_evidence_intentionally_omitted'])
        self.assertFalse(stats['generated_captions'])

    def test_rendered_evidence_in_vanilla_is_fatal(self):
        renderer = module(); renderer.render_visual_compression = lambda **kwargs: []
        install(renderer)
        with self.assertRaises(RuntimeError):
            renderer.render_visual_compression(messages=[], text_only=True, stats={'rendered_source_images':1})


if __name__ == '__main__': unittest.main()
