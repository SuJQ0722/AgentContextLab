import test from 'node:test';
import assert from 'node:assert/strict';
import {SSECompletion} from '../scripts/sse_completion.mjs';
import {guardedFetch,ROUTES} from '../scripts/dsh_hosted_wire_v4.mjs';
const usage='data: {"usage":{"prompt_tokens":7,"completion_tokens":3,"total_tokens":10}}\n\n';
const done='data: [DONE]\n\n';
test('all boundaries, huge following chunk, quoted DONE and multiline data',()=>{
 for(const nl of ['\n','\r\n','\r']){
  const prefix=`data: {"text":"data: [DONE]"}${nl}${nl}`,terminal=`data: [DONE]${nl}${nl}`;
  const bytes=Buffer.from(prefix+terminal+'garbage'.repeat(100));
  for(let i=0;i<=bytes.length;i++){
   const parser=new SSECompletion();parser.feed(bytes.subarray(0,i));parser.feed(bytes.subarray(i));
   assert.equal(parser.done,true);assert.ok((nl==='\r\n'?[Buffer.byteLength(prefix+terminal),Buffer.byteLength(prefix+terminal)-1]:[Buffer.byteLength(prefix+terminal)]).includes(parser.doneOffset));
  }
  const parser=new SSECompletion();parser.feed(Buffer.from(prefix));assert.equal(parser.done,false);
 }
 const parser=new SSECompletion();parser.feed(Buffer.from('data: [DONE]\ndata: extra\n\n'));assert.equal(parser.done,false);
});
function fixture(original,rows){return guardedFetch({original,transform:async wire=>({wire,ledger:{hosting_calls:0}}),endpoint:'http://fixture/v1/chat/completions',emit:x=>rows.push(x),initialRouteIndex:0,timeoutMs:1000,deadlineMs:10000});}
const request={method:'POST',body:JSON.stringify({model:ROUTES[0],messages:[],stream:true})};
test('DONE closes a response whose connection never ends, keeps usage',async()=>{
 const rows=[];let cancelled=false;
 const fetch=fixture(async()=>new Response(new ReadableStream({start(c){c.enqueue(Buffer.from(usage+done+' '.repeat(500)));},cancel(){cancelled=true;}}),{headers:{'content-type':'text/event-stream'}}),rows);
 const started=performance.now();const result=await fetch('http://fixture/v1/chat/completions',request);
 assert.ok(performance.now()-started<500);assert.equal(cancelled,true);assert.equal(await result.text(),usage+done);
 const completed=rows.find(x=>x.event==='stream_complete');assert.equal(completed.completion_evidence,'sse_done');assert.equal(completed.raw_provider_usage.total_tokens,10);
});
test('truncated SSE rotates routes and never concatenates a partial answer',async()=>{
 const rows=[];let calls=0;
 const fetch=fixture(async()=>new Response(++calls===1?usage+'data: {"text":"BAD"}\n\n':'data: {"text":"GOOD"}\n\n'+done,{headers:{'content-type':'text/event-stream'}}),rows);
 const result=await fetch('http://fixture/v1/chat/completions',request);
 assert.equal(calls,2);assert.ok(!(await result.text()).includes('BAD'));
 const failed=rows.find(x=>x.event==='route_transport_error');assert.ok(failed.cause_codes.includes('ACL_INCOMPLETE_SSE'));assert.equal(failed.raw_provider_usage.total_tokens,10);
});

test('real local HTTP SSE ends before an unclosed chunked connection',async()=>{
 const {createServer}=await import('node:http');
 const server=createServer(async(req,res)=>{
  for await(const part of req){};
  res.writeHead(200,{'content-type':'text/event-stream'});res.write(usage+done);
  // No res.end(): terminal SSE is independent of HTTP EOF.
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const endpoint=`http://127.0.0.1:${server.address().port}/v1/chat/completions`,rows=[];
 const run=guardedFetch({original:globalThis.fetch,transform:async wire=>({wire,ledger:{hosting_calls:0}}),endpoint,emit:x=>rows.push(x),initialRouteIndex:0,timeoutMs:1000,deadlineMs:2000});
 try{
  const started=performance.now(),response=await run(endpoint,request);
  assert.equal(await response.text(),usage+done);assert.ok(performance.now()-started<1000);
  assert.equal(rows.filter(x=>x.event==='final_inline_request').length,1);
  assert.equal(rows.find(x=>x.event==='stream_complete').raw_provider_usage.total_tokens,10);
 }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
