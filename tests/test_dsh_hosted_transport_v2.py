import json
import base64
import hashlib
import io
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from lab import runtime_path

class DSHHostedV2Tests(unittest.TestCase):
 def node(self,code):
  env={**os.environ,'PATH':runtime_path(ROOT)}
  for key in ('ACL_HOSTED_DSH_LEDGER','ACL_BOUNDED_CANVAS_ROOT','ACL_BOUNDED_WIRE_LEDGER'):env.pop(key,None)
  r=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
  self.assertEqual(r.returncode,0,r.stderr)
 def test_fetch_final_body_usage_failures_and_unrelated_routes(self):
  self.node("""
import assert from 'node:assert/strict';import {guardedFetch} from './scripts/dsh_hosted_wire_v2.mjs';
let sent=[],rows=[],terminated=0;const wire=JSON.stringify({messages:[{role:'user',content:[{type:'image_url',image_url:{url:'https://i.ibb.co/fixture'}}]}]});
const f=guardedFetch({endpoint:'http://fixture/v1/chat/completions',transform:async()=>({wire,ledger:{image_count:10}}),emit:r=>rows.push(r),terminate:()=>{terminated++},original:async(i,opts)=>{sent.push(opts.body);return new Response('data: {"usage":{"total_tokens":3}}\\n\\ndata: [DONE]\\n\\n',{status:200})}});
for(let i=0;i<3;i++){let r=await f('http://fixture/v1/chat/completions',{method:'POST',body:'original'});assert.match(await r.text(),/total_tokens/);}
assert.equal(sent.length,3);assert.equal(terminated,0);assert(sent.every(x=>x===wire));assert.equal(rows.filter(r=>r.event==='stream_complete').length,3);
let errors=0;const bad=guardedFetch({endpoint:'http://fixture/v1/chat/completions',transform:async()=>({wire,ledger:{}}),emit:()=>{},terminate:()=>{terminated++},original:async()=>{errors++;throw Error('network')}});
for(let i=0;i<3;i++)await assert.rejects(()=>bad('http://fixture/v1/chat/completions',{method:'POST',body:'a'}));assert.equal(errors,2);assert.equal(terminated,1);
let touched=false;const untouched=guardedFetch({endpoint:'http://fixture/v1/chat/completions',transform:()=>{throw Error('should not transform')},emit:()=>{},original:async()=>{touched=true;return new Response('web')}});assert.equal(await(await untouched('http://fixture/search')).text(),'web');assert(touched);
""")
 def test_python_bridge_text_no_hosting_and_lifecycle(self):
  with tempfile.TemporaryDirectory()as d:
   code="import assert from 'node:assert/strict';import {pythonBridge} from './scripts/dsh_hosted_wire_v2.mjs';const b=pythonBridge("+json.dumps(sys.executable)+","+json.dumps(d+'/canvas')+","+json.dumps(d+'/cache')+");const r=await b(JSON.stringify({messages:[{role:'user',content:'hello'}]}));assert.equal(JSON.parse(r.wire).messages[0].content,'hello');assert.equal(r.ledger.image_count,0);"
   self.node(code)
 def test_real_bridge_last_ten_verified_cache_and_source_classification(self):
  from PIL import Image
  from info_loss_phase4_url import pixel_sha
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);cache=root/'cache/hosted';cache.mkdir(parents=True)
   buffer=io.BytesIO();Image.new('RGB',(8,8),'blue').save(buffer,format='PNG');raw=buffer.getvalue();digest=hashlib.sha256(raw).hexdigest();pixel,dimensions=pixel_sha(raw)
   (cache/(digest+'.json')).write_text(json.dumps({'url':'https://i.ibb.co/fixture/test.png','source_sha256':digest,'download_sha256':digest,'byte_identical':True,'pixel_identical':True,'pixel_sha256':pixel,'dimensions':dimensions}))
   payload={'messages':[{'role':'user','content':[{'type':'text','text':'retain text'}]+[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(raw).decode(),'detail':'high'}}for _ in range(12)]}]}
   code="import assert from 'node:assert/strict';import {pythonBridge} from './scripts/dsh_hosted_wire_v2.mjs';const b=pythonBridge("+json.dumps(sys.executable)+","+json.dumps(d+'/canvas')+","+json.dumps(d+'/cache')+");const r=await b("+json.dumps(json.dumps(payload))+");assert.equal(r.ledger.image_count,10);assert.equal(r.ledger.selection.removed_image_count,2);assert(r.ledger.selection.retained.every(x=>x.origin==='native'));const p=JSON.parse(r.wire);assert.equal(p.messages[0].content[0].text,'retain text');assert(p.messages[0].content.slice(1).every(x=>x.image_url.url.startsWith('https:')&&x.image_url.detail==='high'));"
   self.node(code)
 def test_wrapper_preserves_old_guard_order_and_restores(self):
  import dsh_hosted_bc_worker_v2 as w
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);metrics=root/'run/workspace/metrics';metrics.mkdir(parents=True)
   c=root/'config.json';c.write_text(json.dumps({'image_transport':'verified-imgbb-url-v2','bounded_max_images':10,'bounded_request_protocol':'bounded-multimodal-recent-ten-v1','transport_runtime_version':'visual-transport-runtime-v2'}))
   old=str(ROOT/'scripts/dsh_bounded_wire_guard_v1.mjs');env={'NODE_OPTIONS':'--import '+old+' --import '+str(ROOT/'scripts/dsh_wire_image_guard.mjs'),'ACL_BOUNDED_WIRE_LEDGER':str(metrics/'old.jsonl')}
   def launch(*args):return env['NODE_OPTIONS']
   def main():
    out=w.parent.native.command(ROOT,'dsh','prompt',env)
    self.assertTrue(out.startswith('--import '+str(ROOT/'scripts/dsh_hosted_wire_v2.mjs')));self.assertIn('dsh_wire_image_guard.mjs',out);self.assertNotIn(old,out)
   with patch.object(w.parent.native,'command',launch),patch.object(w.parent,'main',main),patch.object(sys,'argv',['worker','--config',str(c)]):w.main();self.assertIs(w.parent.native.command,launch)

 def test_actual_openai_sdk_sse_over_localhost(self):
  self.node('import http from \'node:http\';import OpenAI from \'./deepseekHarness/node_modules/.pnpm/openai@7.19.0_@aws-sdk+credential-provider-node@3.972.84_@smithy+signature-v4@5.7.4_undici@8.11.2_ws@8.21.3_zod@4.4.3/node_modules/openai/index.mjs\';import {guardedFetch}from \'./scripts/dsh_hosted_wire_v2.mjs\';const server=http.createServer((req,res)=>{let body=\'\';req.on(\'data\',x=>body+=x);req.on(\'end\',()=>{res.setHeader(\'content-type\',\'text/event-stream\');res.end(\'data: {"id":"fixture","choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}\\n\\ndata: [DONE]\\n\\n\')})});await new Promise(r=>server.listen(0,\'127.0.0.1\',r));const endpoint=\'http://127.0.0.1:\'+server.address().port+\'/v1/chat/completions\';const rows=[];const guarded=guardedFetch({original:fetch,transform:async body=>({wire:body,ledger:{}}),endpoint,emit:r=>rows.push(r)});const client=new OpenAI({baseURL:endpoint.replace(\'/chat/completions\',\'\'),apiKey:\'fixture\',fetch:guarded,maxRetries:0});try{let chunks=0;for await(const c of await client.chat.completions.create({model:\'fixture\',messages:[{role:\'user\',content:\'你好\'}],stream:true})){chunks++;}if(chunks!==1||rows.some(r=>r.event===\'send_error\'||r.event===\'stream_error\'))throw Error(\'SDK transport failed\');}catch(e){console.log(JSON.stringify({name:e.name,cause:e.cause?.message,root:e.cause?.cause?.code}));process.exitCode=1;}finally{server.closeAllConnections();server.close()}')

if __name__=='__main__':unittest.main()
