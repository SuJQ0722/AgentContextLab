/** Final DSH hosted transport. Upstream SDK bytes/usage are forwarded unchanged. */
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {appendFileSync,mkdirSync} from 'node:fs';
import {dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash,randomUUID} from 'node:crypto';
const sha=x=>createHash('sha256').update(x).digest('hex');

export function safeError(error){
 const codes=[];let current=error;
 for(let depth=0;current&&depth<5;depth++,current=current.cause){
  if(typeof current.code==='string'&&/^[A-Z0-9_]{1,64}$/.test(current.code))codes.push(current.code);
  for(const child of current.errors||[])if(typeof child?.code==='string'&&/^[A-Z0-9_]{1,64}$/.test(child.code))codes.push(child.code);
 }
 return {error_type:error?.name||'Error',cause_codes:[...new Set(codes)]};
}

export function pythonBridge(python,root,cache){
 let child;const pending=new Map();
 function start(){
  child=spawn(python,[fileURLToPath(new URL('./dsh_hosted_transport_bridge_v2.py',import.meta.url)),'--canvas-root',root,'--cache-root',cache],{stdio:['pipe','pipe','ignore']});child.unref();
  createInterface({input:child.stdout}).on('line',line=>{
   try{const row=JSON.parse(line),entry=pending.get(row.id);if(!entry)return;pending.delete(row.id);clearTimeout(entry.timer);row.ok?entry.resolve(row):entry.reject(Error('Image preparation '+row.error_type));if(!pending.size){child.stdin.unref();child.stdout.unref();}}
   catch{for(const e of pending.values()){clearTimeout(e.timer);e.reject(Error('Invalid bridge response'));}pending.clear();}
  });
  const fail=()=>{for(const e of pending.values()){clearTimeout(e.timer);e.reject(Error('Image bridge stopped'));}pending.clear();};child.on('error',fail);child.on('exit',fail);
 }
 return body=>new Promise((resolve,reject)=>{
  if(!child)start();child.stdin.ref();child.stdout.ref();const id=randomUUID();const timer=setTimeout(()=>{pending.delete(id);child.kill('SIGTERM');reject(Error('Image preparation deadline'));},600000);
  pending.set(id,{resolve,reject,timer});child.stdin.write(JSON.stringify({id,body})+'\n',err=>{if(err){clearTimeout(timer);pending.delete(id);reject(Error('Image bridge input failed'));}});
 });
}

export function guardedFetch({original,transform,endpoint,emit,terminate=()=>process.exit(78),timeoutMs=300000,maxFailed=2}){
 const failures=new Map();
 const stop=(reason,key)=>{emit({event:'terminal_failure',reason,body_sha256:key,usage_known:false});terminate();throw Error(reason);};
 return async function(input,init){
  const url=typeof input==='string'?input:input instanceof URL?input.href:input.url;
  if(new URL(url).href!==endpoint)return original.call(this,input,init);
  let body=init?.body;if(body===undefined&&input instanceof Request)body=await input.clone().text();
  if(typeof body!=='string'&&!Buffer.isBuffer(body))return stop('uninspectable_body',null);
  body=body.toString();let prepared;
  try{prepared=await transform(body);}catch(error){return stop('verified_image_preparation_failed',sha(body));}
  const wire=prepared.wire,key=sha(wire),started=performance.now();
  if((failures.get(key)||0)>=maxFailed)return stop('failed_send_budget',key);
  emit({event:'final_hosted_request',body_sha256:key,body_bytes:Buffer.byteLength(wire),ledger:prepared.ledger,prior_failed_sends:failures.get(key)||0});
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);
  const signal=AbortSignal.any([controller.signal,...((init?.signal||input?.signal)?[init?.signal||input.signal]:[])]);
  const headers=new Headers(init?.headers||(input instanceof Request?input.headers:undefined));headers.delete('transfer-encoding');headers.set('content-length',String(Buffer.byteLength(wire)));
  let response;
  try{response=await original.call(this,input instanceof Request?new Request(input,{body:wire,headers,signal}):input,{...init,body:wire,headers,signal});}
  catch(error){clearTimeout(timer);failures.set(key,(failures.get(key)||0)+1);emit({event:'send_error',body_sha256:key,...safeError(error),client_seconds:(performance.now()-started)/1000,usage_known:false});throw error;}
  emit({event:'response_headers',body_sha256:key,http_status:response.status,client_seconds:(performance.now()-started)/1000});
  if(!response.ok){failures.set(key,(failures.get(key)||0)+1);clearTimeout(timer);return response;}
  if(!response.body){clearTimeout(timer);failures.delete(key);return response;}
  const reader=response.body.getReader();let bytes=0,done=false,tail='',first=true;
  const success=()=>{if(!done){done=true;clearTimeout(timer);failures.delete(key);emit({event:'stream_complete',body_sha256:key,response_bytes:bytes,client_seconds:(performance.now()-started)/1000});}};
  const stream=new ReadableStream({
   async pull(c){try{const next=await reader.read();if(next.done){success();c.close();return;}bytes+=next.value.byteLength;if(first){first=false;emit({event:'first_response_bytes',body_sha256:key,client_seconds:(performance.now()-started)/1000});}tail=(tail+Buffer.from(next.value).toString('utf8')).slice(-256);if(/data:\s*\[DONE\]/.test(tail))success();c.enqueue(next.value);}
    catch(error){clearTimeout(timer);if(!done){failures.set(key,(failures.get(key)||0)+1);emit({event:'stream_error',body_sha256:key,...safeError(error),usage_known:false,client_seconds:(performance.now()-started)/1000});c.error(error);}}},
   async cancel(reason){clearTimeout(timer);if(!done)failures.set(key,(failures.get(key)||0)+1);await reader.cancel(reason);}
  });
  return new Response(stream,{status:response.status,statusText:response.statusText,headers:response.headers});
 };
}

if(process.env.ACL_HOSTED_DSH_LEDGER){
 const path=process.env.ACL_HOSTED_DSH_LEDGER;mkdirSync(dirname(path),{recursive:true});
 const emit=row=>appendFileSync(path,JSON.stringify({version:'dsh-hosted-wire-v2',at_unix:Date.now()/1000,latency_kind:'client_transport_not_provider',...row})+'\n');
 const endpoint=process.env.TOKENHUB_BASE_URL.replace(/\/$/,'')+'/chat/completions';
 globalThis.fetch=guardedFetch({original:globalThis.fetch,transform:pythonBridge(process.env.ACL_BOUNDED_PYTHON,process.env.ACL_BOUNDED_CANVAS_ROOT,process.env.ACL_HOSTED_DSH_CACHE),endpoint,emit});
}
