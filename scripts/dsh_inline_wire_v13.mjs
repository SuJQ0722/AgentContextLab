/** DSH handle-aware bridge; existing one-hour four-route transport unchanged. */
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {appendFileSync,mkdirSync} from 'node:fs';
import {dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';
const ledger=process.env.ACL_INLINE_DSH_LEDGER;
delete process.env.ACL_INLINE_DSH_LEDGER;
let runtime;
try{runtime=await import('./dsh_hosted_wire_v4.mjs');}
finally{if(ledger!==undefined)process.env.ACL_INLINE_DSH_LEDGER=ledger;}
export const ROUTES=runtime.ROUTES;
export const guardedFetch=options=>runtime.guardedFetch({deadlineMs:3600000,...options});
export function pythonBridge(python,root){
 let child;const pending=new Map();
 function start(){
  child=spawn(python,[fileURLToPath(new URL('./dsh_inline_bridge_v13.py',import.meta.url)),'--canvas-root',root],{stdio:['pipe','pipe','ignore']});child.unref();
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
if(ledger){
 const seconds=Number(process.env.ACL_INLINE_DSH_TIMEOUT_SECONDS);
 if(seconds!==3600)throw Error('Explicit 3600-second DSH attempt deadline required');
 mkdirSync(dirname(ledger),{recursive:true});
 const emit=row=>appendFileSync(ledger,JSON.stringify({version:'dsh-inline-wire-handle-v13',at_unix:Date.now()/1000,latency_kind:'client_transport_not_provider',...row})+'\n');
 const endpoint=process.env.TOKENHUB_BASE_URL.replace(/\/$/,'')+'/chat/completions';
 globalThis.fetch=guardedFetch({original:globalThis.fetch,transform:pythonBridge(process.env.ACL_BOUNDED_PYTHON,process.env.ACL_BOUNDED_CANVAS_ROOT),endpoint,emit,workerKey:process.env.ACL_INLINE_DSH_JOB_ID});
}
