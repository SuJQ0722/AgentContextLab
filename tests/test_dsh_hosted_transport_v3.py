import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from lab import runtime_path


class DSHInlineV3Tests(unittest.TestCase):
    def node(self, code):
        env = {**os.environ, 'PATH': runtime_path(ROOT)}
        for key in ('ACL_INLINE_DSH_LEDGER', 'ACL_HOSTED_DSH_LEDGER', 'ACL_BOUNDED_WIRE_LEDGER'):
            env.pop(key, None)
        run = subprocess.run(['node', '--input-type=module', '-e', code], cwd=ROOT, env=env,
                             capture_output=True, text=True, timeout=45)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_actual_sdk_dispatcher_inline_stream_upload_and_usage(self):
        sdk = next((ROOT / 'deepseekHarness/node_modules/.pnpm').glob('openai@7.19.0*undici@8.11.2*/node_modules/openai/index.mjs'))
        code = """
import assert from 'node:assert/strict';import http from 'node:http';
import {setGlobalDispatcher,Agent}from './deepseekHarness/node_modules/.pnpm/undici@8.11.2/node_modules/undici/index.js';
import OpenAI from SDK_PATH;
import {guardedFetch,ROUTES}from './scripts/dsh_hosted_wire_v3.mjs';
setGlobalDispatcher(new Agent());let received,wireHeaders;
const server=http.createServer((req,res)=>{let body='';wireHeaders=req.headers;req.on('data',x=>body+=x);req.on('end',()=>{received=JSON.parse(body);res.setHeader('content-type','text/event-stream');res.end('data: {"id":"fixture","choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}\\n\\ndata: [DONE]\\n\\n');});});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const endpoint='http://127.0.0.1:'+server.address().port+'/v1/chat/completions';const rows=[];
const guarded=guardedFetch({original:fetch,transform:async body=>({wire:body,ledger:{}}),endpoint,emit:r=>rows.push(r),initialRouteIndex:0});
const client=new OpenAI({baseURL:endpoint.replace('/chat/completions',''),apiKey:'fixture',fetch:guarded,maxRetries:0});
try{let chunks=0;for await(const c of await client.chat.completions.create({model:ROUTES[0],messages:[{role:'user',content:'你好'.repeat(60000)}],stream:true})){chunks++;assert.equal(c.usage.total_tokens,3);}
assert.equal(chunks,1);assert.equal(received.model,ROUTES[0]);assert.equal(wireHeaders['transfer-encoding'],'chunked');assert.equal(wireHeaders['content-length'],undefined);
assert(rows.some(r=>r.event==='request_body_sent'));assert(rows.some(r=>r.event==='first_response_bytes'));assert(rows.some(r=>r.event==='stream_complete'&&r.raw_provider_usage?.total_tokens===3));
assert(!rows.some(r=>r.event==='route_transport_error'));
}finally{server.closeAllConnections();server.close();}
""".replace('SDK_PATH', json.dumps('./' + str(sdk.relative_to(ROOT))))
        self.node(code)

    def test_rotation_chunk_sizes_retry_wait_and_no_route_mix(self):
        self.node("""
import assert from 'node:assert/strict';import {guardedFetch,ROUTES}from './scripts/dsh_hosted_wire_v3.mjs';
let calls=[],chunks=[],rows=[],waits=[],clock=0;
const endpoint='http://fixture/v1/chat/completions';
const f=guardedFetch({endpoint,initialRouteIndex:0,transform:async body=>({wire:body,ledger:{}}),emit:r=>rows.push(r),sleep:async ms=>{waits.push(ms);clock+=ms},now:()=>clock,random:()=>0,
original:async(input,init)=>{assert.equal(init.duplex,'half');assert.equal(init.headers.has('content-length'),false);let body='';for await(const part of init.body){chunks.push(part.length);body+=Buffer.from(part)}calls.push(JSON.parse(body).model);if(calls.length<=4)return new Response('quota',{status:429,headers:{'retry-after':'0'}});return new Response('data: [DONE]\\n\\n',{status:200});}});
const body=JSON.stringify({model:ROUTES[0],messages:[{role:'user',content:'x'.repeat(200000)}]});
assert.equal((await f(endpoint,{method:'POST',body})).status,200);assert.deepEqual(calls,[...ROUTES,ROUTES[0]]);assert.deepEqual(waits,[60100]);assert(chunks.every(n=>n<=65536));
await f(endpoint,{method:'POST',body});assert.equal(calls.at(-1),ROUTES[0]);assert.equal(rows.filter(r=>r.event==='route_cycle_backoff').length,1);
""")

    def test_partial_stream_failure_rotates_without_mixing(self):
        self.node("""
import assert from 'node:assert/strict';import {guardedFetch,ROUTES}from './scripts/dsh_hosted_wire_v3.mjs';let n=0;const rows=[];const endpoint='http://fixture/v1/chat/completions';
const f=guardedFetch({endpoint,initialRouteIndex:0,transform:async body=>({wire:body,ledger:{}}),emit:r=>rows.push(r),original:async()=>{n++;if(n===1)return new Response(new ReadableStream({pull(c){if(!this.sent){this.sent=true;c.enqueue(new TextEncoder().encode('data: {\"usage\":{\"total_tokens\":3}}\\n\\n'));}else c.error(new TypeError('terminated'));}}));return new Response('new route complete');}});
const response=await f(endpoint,{method:'POST',body:JSON.stringify({model:ROUTES[0],messages:[]})});assert.equal(await response.text(),'new route complete');assert.equal(n,2);assert(rows.some(r=>r.event==='route_transport_error'&&r.usage_known===true&&r.raw_provider_usage.total_tokens===3));
""")

    def test_403_404_unsupported400_rotate_401_is_terminal(self):
        self.node("""
import assert from 'node:assert/strict';import {guardedFetch,ROUTES}from './scripts/dsh_hosted_wire_v3.mjs';let n=0;const endpoint='http://fixture/v1/chat/completions';const body=JSON.stringify({model:ROUTES[0],messages:[]});
const common={endpoint,initialRouteIndex:0,transform:async body=>({wire:body,ledger:{}}),emit:()=>{}};
const f=guardedFetch({...common,original:async()=>{n++;return n===1?new Response('',{status:403}):n===2?new Response('',{status:404}):n===3?new Response(JSON.stringify({error:{message:'model does not support image'}}),{status:400}):new Response('ok');}});
assert.equal(await(await f(endpoint,{method:'POST',body})).text(),'ok');assert.equal(n,4);
let stopped=0,auth=0;const denied=guardedFetch({...common,terminate:()=>{stopped++},original:async()=>{auth++;return new Response('',{status:401});}});await assert.rejects(()=>denied(endpoint,{method:'POST',body}));assert.equal(stopped,1);assert.equal(auth,1);
""")

    def test_bridge_retains_last10_inline_no_upload_dependency(self):
        from PIL import Image
        raw = io.BytesIO();Image.new('RGB', (8, 8), 'blue').save(raw, format='PNG')
        data = 'data:image/png;base64,' + base64.b64encode(raw.getvalue()).decode()
        payload = {'model': 'deepseek-v4.1-flash-1017/huoshan/huoshan', 'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'preserve'}] + [{'type': 'image_url', 'image_url': {'url': data, 'detail': 'high'}} for _ in range(12)]}]}
        with tempfile.TemporaryDirectory() as directory:
            self.node("import assert from 'node:assert/strict';import {pythonBridge}from './scripts/dsh_hosted_wire_v3.mjs';const bridge=pythonBridge(" + json.dumps(sys.executable) + ',' + json.dumps(directory) + ");const out=await bridge(" + json.dumps(json.dumps(payload)) + ");const p=JSON.parse(out.wire);assert.equal(p.messages[0].content.length,11);assert.equal(p.messages[0].content[0].text,'preserve');assert(p.messages[0].content.slice(1).every(x=>x.image_url.url.startsWith('data:image/')&&x.image_url.detail==='high'));assert(!out.wire.includes('https://'));" )
        for name in ('dsh_inline_transport_bridge_v1.py', 'dsh_hosted_bc_worker_v3.py', 'hermes_visual_hosted_retry_worker_v3.py', 'controlled_hosted_visual_worker_v3.py'):
            source = (ROOT / 'scripts' / name).read_text()
            self.assertNotIn('VerifiedImageHost', source)
            self.assertNotIn('verified_hosted_images', source)
            self.assertNotIn('_upload_imgbb', source)


if __name__ == '__main__':
    unittest.main()
