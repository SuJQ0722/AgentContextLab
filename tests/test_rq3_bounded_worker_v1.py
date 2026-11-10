import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))
import rq3_bounded_renderer_v2 as bounded
import hermes_bounded_rq3_worker_v1 as worker
import bounded_lossless_transport_v1 as codec
from test_bounded_multimodal_renderer_v1 import module, fixture, call


class RQ3BoundedTests(unittest.TestCase):
    def research(self):
        try:
            import pymupdf
            return False
        except ImportError:
            from lab import python_for, environment
            env, _ = environment(ROOT, 'hermes')
            code = "import sys,unittest;sys.path.insert(0,'tests');from test_rq3_bounded_worker_v1 import RQ3BoundedTests;r=unittest.TextTestRunner().run(unittest.TestSuite([RQ3BoundedTests(sys.argv[1])]));sys.exit(not r.wasSuccessful())"
            result = subprocess.run([python_for(ROOT), '-c', code, self._testMethodName], env=env, cwd=ROOT, capture_output=True, text=True, timeout=150)
            self.assertEqual(result.returncode, 0, result.stderr[-6000:]); return True

    def test_actual_zero_and_nonzero_pdf_pages_evidence_headtail_and_codec(self):
        if self.research(): return
        import pymupdf
        for scale in (0., .75):
            with self.subTest(scale=scale), tempfile.TemporaryDirectory() as d:
                render = module(); bounded.install(render); codec.install(render)
                messages = fixture(d); stats = {}
                with patch.object(render, '_merge_images_vertical', side_effect=AssertionError('No merge')):
                    result = render.render_visual_compression(messages, 2, font_size=16, max_image_height=2048,
                        history_max_image_height=2048, history_scale=scale, recent_rounds=2,
                        keep_rounds=1, save_dir=d, stats=stats)
                self.assertIs(result[0], messages[0]); self.assertIs(result[1], messages[1]); self.assertIs(result[-1], messages[-1])
                self.assertGreater(len(stats['bounded_pages']), 1)
                self.assertTrue(stats['transport_pixel_identity_verified'])
                registry = worker.registered_pages(Path(d), scale)
                self.assertEqual(len(registry), 2 * len(stats['bounded_pages']))
                self.assertTrue(stats['source_image_coverage_verified'])
                if scale == 0:
                    self.assertEqual(stats['omitted_far_source_images'], 5)
                    self.assertGreater(stats['omitted_far_messages'], 0)
                    self.assertFalse(stats['whole_render_region_retained'])
                    self.assertEqual(stats['rendered_source_images'], 0)
                    self.assertTrue(all(p['segment'] == 'recent' for p in stats['bounded_pages']))
                else:
                    self.assertEqual(stats['omitted_far_source_images'], 0)
                    self.assertTrue(stats['whole_render_region_retained'])
                    self.assertEqual(stats['source_image_input_occurrences'], 5)
                    self.assertEqual(stats['rendered_source_images'], 4)
                    pdf_text = ''
                    for p in Path(d).glob('*.pdf'):
                        with pymupdf.open(p) as doc:
                            pdf_text += ''.join(page.get_text() for page in doc)
                    for i in range(140): self.assertIn('CELL_' + str(731000+i), pdf_text)
                for page in stats['bounded_pages']:
                    self.assertLessEqual(max(page['output']['dimensions']), 2048)
                    factor = scale if page['segment'] == 'history' else 1.
                    self.assertEqual(page['scale'], factor)
                    self.assertEqual(page['output']['dimensions'], [max(1, int(n*factor)) for n in page['raw']['dimensions']])
                # File-byte or encoded pixel substitution must be caught.
                encoded = Path(stats['bounded_pages'][0]['path']).with_suffix('.webp')
                encoded.write_bytes(encoded.read_bytes() + b'tampered')
                with self.assertRaises(ValueError): worker.registered_pages(Path(d), scale)

    def test_seven_scales_use_same_layout_and_zero_keeps_recent(self):
        if self.research(): return
        raw_dims = None
        for scale in bounded.SCALES:
            with tempfile.TemporaryDirectory() as d:
                render = module(); bounded.install(render); stats = {}
                messages = []
                for i in range(3): messages += [call(i), {'role':'tool','tool_call_id':f't{i}','content': 'Visible fact '+str(i)+' value 731.'}]
                result = render.render_visual_compression(messages, 0, history_scale=scale, recent_rounds=1, keep_rounds=0, save_dir=d, stats=stats)
                pages = stats['bounded_pages']; self.assertTrue(pages)
                self.assertEqual(pages[-1]['segment'], 'recent'); self.assertEqual(pages[-1]['scale'], 1.)
                if scale:
                    self.assertEqual(pages[0]['segment'], 'history')
                    dims=pages[0]['raw']['dimensions']
                    if raw_dims is None: raw_dims=dims
                    self.assertEqual(dims,raw_dims)
                else:
                    self.assertEqual(len(pages),1);self.assertEqual(stats['omitted_far_messages'],4)

    def test_invalid_scale_and_renderer_text_only_fail_closed(self):
        render = module()
        messages = [call(0), {'role':'tool','tool_call_id':'t0','content':'fact'}]
        for value in (True, -.1, .125, 1.1, float('nan')):
            with self.assertRaises(ValueError): bounded.render_visual_compression(render,messages,0,history_scale=value,keep_rounds=0)
        with self.assertRaises(ValueError): bounded.render_visual_compression(render,messages,0,text_only=True,keep_rounds=0)

    def test_worker_requires_agreed_scale_protocol_and_geometry(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'native'
            for scale in bounded.SCALES:
                spec={'strategy':'visual','harness':'hermes','scale':scale,'scale_key':'scale_'+format(round(scale*1000),'04d'),'bounded_rq3_protocol':worker.PROTOCOL}
                cfg={'bounded_rq3_protocol':worker.PROTOCOL,'bounded_transport_encoding':codec.VERSION,'visual_renderer':{'history_scale':scale},'shared_policy':{'strategy_configs':{'visual':{'font_size':16,'image_width':1024,'max_image_height':2048,'history_max_image_height':2048,'history_scale':scale,'keep_rounds':1,'recent_rounds':5,'text_only':False}}}}
                self.assertTrue(worker.validate(spec,cfg,out))
                with self.assertRaises(ValueError): worker.validate({**spec,'scale_key':'scale_0125'},cfg,out)
                with self.assertRaises(ValueError): worker.validate({**spec,'strategy':'none'},cfg,out)
                cfg['visual_renderer']['history_scale']=.125
                with self.assertRaises(ValueError): worker.validate(spec,cfg,out)

    def test_worker_hooks_keep_bc_stage_and_install_guard_after_codec(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=root/'native';events=[]
            cfg={'bounded_rq3_protocol':worker.PROTOCOL,'bounded_transport_encoding':codec.VERSION,'visual_renderer':{'history_scale':0.},'shared_policy':{'strategy_configs':{'visual':{'font_size':16,'image_width':1024,'max_image_height':2048,'history_max_image_height':2048,'history_scale':0.,'keep_rounds':1,'recent_rounds':5,'text_only':False}}}}
            cp=root/'config.json';cp.write_text(json.dumps(cfg))
            spec={'strategy':'visual','harness':'hermes','scale':0.,'scale_key':'scale_0000','bounded_rq3_protocol':worker.PROTOCOL,'config_path':str(cp)}
            sp=root/'spec.json';sp.write_text(json.dumps(spec))
            original=lambda *a:events.append('native')
            stage=object();fake=types.SimpleNamespace(configure_engine=original,stage_images=stage)
            def main():
                self.assertIs(fake.stage_images,stage)
                fake.configure_engine(types.SimpleNamespace(_history_scale=0.),'visual',{})
                events.append('ready')
            fake.main=main
            def guard(path,*,rendered_registry):
                self.assertEqual(rendered_registry(),set());events.append('guard')
            with patch.dict(sys.modules,{'hermes_bc_worker_v3':fake,'plugins.context_engine.visual':types.SimpleNamespace(render=object())}), patch.object(bounded,'install',side_effect=lambda r:events.append('renderer')), patch.object(codec,'install',side_effect=lambda r:events.append('codec')), patch('bounded_visual_request_guard_v1.install',side_effect=guard), patch.object(sys,'argv',['worker','--spec',str(sp),'--out',str(out),'--live']):
                worker.main()
            self.assertEqual(events,['native','renderer','codec','guard','ready'])
            self.assertIs(fake.configure_engine,original);self.assertIs(fake.stage_images,stage)
            self.assertEqual(json.loads((out/'bounded-protocol.json').read_text())['far_scale'],0.)

if __name__=='__main__':unittest.main()
