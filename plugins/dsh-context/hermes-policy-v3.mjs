/** Exact Hermes policy bridge inside DSH's native loop; opt-in new-plan lineage. */
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile, rename, appendFile, unlink } from 'node:fs/promises';
import { join } from 'node:path';
import { CompactionEngine } from '../../deepseekHarness/packages/compaction/compaction/lib/index.js';
import { BlockAssembler } from '../../deepseekHarness/packages/llm/llm/lib/index.js';
import { toHermesMessages, fromHermesMessages, replaceSurface, sharedPolicyProjection } from './shared-surface.mjs';
import { invokeBridge } from '../dsh-local-web/hermes-tools-v2.mjs';
import {flushUsageObservers,latestRawUsage} from '../../scripts/dsh_raw_usage_observer.mjs';

export function invokePolicy(config, request, signal) {
  const started=performance.now();
  return new Promise((resolve,reject)=>{
    const child=spawn(config.python,[config.sharedPolicy],{stdio:['pipe','pipe','pipe'],signal});
    const chunks=[];let bytes=0;let timedOut=false;
    const timer=setTimeout(()=>{timedOut=true;child.kill('SIGTERM');},config.helperTimeoutMs??180000);
    child.stderr.resume();
    child.stdout.on('data',b=>{bytes+=b.length;if(bytes>256*1024*1024)child.kill('SIGTERM');else chunks.push(b);});
    child.stdin.on('error',()=>{});child.on('error',e=>{clearTimeout(timer);reject(e);});
    child.on('close',code=>{clearTimeout(timer);let parsed=null;try{parsed=JSON.parse(Buffer.concat(chunks).toString());}catch{}
      const ipc_seconds=(performance.now()-started)/1000;
      if(code!==0||timedOut){const error=new Error(`Shared Hermes policy failed (${timedOut?'timeout':code}); no silent fallback`);error.policy_result=parsed;error.policy_ipc_seconds=ipc_seconds;return reject(error);}
      if(!parsed)return reject(new Error('Shared Hermes policy returned invalid JSON'));
      resolve({...parsed,policy_ipc_seconds:ipc_seconds});});
    child.stdin.end(JSON.stringify(request));
  });
}
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
async function atomic(path,value){await writeFile(path+'.tmp',JSON.stringify(value),{mode:0o600});await rename(path+'.tmp',path);}
async function optional(path){try{return JSON.parse(await readFile(path,'utf8'));}catch(e){if(e.code==='ENOENT')return null;throw e;}}

/** Normalized DSH input excludes cached read/write; provider prompt includes both. */
export function latestProviderUsage(session){
  for(const event of [...session.snapshotEvents()].reverse()){
    if(event.type!=='assistant/message')continue;
    const u=event.data.usage;
    if(!u)return {seq:event.seq,usage:null,reason:'latest model response omitted usage; older usage is not reused'};
    const counts=[u.inputTokens,...['cacheReadTokens','cacheWriteTokens'].filter(k=>u[k]!==undefined).map(k=>u[k])];
    if(counts.some(v=>!Number.isFinite(v)||v<0))return {seq:event.seq,usage:null,reason:'invalid normalized input accounting'};
    // Pinned mapUsage drops cache fields only when pi-ai reports zero. This
    // reconstructs provider prompt size, not evidence of provider cache-field availability.
    return {seq:event.seq,usage:{prompt_tokens:u.inputTokens+(u.cacheReadTokens??0)+(u.cacheWriteTokens??0),completion_tokens:Number.isFinite(u.outputTokens)&&u.outputTokens>=0?u.outputTokens:null},reason:'pinned pi-ai normalized input plus cache read/write'};
  }
  return {seq:null,usage:null,reason:'no model response yet'};
}

