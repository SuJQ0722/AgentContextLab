import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {Context} from '../deepseekHarness/vendor/cordis/lib/index.js';
import LlmRuntime,{LlmAdapter,createUserMessage} from '../deepseekHarness/packages/llm/llm/lib/index.js';
import {resolveProfiles} from '../deepseekHarness/packages/llm/llm-pi-ai/src/config.ts';
import {apply} from '../scripts/dsh_wire_expectations_v9.mjs';

function freeze(value){if(value&&typeof value==='object'&&!Object.isFrozen(value)){Object.values(value).forEach(freeze);Object.freeze(value);}return value;}
function messages(count){return Array.from({length:count},(_,i)=>createUserMessage({source:{kind:'user'},content:[{type:'text',text:`text ${i}`},{type:'image',attachment:{attachmentId:'sha256:'+i.toString(16).padStart(64,'0'),mediaType:'image/png'},aclImageDetail:'high'}]}));}
async function fixture(count,consumeEarly=false){
 const root=await mkdtemp(join(tmpdir(),'acl-readonly-'));const old=process.env.ACL_INLINE_DSH_RETAIN_IMAGES;process.env.ACL_INLINE_DSH_RETAIN_IMAGES='10';
 const ctx=new Context();new LlmRuntime(ctx);let adapterCalls=0,middlewareCalls=0,closed=false,seen;
 class Adapter extends LlmAdapter{async *stream(options){adapterCalls++;seen=options;try{yield {type:'text-delta',text:'first'};yield {type:'text-delta',text:'second'};}finally{closed=true;}}}
 ctx.llm.registerAdapter(['fixture'],new Adapter());
 // Model the real upstream middleware that freezes GenerateOptions.
 ctx.on('llm/stream',async function*(options,next){middlewareCalls++;freeze(options);yield* next();});
 const expectedFile=join(root,'expected.json');apply(ctx,{expectedFile});
 const original=freeze({provider:'fixture',model:'fixture-model',messages:messages(count),sessionId:'fixture-session',purpose:'agent'}),before=JSON.stringify(original);
 try{
  const chunks=[];for await(const chunk of ctx.llm.stream(original)){chunks.push(chunk);if(consumeEarly)break;}
  assert.equal(adapterCalls,1);assert.equal(middlewareCalls,count>10?2:1);assert.equal(closed,true);
  assert.equal(JSON.stringify(original),before);assert.equal(original.messages.length,count);
  const nativeImages=seen.messages.flatMap(m=>m.content.filter(p=>p.type==='image'));
  assert.equal(nativeImages.length,Math.min(10,count));
  const expected=JSON.parse(await readFile(expectedFile));assert.deepEqual(expected.wire_sha256,nativeImages.map(p=>p.attachment.attachmentId.slice(7)));
  assert.equal(expected.pre_sdk_retention.removed.length,Math.max(0,count-10));
  assert.equal((await readFile(expectedFile+'.jsonl','utf8')).trim().split('\n').length,1);
  assert.equal(chunks.length,consumeEarly?1:2);
 }finally{if(old===undefined)delete process.env.ACL_INLINE_DSH_RETAIN_IMAGES;else process.env.ACL_INLINE_DSH_RETAIN_IMAGES=old;await rm(root,{recursive:true,force:true});}
}
test('pinned real LlmRuntime receives deeply frozen 14-image options and redispatches once',async()=>fixture(14));
test('frozen <=10 image requests are a single-pass no-op',async()=>{await fixture(10);await fixture(0);});
test('early stream cancellation closes the redispatched native adapter',async()=>fixture(14,true));
test('native pi-ai profile resolves one-hour request and no provider retry',()=>{
 const profile=resolveProfiles({tokenhub:{apiKeyEnv:'TOKENHUB_API_KEY',api:'openai-completions',baseURL:'http://fixture/v1',timeoutMs:3600000,streamIdleTimeoutMs:3600000,retryPolicy:{mode:'normal',maxRetries:0},models:[{id:'deepseek-v4.1-flash-1017/huoshan/huoshan',input:['text','image'],contextWindow:131072,maxTokens:8192}]}}).get('tokenhub');
 assert.equal(profile.timeoutMs,3600000);assert.equal(profile.retryPolicy.maxRetries,0);
});
