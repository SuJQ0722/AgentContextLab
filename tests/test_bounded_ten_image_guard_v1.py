import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import httpx
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import bounded_ten_image_guard_v1 as guard
import bounded_visual_request_guard_v1 as old
import hermes_bounded_mmbc_ten_image_worker_v1 as worker

def image(color='red',size=(20,20)):
 b=io.BytesIO();Image.new('RGB',size,color).save(b,format='PNG');return b.getvalue()
def part(raw):return{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(raw).decode(),'detail':'high'}}
def body(parts):return json.dumps({'messages':[{'role':'user','content':parts}],'tools':[{'type':'function','function':{'name':'web_search','parameters':{'type':'object'}}}]}).encode()
def cfg():return{'bounded_benchmark':'mmbc100','bounded_visual_protocol':worker.previous.PROTOCOL,'bounded_request_protocol':worker.PROTOCOL,'bounded_max_images':10,'bounded_transport_encoding':'bounded-canvas-lossless-webp-v1','visual_renderer':{'history_scale':.75},'shared_policy':{'strategy_configs':{'visual':{'font_size':16,'history_scale':.75,'image_width':1024,'max_image_height':2048,'history_max_image_height':2048}}}}

class TenImageTests(unittest.TestCase):
 def test_native_plus_canvas_limit_counts_occurrences_without_deduplication(self):
  native=image();canvas=image('blue');registry={hashlib.sha256(canvas).hexdigest()}
  accepted=body([part(native)]*9+[part(canvas)]);row=guard.inspect_payload(accepted,rendered_registry=registry,strict_all_images=False)
  self.assertEqual(row['image_count'],10);self.assertEqual(row['verified_native_images'],9);self.assertEqual(row['verified_canvas_images'],1)
  self.assertEqual(row['remaining_canvas_slots_after_native'],1);self.assertFalse(row['payload_modified'])
  for parts in ([part(native)]*11,[part(native)]*9+[part(canvas)]*2,[part(canvas)]*33):
   with self.assertRaises(guard.TenImageRequestError)as e:guard.inspect_payload(body(parts),rendered_registry=registry,strict_all_images=False)
   self.assertIn('image_count_exceeds_10',e.exception.ledger['violations']);self.assertNotIn('image_count_exceeds_32',e.exception.ledger['violations'])
  self.assertEqual(old.MAX_IMAGES,32)
 def test_original_size_geometry_and_manifest_checks_remain_fail_closed(self):
  raw=image(size=(2049,2));p=body([part(raw)]);sha=hashlib.sha256(raw).hexdigest()
  self.assertEqual(guard.inspect_payload(p,rendered_registry=set(),strict_all_images=False)['verified_native_images'],1)
  with self.assertRaises(guard.TenImageRequestError)as e:guard.inspect_payload(p,rendered_registry={sha},strict_all_images=False)
  self.assertIn('canvas_side_exceeds_2048',e.exception.ledger['violations'])
  huge=json.loads(body([]));huge['padding']='x'*(8*1024*1024)
  with self.assertRaises(guard.TenImageRequestError)as e:guard.inspect_payload(json.dumps(huge).encode(),rendered_registry=set(),strict_all_images=False)
  self.assertIn('body_exceeds_8_mib',e.exception.ledger['violations'])
  with self.assertRaises(guard.TenImageRequestError)as e:guard.inspect_payload(body([]),rendered_registry=lambda:(_ for _ in()).throw(ValueError('manifest tamper')),strict_all_images=False)
  self.assertIn('rendered_registry_unavailable_or_invalid',e.exception.ledger['violations'])
 def test_uninspectable_and_unsupported_images_never_send(self):
  for p in (None,'text',b'{',b'[]',body([{'type':'image_url','image_url':{'url':'https://example.invalid/image.png'}}])):
   with self.subTest(body_type=type(p)),self.assertRaises(guard.TenImageRequestError):guard.inspect_payload(p,rendered_registry=set(),strict_all_images=False)
 def test_final_boundary_preserves_exact_body_and_usage_and_records_rejection(self):
  with tempfile.TemporaryDirectory()as d:
   p=Path(d)/'guard.jsonl';sent=[];response=httpx.Response(200,json={'usage':{'prompt_tokens':7,'completion_tokens':2,'total_tokens':9}})
   def network(client,request):sent.append(request.content);return response
   with patch.object(httpx.Client,'_send_single_request',network):
    guard.install(p,rendered_registry=set());request=httpx.Request('POST','https://fixture.invalid/v1/chat/completions',content=body([{'type':'text','text':'hello'}]));actual=httpx.Client(trust_env=False)._send_single_request(request)
    self.assertIs(actual,response);self.assertEqual(actual.json()['usage']['total_tokens'],9);self.assertEqual(sent,[request.content])
    with self.assertRaises(guard.TenImageRequestError):httpx.Client(trust_env=False)._send_single_request(httpx.Request('POST',request.url,content=body([part(image())]*11)))
    with self.assertRaises(guard.TenImageRequestError):httpx.Client(trust_env=False)._send_single_request(httpx.Request('POST',request.url,content=iter([body([])])))
    with self.assertRaises(RuntimeError):guard.install(p,rendered_registry=set())
    with self.assertRaises(RuntimeError):old.install(p,rendered_registry=set())
   rows=[json.loads(s)for s in p.read_text().splitlines()];self.assertEqual([r['decision']for r in rows],['allow','reject','reject']);self.assertEqual(rows[1]['max_images'],10);self.assertEqual(len(sent),1)
 def test_worker_requires_new_namespace_explicit_limit_and_frozen_configuration(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);campaign=root/'outputs/campaigns/new-mmbc-ten';campaign.mkdir(parents=True);cp=campaign/'experiment.json';config=cfg();cp.write_text(json.dumps(config));spec={'bounded_benchmark':'mmbc100','question_id':'mmbc_131','image':['fixture-native.png'],'bounded_visual_protocol':worker.previous.PROTOCOL,'bounded_request_protocol':worker.PROTOCOL,'bounded_max_images':10,'strategy':'visual','harness':'hermes','campaign_root':str(campaign),'config_path':str(cp),'config_sha256':hashlib.sha256(cp.read_bytes()).hexdigest()};out=campaign/'jobs/hermes/visual/q/attempts/attempt_001/native'
   with patch.object(worker,'ROOT',root),patch.object(worker.previous,'ROOT',root):
    self.assertTrue(worker.validate(spec,config,out))
    self.assertTrue(worker.validate({**spec,'image':[]},config,out))
    for change in ({'bounded_benchmark':'bc100'},{'question_id':'q_001'},{'image':None},{'bounded_max_images':11},{'bounded_max_images':True},{'bounded_request_protocol':'old'},{'config_sha256':None}):
     with self.assertRaises(ValueError):worker.validate({**spec,**change},config,out)
    with self.assertRaises(ValueError):worker.validate(spec,config,root/'outputs/campaigns/mmbc-vera-bounded-retry-v1/old')
    out.mkdir(parents=True);(out/'bounded-protocol.json').write_text('{}')
    with self.assertRaises(ValueError):worker.validate(spec,config,out)
 def test_worker_keeps_native_staging_registry_and_renders_without_page_fitting(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);cp=root/'config.json';cp.write_text(json.dumps(cfg()));sp=root/'spec.json';sp.write_text(json.dumps({'config_path':str(cp),'strategy':'visual'}));out=root/'native';events=[];original_stage=object();stage=object()
   original=lambda *args:events.append('configure');native=types.SimpleNamespace(configure_engine=original,stage_images=original_stage)
   def main():
    self.assertIs(native.stage_images,stage);native.configure_engine(types.SimpleNamespace(_history_scale=.75,_text_only=False),'visual',{})
   native.main=main
   def install(path,*,rendered_registry):self.assertEqual(rendered_registry(),set());events.append('guard');return{'max_images':10}
   with patch.dict(sys.modules,{'hermes_bc_worker_v3':native,'mmbc_input_images':types.SimpleNamespace(stage_images=stage),'plugins.context_engine.visual':types.SimpleNamespace(render=object())}),patch.object(worker,'validate',return_value=True),patch('bounded_multimodal_renderer_v1.install',side_effect=lambda r:events.append('renderer')),patch('bounded_lossless_transport_v1.install',side_effect=lambda r:events.append('lossless')),patch.object(guard,'install',side_effect=install),patch.object(sys,'argv',['worker','--spec',str(sp),'--out',str(out),'--live']):worker.main()
   self.assertEqual(events,['configure','renderer','lossless','guard']);self.assertIs(native.stage_images,original_stage);self.assertIs(native.configure_engine,original)
   record=json.loads((out/'bounded-protocol.json').read_text());self.assertEqual(record['guard_max_images'],10);self.assertEqual(record['far_scale'],.75);self.assertFalse(record['vertical_merge'])
if __name__=='__main__':unittest.main()
