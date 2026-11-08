import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import * as wrapped from '../scripts/dsh_returned_model_routes1.mjs';
import * as original from '../scripts/dsh_raw_usage_observer.mjs';
function fixture(t,id){const dir=mkdtempSync(join(tmpdir(),'routes1-'));t.after(()=>rmSync(dir,{recursive:true,force:true}));
 const lineage=join(dir,'lineage.json');writeFileSync(lineage,JSON.stringify({logical_model:'deepseek-v4.1-flash-1017/huoshan/huoshan',actual_route:'deepseek-v4.1-flash-1017/zijian/sfb',runtime_route_version:'routes1'}));
 return {dir,options:{requestId:id,requestModel:'deepseek-v4.1-flash-1017/zijian/sfb',sessionId:id,purpose:'agent',ledgerPath:join(dir,'raw-usage.jsonl'),routeLineagePath:lineage}};
}
function rows(path){return readFileSync(path,'utf8').trim().split('\n').map(JSON.parse);}
test('SSE delegates original usage state, keeps body and writes joined attribution only',async t=>{
 const {dir,options}=fixture(t,'sse-routes1');
 const body='data: '+JSON.stringify({model:'deepseek-v4-1-flash-261017',choices:[{delta:{content:'SECRET RESPONSE'}}]})+'\n\n'+
 'data: '+JSON.stringify({model:'deepseek-v4-1-flash-261017',usage:{prompt_tokens:100,completion_tokens:2,total_tokens:102,prompt_tokens_details:{cached_tokens:0}}})+'\n\ndata: [DONE]\n\n';
 const response=new Response(body,{headers:{'content-type':'text/event-stream'}});
 const done=wrapped.observeUsageResponse(response,options);assert.equal(await response.text(),body);await done;
 const flush=await wrapped.flushUsageObservers({sessionId:options.sessionId});assert.deepEqual(flush.pending,[]);
 assert.equal(original.latestRawUsage({sessionId:options.sessionId}).provider_prompt_tokens,100);
 assert.equal(original.latestRawUsage({sessionId:options.sessionId}).cached_input_tokens,0);
 assert.equal(rows(options.ledgerPath).filter(x=>!x.event).length,1);
 const sidecar=rows(join(dir,'route-attribution.jsonl'));assert.equal(sidecar.length,1);
 assert.equal(sidecar[0].returned_model,'deepseek-v4-1-flash-261017');assert.equal(sidecar[0].cached_input_presence,true);
 assert.equal(sidecar[0].cache_value_known,true);assert.equal(sidecar[0].usage_authority,false);
 assert.equal(sidecar[0].returned_model_exactly_matches_request_alias,false);assert.equal(sidecar[0].returned_model_matches_preflight_observation,true);assert.equal(sidecar[0].backend_weights_equivalence_verified,null);assert.ok(!JSON.stringify(sidecar).includes('SECRET RESPONSE'));
});
test('JSON missing cache and returned model remain unknown, no normalized zeros',async t=>{
 const {dir,options}=fixture(t,'json-routes1');const payload={choices:[{message:{content:'PRIVATE'}}],usage:{prompt_tokens:3,completion_tokens:1,total_tokens:4}};
 const response=Response.json(payload);await wrapped.observeUsageResponse(response,options);assert.deepEqual(await response.json(),payload);
 const record=rows(join(dir,'route-attribution.jsonl'))[0];assert.equal(record.returned_model,null);
 assert.equal(record.returned_model_presence,false);assert.equal(record.cached_input_presence,false);assert.equal(record.cache_value_known,false);
 assert.equal(original.latestRawUsage({sessionId:options.sessionId}).noncache_input_tokens,null);
});
test('transport failure still reaches original observer and contains no invented model',t=>{
 const {dir,options}=fixture(t,'failure-routes1');wrapped.recordUsageTransportFailure(options,new TypeError('private endpoint'));
 const raw=original.latestRawUsage({sessionId:options.sessionId});assert.equal(raw.response_complete,false);assert.equal(raw.provider_prompt_tokens,null);
 const record=rows(join(dir,'route-attribution.jsonl'))[0];assert.equal(record.returned_model,null);assert.equal(record.actual_route,options.requestModel);
 assert.ok(!JSON.stringify(record).includes('private endpoint'));
});
test('guard and expected-image rules are byte-for-byte parent copies except observer import',()=>{
 for(const [parent,child] of [['dsh_wire_image_guard_capacity1.mjs','dsh_wire_image_guard_routes1.mjs'],['dsh_wire_expectations.mjs','dsh_wire_expectations_routes1.mjs']]){
  const expected=readFileSync(new URL('../scripts/'+parent,import.meta.url),'utf8').replace("'./dsh_raw_usage_observer.mjs'","'./dsh_returned_model_routes1.mjs'");
  assert.equal(readFileSync(new URL('../scripts/'+child,import.meta.url),'utf8'),expected);
 }
});

test('independent route guard blocks changed model/endpoint before network and preserves allowed body',async()=>{
 const {guardedFetch}=await import('../scripts/dsh_route_guard_routes1.mjs');let calls=0,last;
 const fetch=guardedFetch(async(input,init)=>{calls++;last=init.body;return new Response('ok');},{actualRoute:'selected/route',baseUrl:'http://localhost:9999/v1'});
 const init={method:'POST',body:JSON.stringify({model:'selected/route',messages:[{role:'user',content:'unchanged'}]})};
 assert.equal(await (await fetch('http://localhost:9999/v1/chat/completions',init)).text(),'ok');
 assert.equal(last,init.body);assert.equal(calls,1);
 await assert.rejects(fetch('http://localhost:9999/v1/chat/completions',{...init,body:JSON.stringify({model:'other'})}),{name:'RouteBindingError'});
 await assert.rejects(fetch('http://other.test/v1/chat/completions',init),{name:'RouteBindingError'});
 assert.equal(calls,1);
});
