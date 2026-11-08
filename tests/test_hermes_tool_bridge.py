"""No-network checks of the shared Hermes handlers and bridge image artifacts."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lab import python_for
from hermes_tool_bridge import python_no_proxy


class HermesToolBridgeTests(unittest.TestCase):
    def test_dsh_ipv6_proxy_bypass_is_compatible_with_python(self):
        self.assertEqual(python_no_proxy('localhost,127.0.0.1,::1,[::1],10.1.2.3'), 'localhost,127.0.0.1,::1,10.1.2.3')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.env = dict(os.environ, ACL_WEB_SECRETS=json.dumps({"search": {}, "fetch": {"extract_mode": "text"}}),
                        HERMES_IMAGE_ROOT=str(self.workspace))
        self.python = python_for(ROOT)
        subprocess.run([self.python, "-c", "from PIL import Image; import sys; Image.new('RGB',(128,96),(20,80,130)).save(sys.argv[1])", str(self.workspace / "source.png")], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, tool, arguments):
        run = subprocess.run([self.python, str(ROOT / "scripts/hermes_tool_bridge.py"), "--workspace", str(self.workspace)],
                             input=json.dumps({"tool": tool, "arguments": arguments, "call_id": tool}),
                             text=True, capture_output=True, env=self.env, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr[-1000:])
        return json.loads(run.stdout)

    def test_crop_and_zoom_preserve_handler_image_bytes_and_geometry(self):
        source = str(self.workspace / "source.png")
        crop = self.call("image_crop", {"image_path": source, "bbox": [16, 16, 112, 80], "coord_format": "absolute", "padding": 0, "use_smart_resize": False})
        zoom = self.call("image_zoom_in", {"image_path": source, "bbox_2d": [16, 16, 112, 80], "use_super_resolution": False, "use_smart_resize": False})
        for result in (crop, zoom):
            self.assertEqual([part["type"] for part in result["content"]], ["text", "image"])
            image = result["content"][1]
            self.assertEqual((image["width"], image["height"]), (96, 64))
            self.assertEqual(image["sha256"], hashlib.sha256(Path(image["path"]).read_bytes()).hexdigest())
            self.assertEqual(image["media_type"], "image/png")
            self.assertEqual(result["metadata"]["source"], source)
        self.assertEqual(crop["content"][1]["sha256"], zoom["content"][1]["sha256"])

    def test_bad_bbox_and_outside_root_remain_hermes_errors(self):
        bad = self.call("image_crop", {"image_path": str(self.workspace / "source.png"), "bbox": [1, 2]})
        self.assertEqual(len(bad["content"]), 1)
        self.assertIn("bbox", bad["content"][0]["text"])
        outside = self.call("image_zoom_in", {"image_path": "/etc/passwd", "bbox_2d": [0, 0, 100, 100]})
        self.assertIn("allowed root", outside["content"][0]["text"])

    def test_shared_web_handlers_keep_envelopes_language_and_head_tail(self):
        code = r'''
import asyncio, json, sys
from pathlib import Path
from unittest.mock import patch, AsyncMock
sys.path.insert(0, sys.argv[1]+'/scripts')
import hermes_tool_bridge as bridge
bridge.initialize(Path(sys.argv[2]))
import plugins.local_web as web
from plugins.local_web import search_provider as search
class Response:
    headers={'X-Cached':'true'}
    def raise_for_status(self): pass
    def json(self): return {'organic':[{'title':'A','link':'https://example.test','snippet':'S'}]}
payloads=[]
def post(*a,**kw): payloads.append(json.loads(kw['content'])); return Response()
with patch.object(search,'_read_http_search',return_value={'url':'fixture','port':80,'api_key':'fixture'}), patch.object(search,'_resolve_api_key',return_value='fixture'), patch.object(search.httpx,'post',side_effect=post):
    for q in ['example','中文']:
        value=json.loads(web._handle_search({'query':q,'limit':5})); assert value['success'] and value['data']['web'][0]['position']==1
assert payloads[0]['hl']=='en' and payloads[1]['hl']=='zh-cn'
body='HEAD\n'+'a'*12000+'\nTAIL'
async def extract(*a,**kw): return [{'url':'https://example.test','title':'','content':body,'raw_content':body,'metadata':{}}]
with patch('tools.web_tools.async_is_safe_url',new=AsyncMock(return_value=True)),patch.object(web._FETCH,'extract',side_effect=extract):
    value=json.loads(asyncio.run(web._handle_extract({'urls':['https://example.test'],'char_limit':2000})))
text=value['results'][0]['content']; assert 'HEAD' in text and 'TAIL' in text and 'TRUNCATED' in text
print(json.dumps({'language':True,'envelope':True,'head_tail':True}))
'''
        run = subprocess.run([self.python, "-c", code, str(ROOT), str(self.workspace)], env=self.env,
                             text=True, capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr[-1000:])
        self.assertTrue(json.loads(run.stdout)["head_tail"])

    def test_markdown_fetch_is_blocked_before_reader_model_can_run(self):
        self.env["ACL_WEB_SECRETS"] = json.dumps({"search": {}, "fetch": {"extract_mode": "markdown"}})
        run = subprocess.run([self.python, str(ROOT / "scripts/hermes_tool_bridge.py"), "--workspace", str(self.workspace)],
                             input=json.dumps({"tool": "web_extract", "arguments": {"urls": ["https://example.test"]}}),
                             text=True, capture_output=True, env=self.env, timeout=20)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("explicit text mode is required", run.stderr)

    def test_shared_spill_budget_and_verified_original_url(self):
        code = r'''
import json,os,sys,hashlib
from pathlib import Path
sys.path.insert(0, sys.argv[1]+'/scripts')
import hermes_tool_bridge as b
workspace=Path(sys.argv[2]); b.initialize(workspace); b.handlers()
from tools.tool_result_storage import maybe_persist_tool_result
from tools.environments.local import LocalEnvironment
raw='prefix\n'+'x'*110000+'\nend'
actual=b.apply_result_budget(raw,'web_extract','budget-fixture',workspace)
expected=maybe_persist_tool_result(raw,'web_extract','budget-fixture',env=LocalEnvironment(cwd=str(workspace)))
assert actual==expected and '<persisted-output>' in actual
messages=[{'role':'tool','tool_call_id':f'budget-{i}','content':'x'*90000} for i in range(3)]
result=b.apply_turn_budget({'messages':messages,'context_length':1000000},workspace)
assert sum(len(m['content']) for m in result['messages'])<=200000
source=workspace/'source.png'; sha=hashlib.sha256(source.read_bytes()).hexdigest()
manifest=workspace/'origins.json';manifest.write_text(json.dumps({'images':[{'path':str(source),'sha256':sha,'origin_url':'https://example.test/original.png','kind':'native_original'}]}))
os.environ['ACL_IMAGE_ORIGIN_MAP']=str(manifest)
args,evidence=b.resolve_origin_arguments({'image_path':str(source)})
assert args['image_url']=='https://example.test/original.png' and evidence['sha256']==sha
assert b.resolve_origin_arguments({'image_path':str(workspace/'derived-crop.png')})[1] is None
source.write_bytes(b'changed')
try: b.resolve_origin_arguments({'image_path':str(source)})
except ValueError: pass
else: raise AssertionError('changed source admitted')
print(json.dumps({'shared_budget':True,'verified_origin':True}))
'''
        run = subprocess.run([self.python, "-c", code, str(ROOT), str(self.workspace)], env=self.env,
                             text=True, capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr[-1000:])
        self.assertTrue(json.loads(run.stdout)["verified_origin"])


if __name__ == "__main__":
    unittest.main()
