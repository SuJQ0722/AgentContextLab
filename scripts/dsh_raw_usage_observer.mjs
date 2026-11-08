/** Observe provider accounting before SDK zero defaults. Never replace/consume the original body. */
import {appendFileSync, mkdirSync} from 'node:fs';
import {dirname} from 'node:path';

const pending = new Map(), completed = new Map();
let sequence = 0;
const count = v => Number.isSafeInteger(v) && v >= 0;
const own = (o,k) => o != null && Object.hasOwn(o,k);
const at = (o,path) => path.split('.').reduce((v,k)=>v?.[k],o);
const has = (o,path) => {const keys=path.split('.'); const last=keys.pop(); return own(keys.reduce((v,k)=>v?.[k],o),last);};
// Usage contains counters, not response text. Retain numeric/null counter trees;
// discard unknown string metadata so the ledger cannot become a content log.
function safeUsage(value){
 if(value===null||typeof value==='number'||typeof value==='boolean')return value;
 if(!value||typeof value!=='object'||Array.isArray(value))return undefined;
 const result={};for(const [k,v] of Object.entries(value)){const safe=safeUsage(v);if(safe!==undefined)result[k]=safe;}return result;
}
function field(usage,paths){
 const present=paths.filter(p=>has(usage,p));
 const valid=present.filter(p=>count(at(usage,p)));
 const values=valid.map(p=>at(usage,p));
 const conflict=new Set(values).size>1;
 return {present:present.length>0,paths:present,value:valid.length===present.length&&values.length&&!conflict?values[0]:null,conflict,invalid:valid.length!==present.length};
}
export function analyzeRawUsage(raw){
 const u=raw&&typeof raw==='object'&&!Array.isArray(raw)?raw:null;
 const prompt=field(u,['prompt_tokens','input_tokens']);
 const cache=field(u,['prompt_tokens_details.cached_tokens','input_tokens_details.cached_tokens','prompt_cache_hit_tokens','cached_tokens']);
 const miss=field(u,['prompt_cache_miss_tokens']);
 const output=field(u,['completion_tokens','output_tokens']);
 const total=field(u,['total_tokens']);
 const write=field(u,['prompt_tokens_details.cache_write_tokens','cache_creation_input_tokens']);
 const errors=[];
 for(const [name,f] of Object.entries({prompt,cache,miss,output,total,write}))if(f.invalid||f.conflict)errors.push(name+(f.conflict?'_conflicting_aliases':'_invalid_count'));
 if(prompt.value!==null&&cache.value!==null&&cache.value>prompt.value)errors.push('cached_exceeds_prompt');
 if(prompt.value!==null&&cache.value!==null&&miss.value!==null&&cache.value+miss.value!==prompt.value)errors.push('cached_plus_noncache_differs_from_prompt');
 if(prompt.value!==null&&output.value!==null&&total.value!==null&&prompt.value+output.value!==total.value)errors.push('prompt_plus_output_differs_from_total');
 const coherent=errors.length===0;
 return {raw_provider_usage:u?safeUsage(u):null,raw_usage_storage:'Provider usage counter tree; non-counter strings omitted, response text never stored.',usage_present:!!u,
  provider_prompt_tokens:prompt.value,cached_input_presence:cache.present,cached_input_tokens:coherent?cache.value:null,
  cached_input_source_fields:cache.paths,noncache_input_tokens:coherent?(miss.value??(prompt.value!==null&&cache.value!==null?prompt.value-cache.value:null)):null,
  noncache_input_measurement:miss.value!==null?'provider_explicit':prompt.value!==null&&cache.value!==null?'provider_prompt_minus_cached':'missing_cache_split',
  output_tokens:output.value,total_tokens:total.value,cache_write_presence:write.present,cache_write_tokens:write.value,
  conservation:{checked_prompt_output_total:prompt.value!==null&&output.value!==null&&total.value!==null,
   checked_cache_split:prompt.value!==null&&cache.value!==null,valid:coherent,errors},
  accounting_note:'Non-cache means total input minus cache-read; cache-write is separately reported. Missing cache fields remain unknown, never zero.'};
}
function meta(options){return {version:'dsh-raw-provider-usage-v1',request_id:options.requestId??null,
 request_model:options.requestModel??null,session_id:options.sessionId??null,purpose:options.purpose??'unknown',
 observer_sequence:sequence++,timestamp:new Date().toISOString()};}
