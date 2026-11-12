import base64,importlib.util,io,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import page_window_renderer_v1 as window

class WindowTests(unittest.TestCase):
    def test_real_pdf_window_scale_registry_and_wire(self):
        try: import pymupdf
        except ImportError:
            from lab import python_for
            run=subprocess.run([python_for(ROOT),str(Path(__file__))],cwd=ROOT,capture_output=True,text=True,timeout=120)
            self.assertEqual(run.returncode,0,run.stderr[-5000:]);return
        from PIL import Image
        from test_bounded_multimodal_renderer_v1 import module,fixture
        from inline_visual_transport_v1 import transform
        config={'version':window.VERSION,'width':1152,'height':2048,'pages':7,'recent_pages':2,'history_scale':.75}
        render=module();window.install(render,config)
        with tempfile.TemporaryDirectory() as directory:
            messages=fixture(directory)
            # Keep native crop/zoom/table evidence, and enough source text to overflow seven pages.
            messages[3]['content']=' '.join('fact_%05d exact research observation.'%i for i in range(6000))
            stats={};result=render.render_visual_compression(messages,head_end=2,keep_rounds=1,save_dir=directory,stats=stats)
            m=json.loads(Path(stats['page_window_manifest']).read_text())
            self.assertGreater(m['source_page_count'],7);self.assertEqual(len(m['pages']),7)
            self.assertEqual([p['segment'] for p in m['pages']],['history']*5+['recent']*2)
            self.assertEqual([p['dimensions'] for p in m['pages']],[[864,1536]]*5+[[1152,2048]]*2)
            self.assertEqual(result[:2],messages[:2]);self.assertEqual(result[-2:],messages[-2:])
            registry=window.registered_pages(Path(directory));self.assertTrue(registry)
            body=json.dumps({'messages':result}).encode()
            wire,row=transform(body,rendered_registry=registry,page_budget={'history':5,'recent':2},max_canvas_pixels=1152*2048,max_body_bytes=3*1024*1024)
            self.assertEqual(row['selection']['canvas_page_selection']['retained_counts'],{'history':5,'recent':2})
            self.assertLessEqual(len(wire),3*1024*1024)
            # Reclassify old recent pages by physical position, independent of tool rounds.
            self.assertEqual(m['pages'][-3]['scale'],.75)
            with self.assertRaisesRegex(ValueError,'bytes'):
                transform(body,rendered_registry=registry,page_budget={'history':5,'recent':2},max_canvas_pixels=1152*2048,max_body_bytes=1)
            path=Path(m['pages'][0]['path']);path.write_bytes(b'tamper')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):window.registered_pages(Path(directory))

if __name__=='__main__':unittest.main()
