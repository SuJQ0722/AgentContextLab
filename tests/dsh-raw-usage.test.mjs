import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {analyzeRawUsage,observeUsageResponse,flushUsageObservers,latestRawUsage,recordUsageTransportFailure} from '../scripts/dsh_raw_usage_observer.mjs';
const encoder=new TextEncoder();

test('missing cached fields stay unknown; explicit zero, aliases and conservation are distinguished',()=>{
 const base={prompt_tokens:100,completion_tokens:7,total_tokens:107};
 const missing=analyzeRawUsage(base);
 assert.equal(missing.provider_prompt_tokens,100);assert.equal(missing.cached_input_presence,false);
 assert.equal(missing.cached_input_tokens,null);assert.equal(missing.noncache_input_tokens,null);
 const zero=analyzeRawUsage({...base,prompt_tokens_details:{cached_tokens:0}});
 assert.equal(zero.cached_input_presence,true);assert.equal(zero.cached_input_tokens,0);assert.equal(zero.noncache_input_tokens,100);
 const ds=analyzeRawUsage({...base,prompt_cache_hit_tokens:60,prompt_cache_miss_tokens:40});
 assert.equal(ds.cached_input_tokens,60);assert.equal(ds.noncache_input_tokens,40);assert.equal(ds.conservation.valid,true);
 for(const invalid of [{prompt_cache_hit_tokens:110},{prompt_cache_hit_tokens:60,prompt_cache_miss_tokens:30},{prompt_cache_hit_tokens:60,cached_tokens:50},{cached_tokens:'0'},{total_tokens:108}]){
  const result=analyzeRawUsage({...base,...invalid});assert.equal(result.conservation.valid,false);assert.equal(result.cached_input_tokens,null);
 }
});

test('nonstream observer preserves original bytes and logs only raw usage metadata',async()=>{
 const folder=await mkdtemp(join(tmpdir(),'raw-usage-'));try{
  const ledgerPath=join(folder,'raw.jsonl');const body=JSON.stringify({choices:[{message:{content:'PRIVATE RESPONSE TEXT'}}],usage:{prompt_tokens:9,completion_tokens:2,total_tokens:11,prompt_tokens_details:{cached_tokens:0},unrelated_string:'SECRET'}});
  const response=new Response(body,{headers:{'content-type':'application/json'}});
  const observing=observeUsageResponse(response,{ledgerPath,requestId:'json-1',sessionId:'json-session',purpose:'agent'});
  assert.equal(await response.text(),body);const record=await observing;
  assert.equal(record.observation_status,'complete');assert.equal(record.cached_input_tokens,0);
  const log=await readFile(ledgerPath,'utf8');assert.equal(log.includes('PRIVATE'),false);assert.equal(log.includes('SECRET'),false);
  assert.equal(log.trim().split('\n').length,2);
 }finally{await rm(folder,{recursive:true,force:true});}
});

test('SSE chunk boundaries, final usage, missing cache and [DONE] preserve SDK stream',async()=>{
 const text=': comment\r\ndata: '+JSON.stringify({choices:[{delta:{content:'PRIVATE'}}]})+'\r\n\r\ndata: '+JSON.stringify({choices:[],usage:{prompt_tokens:13,completion_tokens:4,total_tokens:17}})+'\n\ndata: [DONE]\n\n';
 const chunks=[text.slice(0,7),text.slice(7,31),text.slice(31,119),text.slice(119)];
 const response=new Response(new ReadableStream({start(c){for(const chunk of chunks)c.enqueue(encoder.encode(chunk));c.close();}}),{headers:{'content-type':'text/event-stream'}});
 const observing=observeUsageResponse(response,{requestId:'sse-1',sessionId:'sse-session',purpose:'agent'});
 assert.equal(await response.text(),text);const record=await observing;
 assert.equal(record.sse_done,true);assert.equal(record.usage_events,1);assert.equal(record.provider_prompt_tokens,13);
 assert.equal(record.cached_input_presence,false);assert.equal(record.cached_input_tokens,null);
 const flushed=await flushUsageObservers({sessionId:'sse-session',purpose:'agent'});assert.equal(flushed.pending.length,0);
 assert.equal(latestRawUsage({sessionId:'sse-session',purpose:'agent'}).request_id,'sse-1');
});

test('EOF without terminal usage is incomplete, not fabricated zero usage',async()=>{
 const body='data: {"choices":[{"delta":{"content":"text"}}]}\n\n';
 const response=new Response(body,{headers:{'content-type':'text/event-stream'}});
 const record=await observeUsageResponse(response,{requestId:'eof',sessionId:'eof-session',purpose:'agent'});
 assert.equal(record.observation_status,'eof_without_done');assert.equal(record.response_complete,false);assert.equal(record.raw_provider_usage,null);assert.equal(record.provider_prompt_tokens,null);
});

test('SSE interruption preserves observed partial usage and leaves SDK error unchanged',async()=>{
 let controller;
 const source=new ReadableStream({start(c){controller=c;c.enqueue(encoder.encode('data: {"usage":{"prompt_tokens":22}}\n\n'));}});
 const response=new Response(source,{headers:{'content-type':'text/event-stream'}});
 const observing=observeUsageResponse(response,{requestId:'abort',sessionId:'abort-session',purpose:'agent'});
 const originalReader=response.body.getReader();assert.equal((await originalReader.read()).done,false);
 await new Promise(r=>setTimeout(r,20));controller.error(new Error('source broke'));
 await assert.rejects(originalReader.read(),/source broke/);
 const record=await observing;assert.equal(record.observation_status,'observer_interrupted');assert.equal(record.response_complete,false);
 assert.equal(record.provider_prompt_tokens,22);assert.equal(record.cached_input_tokens,null);
});

test('flush pending does not substitute previous response; transport failures carry missing usage',async()=>{
 let controller;
 const response=new Response(new ReadableStream({start(c){controller=c;}}),{headers:{'content-type':'text/event-stream'}});
 const observing=observeUsageResponse(response,{requestId:'pending',sessionId:'pending-session',purpose:'agent'});
 const flushed=await flushUsageObservers({sessionId:'pending-session',purpose:'agent',timeoutMs:5});assert.deepEqual(flushed.pending,['pending']);
 controller.enqueue(encoder.encode('data: [DONE]\n\n'));controller.close();await observing;
 const failed=recordUsageTransportFailure({requestId:'failed',sessionId:'pending-session',purpose:'agent'},new TypeError('must not persist error text'));
 assert.equal(failed.error_type,'TypeError');assert.equal(failed.provider_prompt_tokens,null);assert.equal(failed.response_complete,false);
 assert.equal(latestRawUsage({sessionId:'pending-session',purpose:'agent'}).request_id,'failed');
});
