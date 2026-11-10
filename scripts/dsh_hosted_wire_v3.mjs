/** Direct inline images, exact four-route rotation, client transport telemetry. */
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {appendFileSync,mkdirSync} from 'node:fs';
import {dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash,randomUUID} from 'node:crypto';
import {AsyncLocalStorage} from 'node:async_hooks';
import {channel} from 'node:diagnostics_channel';
const sha=x=>createHash('sha256').update(x).digest('hex');
export const ROUTES=Object.freeze(['deepseek-v4.1-flash-1017/huoshan/huoshan','deepseek-v4.1-flash-1017/zijian/sfb','deepseek-v4.1-flash-1017/huoshan/sfc','deepseek-v4.1-flash-1017/zijian/sfc']);
const diagnosticContext=new AsyncLocalStorage(),diagnosticRequests=new WeakMap(),bodySentAttempts=new Set();
channel('undici:request:create').subscribe(({request})=>{const scope=diagnosticContext.getStore();if(scope&&request.method==='POST'){try{if(new URL(request.path,request.origin).href===scope.endpoint)diagnosticRequests.set(request,scope);}catch{}}});
channel('undici:request:bodySent').subscribe(({request})=>{const scope=diagnosticRequests.get(request);if(scope&&!bodySentAttempts.has(scope.id)){bodySentAttempts.add(scope.id);scope.emit({event:'request_body_sent',attempt_id:scope.id,actual_model:scope.model,client_seconds:(performance.now()-scope.started)/1000,measurement:'undici model POST request:bodySent; includes connection; client transport, not provider internal'});}});
export function safeError(error){
 const codes=[];let current=error;
 for(let depth=0;current&&depth<5;depth++,current=current.cause){
  if(typeof current.code==='string'&&/^[A-Z0-9_]{1,64}$/.test(current.code))codes.push(current.code);
  for(const child of current.errors||[])if(typeof child?.code==='string'&&/^[A-Z0-9_]{1,64}$/.test(child.code))codes.push(child.code);
 }
 return {error_type:error?.name||'Error',cause_codes:[...new Set(codes)]};
}
export function pythonBridge(python,root){
 let child;const pending=new Map();
 function start(){
  child=spawn(python,[fileURLToPath(new URL('./dsh_inline_transport_bridge_v1.py',import.meta.url)),'--canvas-root',root],{stdio:['pipe','pipe','ignore']});child.unref();
  createInterface({input:child.stdout}).on('line',line=>{
   try{const row=JSON.parse(line),entry=pending.get(row.id);if(!entry)return;pending.delete(row.id);clearTimeout(entry.timer);row.ok?entry.resolve(row):entry.reject(Error('Inline preparation '+row.error_type));if(!pending.size){child.stdin.unref();child.stdout.unref();}}
   catch{for(const e of pending.values()){clearTimeout(e.timer);e.reject(Error('Invalid bridge response'));}pending.clear();}
  });
  const fail=()=>{for(const e of pending.values()){clearTimeout(e.timer);e.reject(Error('Inline bridge stopped'));}pending.clear();};child.on('error',fail);child.on('exit',fail);
 }
 return body=>new Promise((resolve,reject)=>{
  if(!child)start();child.stdin.ref();child.stdout.ref();const id=randomUUID();const timer=setTimeout(()=>{pending.delete(id);child.kill('SIGTERM');reject(Error('Inline preparation deadline'));},120000);
  pending.set(id,{resolve,reject,timer});child.stdin.write(JSON.stringify({id,body})+'\n',err=>{if(err){clearTimeout(timer);pending.delete(id);reject(Error('Inline bridge input failed'));}});
 });
}
export function retryAfterMs(headers,now=Date.now()){
 const value=headers.get('retry-after');
 if(value!==null&&/^\d+(?:\.\d+)?$/.test(value.trim()))return Number(value)*1000;
 if(value!==null&&Number.isFinite(Date.parse(value)))return Math.max(0,Date.parse(value)-now);
 const millis=headers.get('retry-after-ms');
 return millis!==null&&/^\d+(?:\.\d+)?$/.test(millis.trim())?Number(millis):0;
}
function sleepWithSignal(ms,signal){return new Promise((resolve,reject)=>{
 if(signal?.aborted){reject(signal.reason||Error('Aborted'));return;}
 const abort=()=>{clearTimeout(timer);reject(signal.reason||Error('Aborted'));};
 const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve();},ms);
 signal?.addEventListener('abort',abort,{once:true});
});}
function bodyStream(bytes,emit,attemptId,model,started){
 let offset=0;
 return new ReadableStream({pull(controller){
  if(offset===0)emit({event:'body_stream_started',attempt_id:attemptId,actual_model:model,body_bytes:bytes.length});
  if(offset>=bytes.length){controller.close();emit({event:'body_stream_exhausted',attempt_id:attemptId,actual_model:model,body_bytes:bytes.length,client_seconds:(performance.now()-started)/1000,measurement:'bytes offered to HTTP transport; not socket delivery proof'});return;}
  const end=Math.min(offset+65536,bytes.length);controller.enqueue(bytes.subarray(offset,end));offset=end;
 }});
}
function unsupportedModelImage(text){
 let data;try{data=JSON.parse(text);}catch{return false;}
 const values=[data?.code,data?.message,data?.error?.code,data?.error?.message].filter(x=>typeof x==='string').join(' ');
 return /model|image|vision|multimodal/i.test(values)&&/unsupported|not supported|does not support|not found|not exist|invalid model|不支持/i.test(values);
}
export function providerUsage(bytes){
 const text=Buffer.isBuffer(bytes)?bytes.toString('utf8'):String(bytes);let usage=null;
 try{const data=JSON.parse(text);if(data?.usage&&typeof data.usage==='object')usage=data.usage;}catch{}
 for(const line of text.split(/\r?\n/)){if(!line.startsWith('data:'))continue;
  try{const data=JSON.parse(line.slice(5).trim());if(data?.usage&&typeof data.usage==='object')usage=data.usage;}catch{}
 }
 return usage;
}
export function guardedFetch({original,transform,endpoint,emit:emitOuter,workerKey='fixture',timeoutMs=300000,deadlineMs=1800000,
 sleep=sleepWithSignal,now=Date.now,random=Math.random,initialRouteIndex,unauthenticatedPreflight=false,terminate=()=>process.exit(78)}){
 let nextRoute=initialRouteIndex??Number(BigInt('0x'+sha(workerKey).slice(0,16))%BigInt(ROUTES.length));
 const workerDeadline=now()+deadlineMs;
 return async function(input,init){
  const requestId=randomUUID(),emit=row=>emitOuter({sdk_request_id:requestId,...row});
  const url=typeof input==='string'?input:input instanceof URL?input.href:input.url;
  if(new URL(url).href!==endpoint)return original.call(this,input,init);
  let body=init?.body;if(body===undefined&&input instanceof Request)body=await input.clone().text();
  if(typeof body!=='string'&&!Buffer.isBuffer(body))throw Error('Uninspectable body');
  const prepared=await transform(body.toString()),payload=JSON.parse(prepared.wire);
  if(payload.model!==ROUTES[0]&&!ROUTES.includes(payload.model))throw Error('Unapproved model identity');
  const method=init?.method||(input instanceof Request?input.method:'POST');if(method.toUpperCase()!=='POST')throw Error('Unapproved model method');
  const headers=new Headers(init?.headers||(input instanceof Request?input.headers:undefined));headers.delete('transfer-encoding');headers.delete('content-length');
  const callerSignal=init?.signal||(input instanceof Request?input.signal:undefined);
  const startedWall=now(),deadline=workerDeadline;let attempt=0,failedRoutes=0,cycle=0,cycleRetryAfter=0;
  while(now()<deadline){
   if(callerSignal?.aborted)throw callerSignal.reason||Error('Aborted');
   const routeIndex=nextRoute;nextRoute=(nextRoute+1)%ROUTES.length;
   const model=ROUTES[routeIndex],wire=Buffer.from(JSON.stringify({...payload,model})),id=randomUUID();
   if(wire.length>32*1024*1024)throw Error('Inline request exceeds 32MiB');
   const started=performance.now(),controller=new AbortController();
   const timer=setTimeout(()=>controller.abort(),Math.max(1,Math.min(timeoutMs,deadline-now())));
   const signal=AbortSignal.any([controller.signal,...(callerSignal?[callerSignal]:[])]);attempt++;
   emit({event:'final_inline_request',attempt_id:id,actual_model:model,route_index:routeIndex,http_attempt:attempt,
    original_model:payload.model,body_sha256:sha(wire),body_bytes:wire.length,body_chunk_bytes:65536,
    ledger:prepared.ledger,provider_internal_latency_measured:false});
   let response,retry=false;const attemptChunks=[];
   try{
    response=await diagnosticContext.run({id,model,started,emit,endpoint},()=>original.call(this,url,{...init,method,body:bodyStream(wire,emit,id,model,started),headers,duplex:'half',signal}));
    emit({event:'response_headers',attempt_id:id,actual_model:model,http_status:response.status,client_seconds:(performance.now()-started)/1000});
    if(response.ok){
     const reader=response.body?.getReader(),chunks=attemptChunks;let bytes=0,first=true,tail='';
     if(reader)while(true){const part=await reader.read();if(part.done)break;chunks.push(Buffer.from(part.value));bytes+=part.value.byteLength;
      if(first){first=false;emit({event:'first_response_bytes',attempt_id:id,actual_model:model,client_seconds:(performance.now()-started)/1000});}
      tail=(tail+Buffer.from(part.value).toString('utf8')).slice(-256);
      if(/data:\s*\[DONE\]/.test(tail)){await reader.cancel();break;}
     }
     clearTimeout(timer);const result=Buffer.concat(chunks);
     const usage=providerUsage(result);
     emit({event:'stream_complete',attempt_id:id,actual_model:model,response_bytes:bytes,client_seconds:(performance.now()-started)/1000,
      request_wall_seconds:(now()-startedWall)/1000,response_buffered_for_safe_route_retry:true,
      usage_known:usage!==null,raw_provider_usage:usage});
     const responseHeaders=new Headers(response.headers);responseHeaders.delete('content-length');responseHeaders.delete('content-encoding');
     nextRoute=routeIndex; // Preserve prefix-cache affinity after a successful call.
     return new Response(result,{status:response.status,statusText:response.statusText,headers:responseHeaders});
    }
    if(unauthenticatedPreflight&&[401,403].includes(response.status)){clearTimeout(timer);return response;}
    retry=[403,404,408,429].includes(response.status)||response.status>=500;
    const errorBody=await response.clone().text(),errorUsage=providerUsage(errorBody);
    if(response.status===400)retry=unsupportedModelImage(errorBody);
    const retryAfter=retryAfterMs(response.headers,now());cycleRetryAfter=Math.max(cycleRetryAfter,retryAfter);
    emit({event:'route_http_error',attempt_id:id,actual_model:model,http_status:response.status,retryable:retry,retry_after_ms:retryAfter,
     usage_known:errorUsage!==null,raw_provider_usage:errorUsage,client_seconds:(performance.now()-started)/1000});
    if(response.status===401&&!unauthenticatedPreflight){
     await response.body?.cancel();clearTimeout(timer);
     emit({event:'global_authentication_rejected',attempt_id:id,actual_model:model,http_status:401,usage_known:false});
     terminate();const error=Error('Global authentication rejected');error.code='ACL_AUTH_REJECTED';throw error;
    }
    if(!retry){clearTimeout(timer);return response;}
    await response.body?.cancel();
   }catch(error){
    const detail=safeError(error),usage=providerUsage(Buffer.concat(attemptChunks));emit({event:'route_transport_error',attempt_id:id,actual_model:model,...detail,usage_known:usage!==null,raw_provider_usage:usage,client_seconds:(performance.now()-started)/1000});
    if(callerSignal?.aborted||detail.cause_codes.some(x=>['UND_ERR_INVALID_ARG','ACL_AUTH_REJECTED'].includes(x)))throw error;
    retry=true;
   }finally{clearTimeout(timer);}
   if(retry)failedRoutes++;
   if(failedRoutes===ROUTES.length){
    const delay=Math.max(cycleRetryAfter,Math.min(120000,60000*2**cycle))+100+Math.max(0,Math.min(1,random()))*4900;
    const waitMs=Math.min(delay,Math.max(0,deadline-now()));
    emit({event:'route_cycle_backoff',cycle:cycle+1,failed_routes:failedRoutes,wait_ms:waitMs,retry_after_max_ms:cycleRetryAfter,
     client_wait_not_provider_latency:true});
    const waitStarted=performance.now();let waited=false;
    try{await sleep(waitMs,callerSignal);waited=true;}
    finally{emit({event:'route_backoff_complete',cycle:cycle+1,planned_wait_ms:waitMs,
     client_wait_seconds:(performance.now()-waitStarted)/1000,completed:waited,client_wait_not_provider_latency:true});}
    cycle++;failedRoutes=0;cycleRetryAfter=0;
   }
  }
  emit({event:'trial_transport_deadline',request_wall_seconds:(now()-startedWall)/1000,usage_known:false});
  throw Error('Route rotation deadline reached');
 };
}
if(process.env.ACL_INLINE_DSH_LEDGER){
 const path=process.env.ACL_INLINE_DSH_LEDGER;mkdirSync(dirname(path),{recursive:true});
 const emit=row=>appendFileSync(path,JSON.stringify({version:'dsh-inline-wire-v1',at_unix:Date.now()/1000,latency_kind:'client_transport_not_provider',...row})+'\n');
 const endpoint=process.env.TOKENHUB_BASE_URL.replace(/\/$/,'')+'/chat/completions';
 globalThis.fetch=guardedFetch({original:globalThis.fetch,transform:pythonBridge(process.env.ACL_BOUNDED_PYTHON,process.env.ACL_BOUNDED_CANVAS_ROOT),endpoint,emit,workerKey:process.env.ACL_INLINE_DSH_JOB_ID});
}
