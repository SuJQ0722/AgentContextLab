import assert from 'node:assert/strict';
import {test} from 'node:test';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {Context} from '../deepseekHarness/vendor/cordis/lib/index.js';
import LlmRuntime,{LlmAdapter,createMessage,createUserMessage,createToolResultMessage} from '../deepseekHarness/packages/llm/llm/lib/index.js';
import {Session} from '../deepseekHarness/packages/core/session/lib/index.js';
import ProjectionRegistry from '../deepseekHarness/packages/session/session-projection/lib/index.js';
import TokenMeter from '../deepseekHarness/packages/llm/token-meter/lib/index.js';
import {toHermesMessages,fromHermesMessages,replaceSurface,sharedPolicyProjection} from '../plugins/dsh-context/shared-surface.mjs';
import {apply,latestProviderUsage} from '../plugins/dsh-context/hermes-policy-v3.mjs';

function buildSession(rounds=12,longArgs=false){
 const s=Session.create('shared-fixture',undefined,undefined,undefined,[sharedPolicyProjection]);s.append('turn/start',{turn:1});
 s.append('system/message',{turn:1,step:0,message:createMessage({role:'system',source:{kind:'system-prompt'},content:[{type:'text',text:'Fixture system.'}]})},{surfaceOp:'append'});
 s.append('user/message',createUserMessage({source:{kind:'user'},content:[{type:'text',text:'Recall code7319 and compare records.'}]}),{surfaceOp:'append'});
 s.append('request/header',{header:{config:{provider:'test',model:'test'}},reason:'initial'});
 for(let i=0;i<rounds;i++){
  s.append('step/start',{turn:1,step:i+1});
  const msg=createMessage({role:'assistant',source:{kind:'model',provider:'test',model:'test'},content:[{type:'tool-call',id:'call'+i,name:'web_search',arguments:JSON.stringify({query:longArgs&&i===0?'record'.repeat(150):'record'})}]});
  s.append('assistant/message',{turn:1,step:i+1,message:msg,stream:[],usage:{inputTokens:39000,cacheReadTokens:1000,outputTokens:10,totalTokens:40010}},{surfaceOp:'append'});
  s.append('tool/result',{turn:1,step:i+1,message:createToolResultMessage({callId:'call'+i,content:[{type:'text',text:('Fact '+i+' code7319. ').repeat(600)}],isError:false})},{surfaceOp:'append'});
  s.append('step/end',{turn:1,step:i+1});
 }
 return s;
}

test('native multi-role replacement preserves tool pairing, replays, and does not double-count usage',async()=>{
 const s=buildSession(2),before=s.snapshotEvents().filter(e=>e.data.usage).length;
 const originals=s.deriveMessages(),canonical=await toHermesMessages(originals,{});
 const changed=structuredClone(canonical);changed.at(-1).content=[{type:'text',text:'Shortened result.'}];
 const result=await fromHermesMessages(changed,originals,canonical,{}, {provider:'test',model:'test'});
 replaceSurface(s,result.messages,{provider:'test',model:'test'},{turn:1,step:3,expectedNodes:[...s.surface.nodes],origins:result.origins});
 assert.deepEqual(s.deriveMessages().map(m=>m.role),['system','user','assistant','tool','assistant','tool']);
 assert.equal(s.deriveMessages().at(-1).content[0].text,'Shortened result.');
 assert.equal(s.snapshotEvents().filter(e=>e.data.usage).length,before);
 const replay=Session.create('replayed',s.snapshotEvents(),undefined,undefined,[sharedPolicyProjection]);
 assert.deepEqual(replay.deriveMessages(),s.deriveMessages());
 assert.equal(latestProviderUsage(s).usage.prompt_tokens,40000);
});

test('invalid multi-role output is rejected in preflight without partial live mutation',()=>{
 const s=buildSession(1),before=s.snapshotEvents().length,m=[...s.deriveMessages()];
 m[3]={...m[3],toolCallId:'mismatch'};
 assert.throws(()=>replaceSurface(s,m,{provider:'test',model:'test'},{turn:1,step:2,expectedNodes:[...s.surface.nodes]}),/mismatch/);
 assert.equal(s.snapshotEvents().length,before);
});

