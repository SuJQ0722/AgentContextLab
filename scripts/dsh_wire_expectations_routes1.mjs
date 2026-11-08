/** v1 isolated-agent guard: derive expected wire bytes from native image attachments. */
import {mkdir,writeFile,rename,appendFile} from 'node:fs/promises';
import {dirname} from 'node:path';
import {flushUsageObservers} from './dsh_returned_model_routes1.mjs';
export function apply(ctx,config){
 ctx.on('llm/stream',async function*(options,next){
  const refs=[],details=[];
  for(const message of options.messages??[])for(const part of message.content??[]){
   if(part.type==='image'&&part.attachment){refs.push(part.attachment);details.push(part.aclImageDetail??null);}
  }
  const hashes=refs.map(r=>String(r.attachmentId).replace(/^sha256:/,''));
  if(hashes.some(s=>!/^[a-f0-9]{64}$/.test(s)))throw new Error('Unsupported attachment identity; cannot validate wire integrity');
  const expected={version:1,session_id:options.sessionId??null,purpose:options.purpose??'agent',origin:'native llm/stream image attachment references',wire_sha256:hashes,details,
   native_attachments:refs,scope:'single isolated agent process; byte-identity policy; provider transformations are NOT silently accepted'};
  await mkdir(dirname(config.expectedFile),{recursive:true});
  await writeFile(config.expectedFile+'.tmp',JSON.stringify(expected));await rename(config.expectedFile+'.tmp',config.expectedFile);
  await appendFile(config.expectedFile+'.jsonl',JSON.stringify(expected)+'\n');
  try{yield* next();}finally{
   const observation=await flushUsageObservers({sessionId:options.sessionId??null,purpose:options.purpose??'agent',timeoutMs:5000});
   if(observation.pending.length)throw new Error('Raw provider usage observer did not settle; refusing to reuse older usage');
  }
 });
}
