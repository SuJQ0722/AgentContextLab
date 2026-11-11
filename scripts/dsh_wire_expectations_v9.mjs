/** Readonly GenerateOptions-safe last-ten projection and unchanged byte guard.
 * The pinned runtime's stream() re-enters its middleware with a fresh options
 * object. AsyncLocalStorage scopes re-entry to iteration, not generator creation.
 */
import {AsyncLocalStorage} from 'node:async_hooks';
import {mkdir,writeFile,rename,appendFile} from 'node:fs/promises';
import {dirname} from 'node:path';
import {projectLastTenImages} from './dsh_pre_sdk_images.mjs';
import {flushUsageObservers} from './dsh_raw_usage_observer.mjs';
const projectedCalls=new AsyncLocalStorage();

async function* redispatch(runtime,options,audit){
 const scope={runtime,options,audit};
 const iterator=projectedCalls.run(scope,()=>runtime.stream(options)[Symbol.asyncIterator]());let completed=false;
 try{
  while(true){
   const item=await projectedCalls.run(scope,()=>iterator.next());
   if(item.done){completed=true;return;}
   yield item.value;
  }
 }finally{
  if(!completed&&iterator.return)await projectedCalls.run(scope,()=>iterator.return());
 }
}

export function apply(ctx,config){
 ctx.on('llm/stream',async function*(options,next){
  const active=projectedCalls.getStore();
  const reentry=active?.options===options;
  const projection=!reentry&&process.env.ACL_INLINE_DSH_RETAIN_IMAGES==='10'?projectLastTenImages(options.messages??[]):null;
  if(projection&&projection.messages!==options.messages){
   if(typeof this?.stream!=='function')throw Error('Native LlmRuntime.stream is required for immutable image projection');
   yield* redispatch(this,{...options,messages:projection.messages},projection.audit);
   return;
  }
  const refs=[],details=[];
  for(const message of options.messages??[])for(const part of message.content??[]){
   if(part.type==='image'&&part.attachment){refs.push(part.attachment);details.push(part.aclImageDetail??null);}
  }
  const hashes=refs.map(ref=>String(ref.attachmentId).replace(/^sha256:/,''));
  if(hashes.some(hash=>!/^[a-f0-9]{64}$/.test(hash)))throw Error('Unsupported attachment identity; cannot validate wire integrity');
  const expected={version:1,implementation:'dsh-readonly-wire-expectations-v9',session_id:options.sessionId??null,purpose:options.purpose??'agent',
   origin:'native llm/stream immutable projected attachment references',pre_sdk_retention:reentry?active.audit:projection?.audit??null,
   wire_sha256:hashes,details,native_attachments:refs,
   scope:'single isolated agent process; byte-identity policy; provider transformations are NOT silently accepted'};
  await mkdir(dirname(config.expectedFile),{recursive:true});
  await writeFile(config.expectedFile+'.tmp',JSON.stringify(expected));await rename(config.expectedFile+'.tmp',config.expectedFile);
  await appendFile(config.expectedFile+'.jsonl',JSON.stringify(expected)+'\n');
  try{yield* next();}finally{
   const observation=await flushUsageObservers({sessionId:options.sessionId??null,purpose:options.purpose??'agent',timeoutMs:5000});
   if(observation.pending.length)throw Error('Raw provider usage observer did not settle; refusing to reuse older usage');
  }
 });
}
