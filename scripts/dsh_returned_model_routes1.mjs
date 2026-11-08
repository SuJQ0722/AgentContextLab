/** routes1 attribution only. Original observer remains the sole usage authority. */
import {observeUsageResponse as originalObserve,recordUsageTransportFailure as originalFailure,
 flushUsageObservers as originalFlush,latestRawUsage,analyzeRawUsage} from './dsh_raw_usage_observer.mjs';
import {appendFileSync,mkdirSync,readFileSync} from 'node:fs';
import {dirname,join} from 'node:path';
import {performance} from 'node:perf_hooks';
export {latestRawUsage,analyzeRawUsage};
const pending=new Map();
function lineage(options){
 const path=options.routeLineagePath??process.env.ACL_ROUTE_LINEAGE_FILE;
 if(!path)return {lineage_present:false,logical_model:null,assigned_route:null,route_plan_sha256:null,generation:null};
 try{const x=JSON.parse(readFileSync(path,'utf8'));return {lineage_present:true,logical_model:x.logical_model??null,
  assigned_route:x.actual_route??null,route_plan_sha256:x.route_plan_sha256??null,
  parent_plan_sha256:x.parent_plan_sha256??null,generation:x.generation??x.runtime_route_version??x.runtime_version??'routes1'};}
 catch{return {lineage_present:false,lineage_error:'unreadable_route_lineage',logical_model:null,assigned_route:null,route_plan_sha256:null,generation:null};}
}
function persist(options,record){
 const path=options.routeLedgerPath??(options.ledgerPath?join(dirname(options.ledgerPath),'route-attribution.jsonl'):null);
 if(!path)return record;
 try{mkdirSync(dirname(path),{recursive:true});appendFileSync(path,JSON.stringify(record)+'\n',{mode:0o600});}
 catch{record.attribution_write_error=true;}
 return record;
}
async function returnedModel(response,options){
 const began=performance.now(),models=new Set();let present=false,parseErrors=0,done=false,bytes=0,reader;
 const stream=(response.headers.get('content-type')??'').includes('text/event-stream');
 const accept=value=>{for(const candidate of [value,value?.response,value?.message]){
  if(candidate&&Object.hasOwn(candidate,'model')){present=true;const m=candidate.model;if(typeof m==='string'&&m.length<=512&&!/[\r\n]/.test(m))models.add(m);}
 }};
 try{
  reader=response.clone().body?.getReader();if(!reader)return {returned_model:null,returned_model_presence:false,returned_models:[],model_observation_complete:true,response_observer_seconds:(performance.now()-began)/1000};
  const decoder=new TextDecoder();let buffer='',event=[];
  const dispatch=()=>{if(!event.length)return;const data=event.join('\n');event=[];if(data==='[DONE]'){done=true;return;}try{accept(JSON.parse(data));}catch{parseErrors++;}};
  const line=value=>{if(value===''){dispatch();return;}if(value.startsWith('data:'))event.push(value.slice(5).replace(/^ /,''));};
  while(true){const next=await reader.read();if(next.done)break;bytes+=next.value.byteLength;if(bytes>(options.maxBytes??64*1024*1024))throw new Error('AttributionByteLimit');
   buffer+=decoder.decode(next.value,{stream:true});
   if(stream){let i;while((i=buffer.indexOf('\n'))>=0){line(buffer.slice(0,i).replace(/\r$/,''));buffer=buffer.slice(i+1);}if(buffer.length>8*1024*1024)throw new Error('AttributionEventLimit');}
  }
  buffer+=decoder.decode();if(stream){if(buffer)line(buffer.replace(/\r$/,''));dispatch();}else{try{accept(JSON.parse(buffer));}catch{parseErrors++;}}
  return {returned_model:models.size===1?[...models][0]:null,returned_models:[...models],returned_model_presence:present,
   returned_model_conflict:models.size>1,model_observation_complete:parseErrors===0&&(!stream||done),
   model_parse_errors:parseErrors,response_observer_seconds:(performance.now()-began)/1000};
 }catch(error){try{reader?.cancel().catch(()=>{});}catch{}
  return {returned_model:models.size===1?[...models][0]:null,returned_models:[...models],returned_model_presence:present,
   model_observation_complete:false,model_error_type:error?.name??'Error',response_observer_seconds:(performance.now()-began)/1000};}
}
function attribution(options,usage,model){
 const context=lineage(options);
 return {version:'routes1-returned-model-v1',event:'final',request_id:options.requestId??null,
  actual_route:options.requestModel??null,session_id:options.sessionId??null,purpose:options.purpose??'unknown',timestamp:new Date().toISOString(),
  ...context,...model,route_matches_assignment:context.assigned_route===null?null:context.assigned_route===options.requestModel,
  returned_model_exactly_matches_request_alias:model.returned_model==null||options.requestModel==null?null:model.returned_model===options.requestModel,
  preflight_returned_model_observation:'deepseek-v4-1-flash-261017',
  returned_model_matches_preflight_observation:model.returned_model==null?null:model.returned_model==='deepseek-v4-1-flash-261017',
  backend_weights_equivalence_verified:null,
  cached_input_presence:usage.cached_input_presence??false,cache_value_known:usage.cached_input_tokens!=null,
  provider_prompt_known:usage.provider_prompt_tokens!=null,output_known:usage.output_tokens!=null,
  response_complete:usage.response_complete===true,http_status:usage.http_status??null,
  usage_authority:false,usage_source:options.ledgerPath??null,usage_join_key:'request_id',
  latency_note:'response_observer_seconds measures cloned response-body observation after headers, not full request or provider API latency; SDK latency remains in original calls.jsonl',
  provider_internal_latency_seconds:null};
}
export function observeUsageResponse(response,options={}){
 // Call the original observer directly: shared-policy imports this exact module's
 // state, so prompt-token triggers and missing-usage handling remain unchanged.
 const usage=originalObserve(response,options);const model=returnedModel(response,options);
 const task=Promise.all([usage,model]).then(([u,m])=>{persist(options,attribution(options,u,m));return u;});
 const id=options.requestId??Symbol();pending.set(id,{task,sessionId:options.sessionId,purpose:options.purpose});
 task.finally(()=>pending.delete(id));return task;
}
export function recordUsageTransportFailure(options,error){
 const usage=originalFailure(options,error);
 persist(options,attribution(options,usage,{returned_model:null,returned_models:[],returned_model_presence:false,
  model_observation_complete:false,response_observer_seconds:null,transport_error_type:error?.name??'Error'}));return usage;
}
export async function flushUsageObservers(options={}){
 const original=await originalFlush(options);let timer;
 const selected=[...pending.entries()].filter(([,x])=>(options.sessionId===undefined||options.sessionId===x.sessionId)&&
  (options.purpose===undefined||options.purpose===x.purpose));
 if(selected.length)await Promise.race([Promise.all(selected.map(([,x])=>x.task)),new Promise(r=>{timer=setTimeout(r,options.timeoutMs??5000);})]);
 clearTimeout(timer);
 return {...original,pending:[...new Set([...original.pending,...selected.filter(([id])=>pending.has(id)).map(([id])=>String(id))])]};
}