class Adapter extends LlmAdapter{
 constructor(){super();this.calls=[];}
 async resolveModel(provider,model){return {provider,id:model,name:model,context:{contextWindow:131072}};}
 async *stream(options){this.calls.push(options);yield {type:'block-start',index:0,blockType:'text'};yield {type:'block-end',index:0,block:{type:'text',text:'## Active Task\nRecall code7319.\n## Critical Context\nFixture facts retained.'}};yield {type:'usage',usage:{inputTokens:100,outputTokens:20,totalTokens:120}};yield {type:'finish',reason:{kind:'stop'}};}
}
for(const [dsh,strategy] of [['none','none'],['discard','discard'],['sliding_window_native','sliding_window'],['summarize','summarize'],['visual_native','visual']]){
 test(`shared ${strategy} executes actual Hermes policy with native replayable roles`,async()=>{
  const directory=await mkdtemp(join(tmpdir(),'acl-shared-policy-')),ctx=new Context();
  new LlmRuntime(ctx);new ProjectionRegistry(ctx);new TokenMeter(ctx);const adapter=new Adapter();ctx.llm.registerAdapter(['test'],adapter);
  const imageBytes=new Map();ctx.provide('attachments');ctx.set('attachments',{async saveImages(images){return images.map((x,i)=>{const id='test:'+i;imageBytes.set(id,x.data);return {attachmentId:id,mediaType:x.mediaType,width:1000,height:1000,bytes:x.data.length};});},async readImage(ref){return {ref,data:imageBytes.get(ref.attachmentId)};}});
  let Engine;apply({plugin(e){Engine=e;}},{strategy:dsh,python:process.env.ACL_PYTHON||'python',sharedPolicy:fileURLToPath(new URL('../scripts/shared_context_policy.py',import.meta.url)),metricsDir:directory,policyConfig:{model:'test',provider:'custom',api_mode:'chat_completions',context_length:131072,threshold_tokens:32768,strategy_config:{save_dir:directory,font_size:16,history_scale:1,keep_rounds:strategy==='discard'?0:1,window_size:5}}});
  try{
   const engine=new Engine(ctx),s=buildSession(12,strategy==='summarize');const before=await toHermesMessages(s.deriveMessages(),ctx.attachments);
   await engine.run({session:s,options:{provider:'test',model:'test'}},new AbortController().signal,{turn:1,step:13});
   const after=s.deriveMessages();assert.ok(after.length);
   assert.deepEqual(Session.create('restored',s.snapshotEvents(),undefined,undefined,[sharedPolicyProjection]).deriveMessages(),after);
   if(strategy==='none')assert.deepEqual(await toHermesMessages(after,ctx.attachments),before);
   if(strategy==='sliding_window'){assert.equal(after.filter(m=>JSON.stringify(m.content).includes('tool response omitted')).length,6);assert.deepEqual(after.filter(m=>m.role==='tool').slice(-5),s.snapshotEvents().filter(e=>e.type==='tool/result'&&e.surfaceOp==='append').slice(-5).map(e=>e.data.message));}
   if(strategy==='summarize'){assert.ok(s.snapshotEvents().some(e=>e.type==='acl/hermes-policy-projection'));assert.equal(adapter.calls.length,1);assert.match(JSON.stringify(adapter.calls[0].messages),/structured checkpoint summary/);assert.ok(after.some(m=>JSON.stringify(m.content).includes('CONTEXT COMPACTION')));}
   if(strategy==='visual')assert.ok(after.some(m=>m.content.some(b=>b.type==='image')));
  }finally{await ctx.fiber.dispose();await rm(directory,{recursive:true,force:true});}
 });
}

test('latest usage never falls back to an older reported prompt after a missing-usage response',()=>{
 const s=buildSession(1);s.append('step/start',{turn:1,step:2});
 s.append('assistant/message',{turn:1,step:2,message:createMessage({role:'assistant',source:{kind:'model',provider:'test',model:'test'},content:[{type:'text',text:'No usage emitted.'}]}),stream:[]},{surfaceOp:'append'});
 assert.equal(latestProviderUsage(s).usage,null);
});

test('pure text canonical messages preserve Hermes string semantics for pruning and summary prompts',async()=>{
 const s=buildSession(1),canonical=await toHermesMessages(s.deriveMessages(),{});
 assert.equal(typeof canonical.find(m=>m.role==='tool').content,'string');
 assert.equal(canonical.find(m=>m.role==='tool').content,s.deriveMessages().find(m=>m.role==='tool').content[0].text);
 assert.equal(typeof canonical.find(m=>m.role==='user').content,'string');
});


test('assistant summary checkpoint uses recorded auxiliary identity and replays without model usage duplication',async()=>{
 const s=buildSession(2),old=s.deriveMessages(),canonical=await toHermesMessages(old,{});
 const selected=[canonical[0],canonical[1],{role:'assistant',content:'Recorded auxiliary summary.'}];
 const converted=await fromHermesMessages(selected,old,canonical,{}, {provider:'test',model:'test'});
 const before=s.snapshotEvents().filter(e=>e.data.usage).length;
 replaceSurface(s,converted.messages,{provider:'test',model:'test'},{turn:1,step:3,expectedNodes:[...s.surface.nodes],origins:converted.origins,summaryCallId:'real-auxiliary-call-fixture'});
 assert.equal(s.deriveMessages().at(-1).role,'assistant');
 assert.equal(s.snapshotEvents().filter(e=>e.data.usage).length,before);
 assert.deepEqual(Session.create('restored-summary',s.snapshotEvents(),undefined,undefined,[sharedPolicyProjection]).deriveMessages(),s.deriveMessages());
});
