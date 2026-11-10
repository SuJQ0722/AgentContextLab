import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'tests'))
import recent_ten_images_transport_v1 as transport
import hermes_bounded_mmbc_recent_ten_worker_v1 as worker
import bounded_ten_image_guard_v1 as guard
from test_bounded_ten_image_guard_v1 import image,part,cfg

def dumps(payload):return json.dumps(payload,ensure_ascii=True,indent=1).encode()
def pictures(n):return [image(color=(i%256,0,0))for i in range(n)]
def shape_without_images(payload):
 value=copy.deepcopy(payload)
 for m in value['messages']:
  if isinstance(m.get('content'),list):m['content']=[p for p in m['content']if p.get('type')!='image_url']
 return value

class RecentTenTests(unittest.TestCase):
 def test_eleven_native_keeps_last_ten_exact_bytes_and_empty_first_message(self):
  raw=pictures(11);payload={'model':'fixture','messages':[{'role':'user','content':[part(raw[0])]},{'role':'assistant','content':[part(r)for r in raw[1:]]}]};original=dumps(payload)
  wire,record=transport.transform(original,rendered_registry=set());actual=json.loads(wire)
  self.assertEqual(actual['messages'][0],{'role':'user','content':[]});self.assertEqual(actual['messages'][1],payload['messages'][1]);self.assertEqual(original,dumps(payload))
  self.assertEqual(record['original_image_count'],11);self.assertEqual(record['retained_image_count'],10);self.assertEqual(record['removed_image_count'],1)
  self.assertEqual(record['removed'][0]['sha256'],hashlib.sha256(raw[0]).hexdigest());self.assertEqual([r['sha256']for r in record['retained']],[hashlib.sha256(r).hexdigest()for r in raw[1:]])
  self.assertEqual(record['empty_content_message_indices'],[0]);self.assertEqual(record['final_guard']['image_count'],10)
 def test_global_mixed_order_keeps_text_roles_tools_and_counts_repeated_occurrences(self):
  raw=pictures(13);registry={hashlib.sha256(raw[i]).hexdigest()for i in(0,4,7,12)}
  messages=[{'role':'system','content':'instructions unchanged 中文'},
   {'role':'assistant','content':[part(raw[0]),{'type':'text','text':'exact text\nURL abc'},part(raw[1])],'tool_calls':[{'id':'tool-1','type':'function','function':{'name':'web_search','arguments':'{"q":"test"}'}}]},
   {'role':'tool','tool_call_id':'tool-1','content':[part(raw[2]),{'type':'text','text':'tool evidence'},part(raw[3])]},
   {'role':'user','content':[part(r)for r in raw[4:]]}]
  payload={'model':'fixture','messages':messages,'temperature':0,'stream':True,'stream_options':{'include_usage':True},'tools':[{'type':'function','function':{'name':'web_search'}}]};wire,record=transport.transform(dumps(payload),rendered_registry=registry);actual=json.loads(wire)
  self.assertEqual(shape_without_images(actual),shape_without_images(payload));self.assertEqual([x['original_image_ordinal']for x in record['removed']],[0,1,2]);self.assertEqual([x['original_image_ordinal']for x in record['retained']],list(range(3,13)))
  self.assertEqual(record['retained'][0]['wire_part_index'],1);self.assertEqual(record['removed'][0]['origin'],'canvas');self.assertEqual(record['retained'][-1]['origin'],'canvas');self.assertEqual(record['retained'][0]['origin'],'native')
  repeated={'messages':[{'role':'user','content':[part(raw[0])]*11}]};_,record=transport.transform(dumps(repeated),rendered_registry=registry);self.assertEqual(record['removed_image_count'],1);self.assertEqual(record['retained_image_count'],10)
 def test_text_and_ten_images_no_change_registry_failure_and_final_limit(self):
  for n in(0,10):
   payload={'messages':[{'role':'user','content':[{'type':'text','text':'hello'}]+[part(r)for r in pictures(n)]}]};original=dumps(payload);wire,record=transport.transform(original,rendered_registry=set());self.assertEqual(wire,original);self.assertFalse(record['request_body_modified'])
  for invalid in(None,b'{',dumps({'messages':[{'role':'user','content':[{'type':'image_url','image_url':'https://example.invalid/a'}]}]})):
   with self.assertRaises(transport.RecentImageTransportError):transport.transform(invalid,rendered_registry=set())
  huge={'messages':[{'role':'user','content':[{'type':'text','text':'x'*(8*1024*1024)}]}]}
  with self.assertRaises(transport.RecentImageTransportError)as e:transport.transform(dumps(huge),rendered_registry=set())
  self.assertIn('body_exceeds_8_mib',e.exception.ledger['violations'])
  with self.assertRaises(transport.RecentImageTransportError):transport.transform(dumps({'messages':[]}),rendered_registry=lambda:(_ for _ in()).throw(ValueError('manifest changed')))
 def test_final_body_header_response_usage_and_pre_retention_observer_order(self):
  original=dumps({'messages':[{'role':'tool','tool_call_id':'x','content':[{'type':'text','text':'keep tool'}]+[part(r)for r in pictures(12)]}],'stream':True,'stream_options':{'include_usage':True}})
  seen=[];events=[]
  response=httpx.Response(200,content=b'data: {"usage":{"prompt_tokens":10,"prompt_tokens_details":{"cached_tokens":6},"completion_tokens":2,"total_tokens":12}}\n\ndata: [DONE]\n\n',headers={'content-type':'text/event-stream'})
  def final(client,request):events.append('actual_wire');seen.append(request);return response
  def earlier(client,request,*args,**kwargs):
   events.append('pre_retention');self.assertEqual(request.content,original);return client._send_single_request(request)
  with tempfile.TemporaryDirectory()as d,patch.object(httpx.Client,'_send_single_request',final),patch.object(httpx.Client,'send',earlier):
   path=Path(d)/'wire.jsonl';transport.install(path,rendered_registry=set());request=httpx.Request('POST','https://fixture.invalid/v1/chat/completions',content=original,headers={'content-length':'1','x-fixture':'keep'},extensions={'timeout':{'read':4}});actual=httpx.Client(trust_env=False).send(request)
   self.assertIs(actual,response);self.assertIn(b'"cached_tokens":6',actual.content);self.assertEqual(events,['pre_retention','actual_wire']);self.assertEqual(request.content,original);self.assertEqual(request.headers['content-length'],'1')
   out=seen[0];self.assertEqual(out.headers['content-length'],str(len(out.content)));self.assertEqual(out.headers['x-fixture'],'keep');self.assertEqual(out.extensions,request.extensions);self.assertEqual(out.method,request.method);self.assertEqual(out.url,request.url)
   rows=[json.loads(x)for x in path.read_text().splitlines()];r=rows[0];self.assertEqual(r['original_body_sha256'],hashlib.sha256(original).hexdigest());self.assertEqual(r['final_body_sha256'],hashlib.sha256(out.content).hexdigest());self.assertEqual(r['final_guard']['image_count'],10);self.assertEqual(r['removed_image_count'],2)
   with self.assertRaises(RuntimeError):guard.install(path,rendered_registry=set())
 def test_limit_applies_to_actual_retained_body_not_larger_original_body(self):
  # A valid PNG may contain trailing bytes; the dropped image remains byte-audited.
  large=image()+b'\0'*(7*1024*1024)
  payload={'messages':[{'role':'user','content':[part(large)]+[part(r)for r in pictures(10)]}]}
  original=dumps(payload);self.assertGreater(len(original),8*1024*1024)
  wire,record=transport.transform(original,rendered_registry=set())
  self.assertLess(len(wire),8*1024*1024);self.assertEqual(record['removed'][0]['sha256'],hashlib.sha256(large).hexdigest());self.assertTrue(record['network_send_authorized'])
 def test_ledger_write_failure_prevents_network(self):
  sent=[]
  with tempfile.TemporaryDirectory()as d,patch.object(httpx.Client,'_send_single_request',lambda *a:sent.append(a)):
   transport.install(Path(d)/'wire.jsonl',rendered_registry=set())
   req=httpx.Request('POST','https://fixture.invalid/v1/chat/completions',content=dumps({'messages':[]}))
   with patch.object(Path,'open',side_effect=OSError('fixture disk full')),self.assertRaises(OSError):httpx.Client(trust_env=False)._send_single_request(req)
   self.assertEqual(sent,[])
 def test_pre_retention_vision_ledger_is_not_labelled_final_wire(self):
  instance=object.__new__(worker.RetentionVisionRecorder);writes=[]
  with patch.object(worker.VisionRecorder,'write',side_effect=lambda *a:writes.append(a)):
   instance.write('vision-wire.jsonl',{'event':'final_http_payload','images':[{'payload_sha256':'fixture'}]});instance.write('calls.jsonl',{'usage':{'total_tokens':12}})
  self.assertEqual(writes[0][0],'vision-pre-retention.jsonl');self.assertTrue(writes[0][1]['not_final_wire']);self.assertEqual(writes[1],('calls.jsonl',{'usage':{'total_tokens':12}}))
 def test_worker_preserves_mm_scope_allows_empty_images_and_restores_hooks(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);cp=root/'config.json';config={**cfg(),'bounded_request_protocol':worker.PROTOCOL,'bounded_image_retention':transport.RETENTION};cp.write_text(json.dumps(config));spec={'config_path':str(cp),'strategy':'visual','bounded_request_protocol':worker.PROTOCOL,'bounded_image_retention':transport.RETENTION};sp=root/'spec.json';sp.write_text(json.dumps(spec));events=[];stage=object();oldstage=object();oldrecorder=object();original=lambda *a:events.append('configure');native=types.SimpleNamespace(configure_engine=original,stage_images=oldstage,VisionRecorder=oldrecorder)
   def main():
    self.assertIs(native.VisionRecorder,worker.RetentionVisionRecorder);self.assertIs(native.stage_images,stage);native.configure_engine(types.SimpleNamespace(_history_scale=.75,_text_only=False),'visual',{})
   native.main=main
   def install(path,*,rendered_registry):self.assertEqual(rendered_registry(),set());events.append('transport');return{'max_images':10}
   with patch.dict(sys.modules,{'hermes_bc_worker_v3':native,'mmbc_input_images':types.SimpleNamespace(stage_images=stage),'plugins.context_engine.visual':types.SimpleNamespace(render=object())}),patch.object(worker,'validate',return_value=True),patch('bounded_multimodal_renderer_v1.install',side_effect=lambda r:events.append('renderer')),patch('bounded_lossless_transport_v1.install',side_effect=lambda r:events.append('encoding')),patch.object(transport,'install',side_effect=install),patch.object(sys,'argv',['worker','--spec',str(sp),'--out',str(root/'native'),'--live']):worker.main()
   self.assertEqual(events,['configure','renderer','encoding','transport']);self.assertIs(native.VisionRecorder,oldrecorder);self.assertIs(native.stage_images,oldstage)
   with patch.object(worker.ten,'validate',return_value=True)as validate:
    self.assertTrue(worker.validate(spec,config,root));self.assertEqual(validate.call_args[0][0]['bounded_request_protocol'],worker.ten.PROTOCOL)
    with self.assertRaises(ValueError):worker.validate({**spec,'bounded_image_retention':'preserve_all'},config,root)
if __name__=='__main__':unittest.main()