export function apply(ctx,config){
  const map={none:'none',discard:'discard',summarize:'summarize',sliding_window_native:'sliding_window',visual_native:'visual'};
  const strategy=map[config.strategy];
  if(config.postCompressionBudget!==undefined)throw new Error('DSH-only postCompressionBudget is incompatible with strict shared Hermes policy; controlled baselines use a separate protocol');
  if(!strategy)throw new Error('Shared Hermes policy supports the five main strategies; controlled native-image baselines retain their separate policies');
  for(const key of ['python','sharedPolicy','metricsDir','policyConfig'])if(!config[key])throw new Error(`Shared Hermes policy requires ${key}`);
  class SharedHermesCompaction extends CompactionEngine{
    static inject=['llm','attachments','tokenMeter','sessions'];
    researchStrategy=config.strategy;
    constructor(context){
      super(context);
      if(context.get('sessions'))context.sessions.registerMessageProjection(sharedPolicyProjection);
      context.on('agent/pre-step',async({agent,turn,step,signal},next)=>{
        // A failure propagates and stops the request; it is never swallowed by BasicCompaction.
        await this.run(agent,signal,{turn,step});return next();
      });
    }
    async compactIfNeeded(agent,trigger,signal){
      if(trigger==='context-overflow')throw new Error('Provider overflow: shared Hermes policy will not substitute a different local-estimate compression rule');
      const events=agent.session.snapshotEvents();const start=[...events].reverse().find(e=>e.type==='turn/start');
      return this.run(agent,signal,{turn:start?.data.turn??0,step:0});
    }
    async compactNow(){throw new Error('Shared Hermes policy does not allow an unversioned manual compression override');}
    async compactRegion(){throw new Error('Shared Hermes policy owns the complete Hermes selection; arbitrary DSH regions are disabled');}
    async run(agent,signal,position){
      const session=agent.session;
      const folder=join(config.metricsDir,'shared-policy',String(session.id).replace(/[^A-Za-z0-9_.-]/g,'_'));
      await mkdir(folder,{recursive:true,mode:0o700});
      const pendingPath=join(folder,'pending.json'),statePath=join(folder,'state.json'),summaryPendingPath=join(folder,'pending-summary.json');
      let previousSummary=await optional(summaryPendingPath);
      if(previousSummary&&previousSummary.status!=='settled')throw new Error('Unsettled shared summary attempt; do not automatically retry a possibly billed call');
      if(await optional(pendingPath))throw new Error('Unfinished shared-policy surface transaction; inspect journal before explicit recovery');
      const saved=await optional(statePath);
      if(previousSummary&&saved?.completed_summary_id===previousSummary.response?.call_id){await unlink(summaryPendingPath);previousSummary=null;}
      const latest=latestProviderUsage(session);
      let rawUsage=null;
      if(process.env.ACL_IMAGE_WIRE_AUDIT_DIR&&latest.seq!==null){
        const flushed=await flushUsageObservers({sessionId:session.id,purpose:'agent',timeoutMs:5000});
        if(flushed.pending.length)throw new Error('Pending raw usage cannot be replaced by an older response');
        rawUsage=latestRawUsage({sessionId:session.id,purpose:'agent'});
        latest.usage=rawUsage?.response_complete&&rawUsage.conservation?.valid&&Number.isFinite(rawUsage.provider_prompt_tokens)
          ?{prompt_tokens:rawUsage.provider_prompt_tokens,completion_tokens:rawUsage.output_tokens}:null;
        latest.reason=latest.usage?'raw provider prompt_tokens; missing cache split remains unknown':'latest raw provider prompt usage unavailable';
      }
      const original=session.deriveMessages();
      if(original.length!==session.surface.nodes.length)throw new Error('Shared policy requires aligned visible surface nodes; dormant native nodes must be explicitly handled');
      if(saved&&saved.last_provider_usage_seq===latest.seq&&same(saved.surface_nodes,session.surface.nodes))return null;
      const canonical=await toHermesMessages(original,this.ctx.attachments,signal);
      let requestMessages=canonical;
      // Apply the actual Hermes per-turn aggregate tool budget before its compression policy.
      let budget=null;
      if(config.toolBridge){
        let last=-1;
        for(let i=canonical.length-1;i>=0;i--)if(canonical[i].role==='assistant'&&canonical[i].tool_calls?.length){last=i;break;}
        if(last>=0){
          const ids=new Set(canonical[last].tool_calls.map(c=>c.id));
          const indexes=canonical.map((m,i)=>m.role==='tool'&&i>last&&ids.has(m.tool_call_id)?i:-1).filter(i=>i>=0);
          if(indexes.length){
            budget=await invokeBridge({...config.toolBridge,python:config.python},{operation:'tool_budget',messages:indexes.map(i=>canonical[i]),context_length:config.policyConfig.context_length},signal);
            if(!Array.isArray(budget.messages)||budget.messages.length!==indexes.length)throw new Error('Hermes tool budget changed tool result count');
            requestMessages=structuredClone(canonical);indexes.forEach((index,i)=>{requestMessages[index]=budget.messages[i];});
          }
        }
      }
      const request={operation:'apply',strategy,messages:requestMessages,state:saved?.state??null,config:config.policyConfig,provider_usage:latest.usage};
      const policyInvocations=[];
      const callPolicy=async payload=>{
        try{const value=await invokePolicy(config,payload,signal);policyInvocations.push({policy_ipc_seconds:value.policy_ipc_seconds,...value.timings});return value;}
        catch(error){await appendFile(join(config.metricsDir,'shared-policy-errors.jsonl'),JSON.stringify({timestamp:new Date().toISOString(),session_id:session.id,strategy:config.strategy,policy_ipc_seconds:error.policy_ipc_seconds??null,timings:error.policy_result?.timings??null,error_type:error.name,error:error.policy_result?.error??error.message})+'\n');throw error;}
      };
      let result=await callPolicy(request),summaryStream=[],summaryCalls=[];
      const route=session.requestHeader()?.config??agent.options;
      if(!route?.provider||!route?.model){if(result.status==='awaiting_summary')throw new Error('No native route for shared summary');}
      if(result.status==='awaiting_summary'){
        const call=result.pending_call;if(call.model&&call.model!==route.model)throw new Error('Shared summary model differs from agent model');
        let response;
        if(previousSummary){
          if(previousSummary.response.request_sha256!==call.request_sha256||!same(previousSummary.source_nodes,session.surface.nodes))throw new Error('Settled summary journal no longer matches this policy input');
          response=previousSummary.response;summaryStream=previousSummary.stream;
          summaryCalls.push({...previousSummary.call,replayed_without_api:true});
        }else{
          const logicalId=randomUUID(),started=Date.now(),assembler=new BlockAssembler();
          await atomic(summaryPendingPath,{status:'started',logical_call_id:logicalId,source_nodes:[...session.surface.nodes],request:call,policy_request:request,started_at:new Date().toISOString()});
          try{
            for await(const chunk of this.ctx.llm.stream({provider:route.provider,model:route.model,
              messages:call.messages.map(m=>({role:m.role,content:typeof m.content==='string'?[{type:'text',text:m.content}]:m.content})),
              maxTokens:call.max_tokens,sessionId:session.id,purpose:'compaction',signal})){
              summaryStream.push({type:'chunk',time:Date.now(),chunk});assembler.push(chunk);
            }
          }catch(error){
            await atomic(summaryPendingPath,{status:'failed',logical_call_id:logicalId,source_nodes:[...session.surface.nodes],request:call,policy_request:request,stream:summaryStream,usage:assembler.usage??null,error_type:error?.name??'Error',client_seconds:(Date.now()-started)/1000});
            throw error;
          }
          const blocks=assembler.blocks(),content=blocks.filter(b=>b.type==='text').map(b=>b.text).join('');
          const error=['error','aborted'].includes(assembler.finish?.kind)?assembler.finish.kind:null;
          response={request_sha256:call.request_sha256,content,usage:assembler.usage??null,call_id:logicalId,...(error?{error}: {})};
          const callRecord={request:call,response,finish:assembler.finish,client_seconds:(Date.now()-started)/1000};
          await atomic(summaryPendingPath,{status:'settled',source_nodes:[...session.surface.nodes],request:call,policy_request:request,response,stream:summaryStream,call:callRecord});
          await atomic(join(folder,'summary-'+logicalId+'.json'),{...callRecord,stream:summaryStream});
          summaryCalls.push(callRecord);
        }
        result=await callPolicy({...request,state:result.state,summary_response:response});
        if(result.status==='awaiting_summary')throw new Error('Shared summary replay did not consume the recorded response');
      }
      const policyChanged=result.changed===true;
      const changed=policyChanged||!same(requestMessages,canonical);
      const record={version:'hermes-shared-context-v1',timestamp:new Date().toISOString(),session_id:session.id,
        strategy:config.strategy,hermes_strategy:strategy,status:result.status,provider_usage:latest.usage,
        provider_usage_seq:latest.seq,trigger_token_source:latest.reason,raw_provider_usage:rawUsage,
        cache_measurement:rawUsage?'raw provider presence fields; missing remains null':'normalized only; raw cache presence unknown',
        policy_invocations:policyInvocations,policy_ipc_seconds:policyInvocations.reduce((n,t)=>n+t.policy_ipc_seconds,0),
        render_seconds:policyInvocations.reduce((n,t)=>n+(t.renderer_seconds??0),0),
        compression_count_delta:(result.state?.engine?.compression_count??0)-(saved?.state?.engine?.compression_count??0),
        policy_config:config.policyConfig,tool_budget:budget,summary_calls:summaryCalls,render_stats:result.timings?.renderer_calls>0?result.render_stats??null:null};
      let committed=null;
      if(changed){
        const targetMessages=policyChanged?result.messages:requestMessages;
        const converted=await fromHermesMessages(targetMessages,original,canonical,this.ctx.attachments,route,join(folder,'raw-images'),signal);
        const callId=randomUUID();const expectedNodes=[...session.surface.nodes];
        const journal={...record,call_id:callId,input:canonical,output:targetMessages,
          converted_messages:converted.messages,image_ledger:converted.imageLedger,state:result.state,expected_nodes:expectedNodes};
        const journalPath=join(folder,callId+'.json');await atomic(journalPath,journal);
        await atomic(pendingPath,{journal:journalPath,expected_nodes:expectedNodes});
        committed=replaceSurface(session,converted.messages,route,{...position,expectedNodes,policyCallId:callId,summaryStream,
          origins:converted.origins,summaryCallId:summaryCalls.at(-1)?.response?.call_id,nodeTokens:Object.fromEntries(this.ctx.tokenMeter.measure(session).nodes.map(n=>[n.seq,n.tokens]))});
        record.compaction_id=callId;record.journal=journalPath;record.image_ledger=converted.imageLedger;
      }
      await atomic(statePath,{state:result.state,last_provider_usage_seq:latest.seq,surface_nodes:[...session.surface.nodes],completed_summary_id:summaryCalls.at(-1)?.response?.call_id??saved?.completed_summary_id??null});
      if(changed)await unlink(pendingPath);
      if(summaryCalls.length)await unlink(summaryPendingPath);
      // The common policy determines selection. This observational budget does not
      // silently re-compress, truncate, or add a DSH-only post-budget rejection.
      const measured=this.ctx.tokenMeter.measure(session).totalTokens;
      record.post_tokens_estimate=measured;record.budget=config.postCompressionBudget;
      record.budget_measurement='dsh local meter; policy trigger uses provider prompt usage';
      record.valid=true;
      await appendFile(join(config.metricsDir,'shared-policy.jsonl'),JSON.stringify(record)+'\n');
      return committed;
    }
  }
  ctx.plugin(SharedHermesCompaction,{});
}
