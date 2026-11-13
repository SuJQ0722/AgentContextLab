import base64,io,json,sys,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import inline_visual_transport_v1 as inline
from dsh_canvas_segments_v13 import select_canvas_pages,verified_handle
class SegmentTests(unittest.TestCase):
 def fixture(self,n=7):
  content=[];registry=set()
  for i in range(n):
   buf=io.BytesIO();Image.new('RGB',(12,20),(i,2,3)).save(buf,format='WEBP',lossless=True);raw=buf.getvalue();sha=hashlib.sha256(raw).hexdigest();registry.add(sha)
   content.extend([{'type':'text','text':f"[{'History'if i<n-2 else'Recent'} page {i+1}/{n} — linear scale 0.75, high detail]"},{'type':'text','text':f'Image sha256:{sha}; request preview 12x20px. It may be resized or re-encoded; source dimensions, format, and byte size may differ.'},{'type':'image_url','image_url':{'url':'data:image/webp;base64,'+base64.b64encode(raw).decode(),'detail':'high'}}])
  return {'model':'fixture','messages':[{'role':'user','content':content}]},registry
 def test_old_failure_new_exact_bytes(self):
  payload,reg=self.fixture();raw=json.dumps(payload).encode()
  with self.assertRaisesRegex(ValueError,'verified segment label'):inline.select_canvas_pages(raw,reg,{'history':5,'recent':2})
  with patch.object(inline,'select_canvas_pages',select_canvas_pages):wire,a=inline.transform(raw,rendered_registry=reg,page_budget={'history':5,'recent':2})
  self.assertEqual(wire,raw);self.assertEqual(a['image_count'],7);self.assertEqual(a['hosting_calls'],0)
 def test_drop_page_also_drops_only_its_native_handle(self):
  payload,reg=self.fixture(9);raw=json.dumps(payload).encode();wire,a=select_canvas_pages(raw,reg,{'history':5,'recent':2});c=json.loads(wire)['messages'][0]['content'];self.assertEqual(c,payload['messages'][0]['content'][6:]);self.assertEqual(a['verified_native_handle_count'],9)
 def test_unrelated_text_or_wrong_hash_cannot_mask_missing_label(self):
  for replacement in ['unrelated text','Image sha256:'+'0'*64+'; request preview 12x20px. It may be resized or re-encoded; source dimensions, format, and byte size may differ.']:
   payload,reg=self.fixture();payload['messages'][0]['content'][1]['text']=replacement
   with self.assertRaises(ValueError):select_canvas_pages(json.dumps(payload).encode(),reg,{'history':5,'recent':2})
 def test_normalized_handle_and_dimensions_are_bound(self):
  payload,reg=self.fixture();parts=payload['messages'][0]['content'];sha=hashlib.sha256(base64.b64decode(parts[2]['image_url']['url'].split(',')[1])).hexdigest();h=f'Image "canvas" (sha256:{sha}); request preview 12x20px. Normalized copy (read-only; may be resized or re-encoded): "/read-only/file.webp" (12x20px, image/webp). Source dimensions, format, and byte size may differ. Copy to a writable path ending in .webp before editing.'
  self.assertTrue(verified_handle(h,parts[2],reg));self.assertFalse(verified_handle(h.replace('preview 12x20','preview 1x20'),parts[2],reg))
 def test_native_evidence_and_text_preserved(self):
  payload,reg=self.fixture();native=payload['messages'][0]['content'][-1].copy();sha=hashlib.sha256(base64.b64decode(native['image_url']['url'].split(',')[1])).hexdigest();reg.remove(sha);wire,a=select_canvas_pages(json.dumps(payload).encode(),reg,{'history':5,'recent':2});self.assertEqual(json.loads(wire),payload);self.assertTrue(a['native_images_preserved'])
if __name__=='__main__':unittest.main()