function persist(options,record){if(options.ledgerPath){mkdirSync(dirname(options.ledgerPath),{recursive:true});appendFileSync(options.ledgerPath,JSON.stringify(record)+'\n',{mode:0o600});}}
function finish(options,base,record){const final={...base,...record};try{persist(options,final);}catch{final.instrumentation_error='ledger_write_error';}completed.set(base.observer_sequence,final);return final;}
export function recordUsageTransportFailure(options,error){
 const base=meta(options);return finish(options,base,{...analyzeRawUsage(null),observation_status:'transport_error',response_complete:false,error_type:error?.name??'Error'});
}
/** Start immediately; caller returns original response without awaiting this promise. */
export function observeUsageResponse(response,options={}){
 const base=meta(options);
 const task=(async()=>{
  let raw=null,usageEvents=0,done=false,bytes=0,parseErrors=0,reader;
  const stream=(response.headers.get('content-type')??'').includes('text/event-stream');
  const accept=obj=>{const usage=obj?.usage??obj?.response?.usage??obj?.message?.usage;if(usage&&typeof usage==='object'&&!Array.isArray(usage)){raw=usage;usageEvents++;}};
  try{
   persist(options,{...base,event:'response_started',observation_status:'reading',http_status:response.status});
   reader=response.clone().body?.getReader();
   if(!reader)return finish(options,base,{...analyzeRawUsage(null),observation_status:'empty_body',response_complete:true,http_status:response.status});
   const decoder=new TextDecoder();let buffer='',eventData=[];
   const dispatch=()=>{if(!eventData.length)return;const data=eventData.join('\n');eventData=[];if(data==='[DONE]'){done=true;return;}try{accept(JSON.parse(data));}catch{parseErrors++;}};
   const line=text=>{if(text===''){dispatch();return;}if(text.startsWith('data:'))eventData.push(text.slice(5).replace(/^ /,''));};
   while(true){const next=await reader.read();if(next.done)break;bytes+=next.value.byteLength;
    if(bytes>(options.maxBytes??64*1024*1024))throw new Error('ObserverByteLimit');
    buffer+=decoder.decode(next.value,{stream:true});
    if(stream){let newline;while((newline=buffer.indexOf('\n'))>=0){line(buffer.slice(0,newline).replace(/\r$/,''));buffer=buffer.slice(newline+1);}if(buffer.length>8*1024*1024)throw new Error('ObserverEventLimit');}
   }
   buffer+=decoder.decode();
   if(stream){if(buffer)line(buffer.replace(/\r$/,''));dispatch();}else{try{accept(JSON.parse(buffer));}catch{parseErrors++;}}
   return finish(options,base,{...analyzeRawUsage(raw),observation_status:parseErrors?'parse_error':stream&&!done?'eof_without_done':'complete',
    response_complete:!parseErrors&&(!stream||done),http_status:response.status,stream,sse_done:stream?done:null,usage_events:usageEvents,parse_errors:parseErrors});
  }catch(error){
   // Cancel only the cloned branch. Do not await tee cancellation: it may wait
   // for the real SDK consumer and would make flushing deadlock.
   try{reader?.cancel().catch(()=>{});}catch{}
   return finish(options,base,{...analyzeRawUsage(raw),observation_status:'observer_interrupted',response_complete:false,http_status:response.status,
    stream,sse_done:stream?done:null,usage_events:usageEvents,parse_errors:parseErrors,error_type:error?.name??'Error'});
  }
 })().catch(error=>{const record={...base,...analyzeRawUsage(null),observation_status:'observer_write_error',response_complete:false,error_type:error?.name??'Error'};completed.set(base.observer_sequence,record);return record;});
 pending.set(base.observer_sequence,{base,task});task.finally(()=>pending.delete(base.observer_sequence));return task;
}
const matches=(record,options)=> (options.sessionId===undefined||record.session_id===options.sessionId)&&(options.purpose===undefined||record.purpose===options.purpose);
export function latestRawUsage(options={}){return [...completed.values()].filter(r=>matches(r,options)).sort((a,b)=>b.observer_sequence-a.observer_sequence)[0]??null;}
export async function flushUsageObservers(options={}){
 const selected=[...pending.values()].filter(p=>matches(p.base,options));let timer;
 if(selected.length)await Promise.race([Promise.all(selected.map(p=>p.task)),new Promise(resolve=>{timer=setTimeout(resolve,options.timeoutMs??5000);})]);
 clearTimeout(timer);return {records:[...completed.values()].filter(r=>matches(r,options)),pending:[...pending.values()].filter(p=>matches(p.base,options)).map(p=>p.base.request_id)};
}
