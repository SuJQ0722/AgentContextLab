/** Local-only exact shared-policy/native-surface/actual-adapter visual comparison. */
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {createServer} from 'node:http';
import {Context} from '../deepseekHarness/vendor/cordis/lib/index.js';
import LlmRuntime from '../deepseekHarness/packages/llm/llm/lib/index.js';
import {Session} from '../deepseekHarness/packages/core/session/lib/index.js';
import ProjectionRegistry from '../deepseekHarness/packages/session/session-projection/lib/index.js';
import TokenMeter from '../deepseekHarness/packages/llm/token-meter/lib/index.js';
import LocalAttachmentStore from '../deepseekHarness/packages/attachment/attachment-local/lib/index.js';
import {PiAiAdapter} from '../deepseekHarness/packages/llm/llm-pi-ai/lib/index.js';
import {resolveProfiles} from '../deepseekHarness/packages/llm/llm-pi-ai/src/config.ts';
import {apply,invokePolicy} from '../plugins/dsh-context/hermes-policy-v3.mjs';
import {toHermesMessages,fromHermesMessages,sharedPolicyProjection} from '../plugins/dsh-context/shared-surface.mjs';
import {apply as expectedImages} from './dsh_wire_expectations.mjs';
const sha=b=>createHash('sha256').update(b).digest('hex');
const root=process.cwd(), out=resolve(process.argv[2]), fixture=resolve(process.argv[3]);
await mkdir(out,{recursive:true});
process.env.ACL_IMAGE_WIRE_APPLY_DETAILS='1';
process.env.ACL_IMAGE_WIRE_AUDIT_DIR=join(out,'wire');process.env.ACL_IMAGE_WIRE_EXPECTED=join(out,'expected.json');
await import('./dsh_wire_image_guard.mjs');
const ctx=new Context();new LlmRuntime(ctx);new ProjectionRegistry(ctx);new TokenMeter(ctx);
const attachments=new LocalAttachmentStore(ctx,{dshHome:join(out,'dsh-home'),normalizedImageMaxPixels:64000000,normalizedImageMaxDimension:65535,normalizedImageMaxBytes:50*1024*1024});
const wire=[];
const server=createServer(async(req,res)=>{
 const chunks=[];for await(const chunk of req)chunks.push(chunk);const body=JSON.parse(Buffer.concat(chunks).toString());
 const images=body.messages.flatMap(m=>Array.isArray(m.content)?m.content:[]).filter(p=>p.type==='image_url');
 wire.push({roles:body.messages.map(m=>m.role),image_details:images.map(p=>p.image_url.detail??null),image_sha256:images.map(p=>sha(Buffer.from(p.image_url.url.split(',')[1],'base64')))});
 res.writeHead(200,{'content-type':'text/event-stream'});
 const base={id:'shared-local',object:'chat.completion.chunk',created:1,model:body.model};
 for(const c of [{...base,choices:[{index:0,delta:{role:'assistant',content:'SHARED-WIRE-OK'},finish_reason:null}]},{...base,choices:[{index:0,delta:{},finish_reason:'stop'}],usage:{prompt_tokens:40000,completion_tokens:4,total_tokens:40004,prompt_tokens_details:{cached_tokens:0}}}])res.write('data: '+JSON.stringify(c)+'\n\n');res.end('data: [DONE]\n\n');
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
try{
 const model=process.env.ACL_MODEL,profiles=resolveProfiles({tokenhub:{api:'openai-completions',baseURL:`http://127.0.0.1:${server.address().port}/v1`,requestImagePixelBudget:64000000,requestImageMaxBytes:50*1024*1024,maxRequestImageBytes:20*1024*1024,models:[{id:model,input:['text','image'],contextWindow:131072,maxTokens:8192}]}});
 const auth={credentials:{read:async()=>undefined,list:async()=>[],modify:async()=>undefined,delete:async()=>{}},authContext:{env:async()=>undefined,fileExists:async()=>false}};
 ctx.llm.registerAdapter(['tokenhub'],new PiAiAdapter({profiles:()=>profiles,resolveApiKey:async()=> 'fixture-only',auth,resolveAttachments:()=>attachments}));
 expectedImages(ctx,{expectedFile:join(out,'expected.json')});
 const source=JSON.parse(await readFile(join(fixture,'messages.json'),'utf8'));
 for(const m of source){
  if(m.content?._multimodal)m.content=m.content.content;
  if(Array.isArray(m.content))for(const b of m.content)if(b.type==='image_url'){
   const url=b.image_url.url;if(!url.startsWith('data:'))b.image_url.url='data:image/png;base64,'+(await readFile(url)).toString('base64');
  }
 }
 const route={provider:'tokenhub',model};
 const admitted=await fromHermesMessages(source,[],[],attachments,route,join(out,'input-images'));
 const session=Session.create('shared-visual-matched',undefined,undefined,undefined,[sharedPolicyProjection]);session.append('turn/start',{turn:1});
 session.append('request/header',{header:{config:route},reason:'initial'});
 let step=0,open=false;
 for(const message of admitted.messages){
  if(message.role==='assistant'){
   if(open)session.append('step/end',{turn:1,step});step++;open=true;session.append('step/start',{turn:1,step});
   session.append('assistant/message',{turn:1,step,message,stream:[],usage:{inputTokens:40000,outputTokens:10,totalTokens:40010}},{surfaceOp:'append'});
  }else if(message.role==='user')session.append('user/message',message,{surfaceOp:'append'});
  else if(message.role==='tool')session.append('tool/result',{turn:1,step,message},{surfaceOp:'append'});
 }
 if(open)session.append('step/end',{turn:1,step});
 const canonical=await toHermesMessages(session.deriveMessages(),attachments);
 const config={strategy:'visual_native',python:process.env.ACL_PYTHON,sharedPolicy:join(root,'scripts/shared_context_policy.py'),metricsDir:join(out,'metrics'),policyConfig:{model,provider:'custom',api_mode:'chat_completions',context_length:131072,threshold_tokens:32768,strategy_config:{font_size:16,history_scale:1,keep_rounds:1,recent_rounds:5,save_dir:join(out,'hermes-canvas')}}};
 const direct=await invokePolicy(config,{operation:'apply',strategy:'visual',messages:canonical,config:config.policyConfig,provider_usage:{prompt_tokens:40000,completion_tokens:10}},new AbortController().signal);
 await writeFile(join(out,'direct-hermes-result.json'),JSON.stringify(direct));
 for await(const chunk of ctx.llm.stream({...route,messages:session.deriveMessages(),sessionId:session.id,maxTokens:16}))if(chunk.type==='finish'&&chunk.reason.kind!=='stop')throw new Error('Local raw usage setup failed');
 let Engine;apply({plugin(e){Engine=e;}},config);const engine=new Engine(ctx);
 await engine.run({session,options:route},new AbortController().signal,{turn:1,step:step+1});
 const final=session.deriveMessages();
 const directImageParts=direct.messages.flatMap(m=>Array.isArray(m.content)?m.content:[]).filter(b=>b.type==='image_url');
 const rawImages=directImageParts.map(b=>Buffer.from(b.image_url.url.split(',')[1],'base64'));
 const finalImages=[];for(const m of final)for(const b of m.content)if(b.type==='image')finalImages.push((await attachments.readImage(b.attachment)).data);
 if(JSON.stringify(rawImages.map(sha))!==JSON.stringify(finalImages.map(sha)))throw new Error('Native shared output canvas differs from direct Hermes');
 for await(const chunk of ctx.llm.stream({...route,messages:final,sessionId:session.id,purpose:'agent',maxTokens:16}))if(chunk.type==='finish'&&chunk.reason.kind!=='stop')throw new Error('Local wire call failed: '+JSON.stringify(chunk.reason));
 if(wire.length!==2||JSON.stringify(wire.at(-1).image_sha256)!==JSON.stringify(rawImages.map(sha)))throw new Error('Wire images differ from direct Hermes canvas');
 if(JSON.stringify(wire.at(-1).image_details)!==JSON.stringify(directImageParts.map(p=>p.image_url.detail??null)))throw new Error('Wire image details differ from Hermes');
 const replay=Session.create('shared-replay',session.snapshotEvents(),undefined,undefined,[sharedPolicyProjection]);
 if(JSON.stringify(replay.deriveMessages())!==JSON.stringify(final))throw new Error('Native replay changed policy surface');
 const docs=join(root,'docs/visual-integrity/repair-v3');await mkdir(docs,{recursive:true});
 await writeFile(join(docs,'hermes-matched.png'),rawImages[0]);await writeFile(join(docs,'dsh-matched.png'),finalImages[0]);
 const report={passed:true,paid_calls:0,network:'two localhost mock model calls (pre-compression raw usage, post-compression wire)',scope:'Same canonical multimodal fixture -> direct actual Hermes VisualEngine vs DSH native shared-policy durable span replacement -> actual pi-ai OpenAI HTTP adapter. The input includes actual crop/zoom handler results, stubbed local image_search transport, and18-row table. This is transport/render parity, not semantic benchmark accuracy.',source_fixture:fixture,provider_prompt_tokens_fixture:40000,canvas_sha256:rawImages.map(sha),canvas_count:rawImages.length,byte_identical_direct_hermes_native_and_wire:true,hermes_details:directImageParts.map(p=>p.image_url.detail??null),detail_policy_matches:true,native_roles:final.map(m=>m.role),wire,source_image_stats:direct.render_stats,native_replay_verified:true};
 await writeFile(join(out,'result.json'),JSON.stringify(report,null,2));await writeFile(join(docs,'matched-canvas-manifest.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify({out,passed:true,canvas_count:rawImages.length,canvas_sha256:report.canvas_sha256}));
}finally{await ctx.fiber.dispose();await new Promise(r=>server.close(r));}
