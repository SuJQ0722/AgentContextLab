/** Canonical Hermes messages and durable multi-role DSH surface transactions.
 * No message list is flattened into a user-role text checkpoint.
 */
import { createHash, randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { Session } from '../../deepseekHarness/packages/core/session/lib/index.js';
import { createMessage } from '../../deepseekHarness/packages/llm/llm/lib/index.js';
import { inlineImagesForRenderer } from './content.mjs';
const sha = data => createHash('sha256').update(data).digest('hex');
const jsonEqual = (a,b) => JSON.stringify(a) === JSON.stringify(b);


export const sharedPolicyProjection={
 type:'acl/hermes-policy-projection',
 project(event,context){
  const updates=new Map();
  for(const target of event.data.targets??[]){
   if(!context.nodes.includes(target.seq)||updates.has(target.seq))throw new Error('Invalid shared policy projection target');
   const source=context.events[target.seq-context.baseSeq];
   const before=context.messages.get(target.seq)??(source.type==='user/message'?source.data:source.data.message);
   if(!before||!jsonEqual(before,target.before)||before.id!==target.after.id)throw new Error('Shared policy projection input identity changed');
   const allowed=before.role==='assistant'&&target.after.role==='assistant'||before.role==='user'&&target.after.role==='assistant'&&target.summaryCallId;
   if(!allowed)throw new Error('Shared policy projection may only transform assistant context or project a real auxiliary summary checkpoint');
   updates.set(target.seq,Object.freeze(structuredClone(target.after)));
  }
  return updates;
 }
};
export async function toHermesMessages(messages, attachments, signal) {
  const inline = await inlineImagesForRenderer(messages, attachments, signal);
  return inline.map((message, index) => {
    const item = {role: message.role, content: [], _dsh_original_id: messages[index].id};
    const calls = [];
    for (const block of message.content) {
      if (block.type === 'text' || block.type === 'image_url') item.content.push(block);
      else if (block.type === 'reasoning') item.reasoning_content = (item.reasoning_content ?? '') + block.text;
      else if (block.type === 'tool-call') calls.push({id:block.id,type:'function',function:{name:block.name,arguments:block.arguments}});
      else if(message.role==='developer'&&['tool-addition','tool-removal'].includes(block.type)){
        item.content.push({type:'text',text:`[DSH harness ${block.type}: ${block.toolName}]`});
        (item._dsh_native_developer_blocks??=[]).push(block);
      }else throw new Error(`Shared Hermes policy cannot represent DSH block ${block.type}`);
    }
    if(item.content.every(b=>b.type==='text'))item.content=item.content.map(b=>b.text).join('\n');
    if (calls.length) item.tool_calls = calls;
    if (message.role === 'tool') {
      item.tool_call_id = message.toolCallId;
      item._dsh_is_error = message.isError === true;
    }
    return item;
  });
}

export async function fromHermesMessages(messages, originals, canonicalOriginals, attachments, route, auditDir, signal) {
  const originalById = new Map(originals.map(m => [m.id,m]));
  const canonicalById = new Map(canonicalOriginals.map(m => [m._dsh_original_id,m]));
  const imageByUrl = new Map();
  for (let i=0;i<canonicalOriginals.length;i++) {
    const refs = originals[i].content.filter(b=>b.type==='image');
    const urls = (Array.isArray(canonicalOriginals[i].content)?canonicalOriginals[i].content:[]).filter(b=>b.type==='image_url');
    urls.forEach((b,j)=>imageByUrl.set(b.image_url.url,refs[j]));
  }
  const converted = [], imageLedger = [];
  for (const [messageIndex,item] of messages.entries()) {
    const original = originalById.get(item._dsh_original_id);
    if (original && jsonEqual(item,canonicalById.get(item._dsh_original_id))) { converted.push(original); continue; }
    const content = [];
    const parts = typeof item.content === 'string' ? [{type:'text',text:item.content}] : item.content ?? [];
    if (!Array.isArray(parts)) throw new Error('Shared policy returned noncanonical message content');
    for (const [contentIndex,part] of parts.entries()) {
      if (part.type === 'text') { content.push({type:'text',text:part.text}); continue; }
      if (part.type !== 'image_url') throw new Error(`Unsupported shared-policy output block ${part.type}`);
      const url = typeof part.image_url === 'string' ? part.image_url : part.image_url?.url;
      if (imageByUrl.has(url)) { const block=imageByUrl.get(url);content.push({...block,...part.image_url?.detail?{aclImageDetail:part.image_url.detail}:{}});continue; }
      const match = /^data:(image\/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=\r\n]+)$/.exec(url ?? '');
      if (!match) throw new Error('Shared-policy image is not inline admitted bytes');
      const data=Buffer.from(match[2],'base64'), hash=sha(data);
      const refs=await attachments.saveImages([{data,mediaType:match[1]}]);
      if(refs.length!==1)throw new Error('Shared-policy image admission changed count');
      const stored=await attachments.readImage(refs[0],signal);
      if(sha(stored.data)!==hash)throw new Error('Shared-policy canvas changed during attachment admission; preserve image configuration required');
      const block={type:'image',attachment:refs[0],...part.image_url?.detail?{aclImageDetail:part.image_url.detail}:{}};imageByUrl.set(url,block);content.push(block);
      if(auditDir){await mkdir(auditDir,{recursive:true});await writeFile(join(auditDir,hash+'.'+match[1].split('/')[1]),data);}
      imageLedger.push({message_index:messageIndex,content_index:contentIndex,source_sha256:hash,native_attachment:refs[0]});
    }
    for(const call of item.tool_calls ?? [])content.push({type:'tool-call',id:call.id,name:call.function.name,
      arguments:typeof call.function.arguments==='string'?call.function.arguments:JSON.stringify(call.function.arguments)});
    if(item.role==='assistant'&&item.reasoning_content)content.unshift({type:'reasoning',text:item.reasoning_content});
    if(item.role==='assistant'&&original){converted.push({...original,content});continue;}
    if(item.role==='tool'&&original){
      if(item.tool_call_id!==original.toolCallId)throw new Error('Shared policy changed a tool call identity');
      converted.push({...original,content});continue;
    }
    let source;
    if(item.role==='system')source={kind:'system-prompt'};
    else if(item.role==='assistant')source={kind:'model',provider:route.provider,model:route.model};
    else if(item.role==='tool')source={kind:'tool',callId:item.tool_call_id};
    else source={kind:'hermes-shared-policy',policyVersion:'hermes-shared-context-v1',originalMessageId:item._dsh_original_id??null};
    converted.push(createMessage({role:item.role,content,source,...item.role==='tool'?{toolCallId:item.tool_call_id,isError:item._dsh_is_error===true}:{}}));
  }
  return {messages:converted,imageLedger,origins:messages.map(m=>m._dsh_original_id??null)};
}

/** Synchronous multi-role replacement; prepare/validate in a detached replay first.
 * The start/end bracket records the policy transaction, source sequence list and
 * provider-independent state live in the caller's immutable journal. A pending
 * journal blocks resume if a process crashes before completion.
 */
export function replaceSurface(session, messages, route, options) {
  const {turn,step,expectedNodes,policyCallId,preflight=true,origins=messages.map(m=>m.id),nodeTokens={}}=options;
  const nodes=[...session.surface.nodes],old=session.deriveMessages();
  if(!jsonEqual(nodes,expectedNodes)||nodes.length!==old.length)throw new Error('Shared policy surface changed or contains dormant nodes');
  const oldIndex=new Map(old.map((m,i)=>[m.id,i]));
  const anchors=[];
  for(let i=0;i<messages.length;i++)if(oldIndex.has(origins[i]))anchors.push({old:oldIndex.get(origins[i]),next:i});
  if(anchors.some((a,i)=>i>0&&a.old<=anchors[i-1].old))throw new Error('Shared policy reordered original history');
  const operations=[];
  for(const a of anchors)if(!jsonEqual(old[a.old],messages[a.next]))operations.push({start:a.old,end:a.old,message:messages[a.next]});
  const bounds=[{old:-1,next:-1},...anchors,{old:old.length,next:messages.length}];
  for(let i=1;i<bounds.length;i++){
    const left=bounds[i-1],right=bounds[i],start=left.old+1,end=right.old-1;
    const added=messages.slice(left.next+1,right.next);
    if(start>end&&!added.length)continue;
    if(added.length===1&&start<=end){operations.push({start,end,message:added[0]});continue;}
    if(!added.length&&start<=end&&left.old>=0&&messages[left.next].role!=='assistant'){
      // Deletion is a single native replacement anchored by the retained preceding message.
      operations.push({start:left.old,end,message:messages[left.next]});continue;
    }
    throw new Error('Shared policy output cannot be represented by native non-assistant range replacements; refusing role flattening');
  }
  // A deletion may subsume an independently changed preceding anchor.
  const selected=operations.filter((op,i)=>!operations.some((other,j)=>j!==i&&other.start<=op.start&&other.end>=op.end&&(other.end-other.start>op.end-op.start)));
  for(const op of selected){
    if(op.message.role==='assistant'&&!(op.start===op.end&&old[op.start].role==='assistant')&&!options.summaryCallId)throw new Error('New assistant-role summary lacks a recorded auxiliary model call');
    if(op.message.role==='tool'&&op.message.toolCallId!==op.message.source.callId)throw new Error('Shared policy tool call id mismatch');
    if(op.start===0&&old[0]?.role==='system'&&(op.end!==0||op.message.role!=='system'))throw new Error('Shared policy must preserve the native system head');
  }
  if(preflight){const replay=Session.create('shared-policy-validation',session.snapshotEvents(),undefined,undefined,[sharedPolicyProjection]);replaceSurface(replay,messages,route,{...options,preflight:false});}
  if(!selected.length)return null;
  const id=policyCallId??randomUUID();const startEvent=session.append('compaction/start',{compactionId:id,turn});let summarySeq=null;
  for(const op of selected.sort((a,b)=>b.start-a.start)){
    const sources=nodes.slice(op.start,op.end+1),shadowedRange={start:sources[0],end:sources.at(-1)};
    const shadowedTokenCount=sources.reduce((n,seq)=>n+(nodeTokens[seq]??0),0);
    const message=op.message;let type,data;
    if(message.role==='assistant'&&op.start===op.end&&old[op.start].role==='assistant'){
      session.append('acl/hermes-policy-projection',{targets:[{seq:sources[0],before:old[op.start],after:message,reason:'actual Hermes tool-argument pruning'}]});continue;
    }
    if(message.role==='assistant'){
      // Native checkpoint is attributed to the real auxiliary request. A pure,
      // durable projection preserves Hermes' assistant role without inventing a
      // main-agent response or a model step.
      const checkpoint={...message,role:'user',source:{kind:'hermes-shared-summary',callId:options.summaryCallId}};
      const e=session.append('compaction/summary',{compactionId:id,summary:message.content,shadowedRange,shadowedSeqs:sources,shadowedTokenCount,provider:route.provider,model:route.model});summarySeq=e.seq;
      const replacement=session.append('user/message',checkpoint,{surfaceOp:{op:'replace',startSeq:shadowedRange.start,endSeq:shadowedRange.end},sourceEventSeqs:sources});
      session.append('acl/hermes-policy-projection',{targets:[{seq:replacement.seq,before:checkpoint,after:message,summaryCallId:options.summaryCallId,reason:'actual Hermes summary role'}]});continue;
    }
    if(message.role==='user'){
      const e=session.append('compaction/summary',{compactionId:id,summary:message.content,shadowedRange,shadowedSeqs:sources,shadowedTokenCount,provider:route.provider,model:route.model});summarySeq=e.seq;
      type='user/message';data=message;
    }else{
      session.append('compaction/prune',{shadowedRange,shadowedSeqs:sources,shadowedTokenCount});
      type=message.role==='tool'?'tool/result':message.role+'/message';
      data=message.role==='tool'?{...session.snapshotEvents()[sources[0]].data,message}:{turn,step,message};
    }
    session.append(type,data,{surfaceOp:{op:'replace',...{startSeq:shadowedRange.start,endSeq:shadowedRange.end}},sourceEventSeqs:sources});
  }
  const endEvent=session.append('compaction/end',{compactionId:id,turn});
  const derived=session.deriveMessages();
  if(!jsonEqual(derived,messages))throw new Error('Native surface differs from exact Hermes policy output');
  return {compactionId:id,startSeq:startEvent.seq,endSeq:endEvent.seq,summarySeq,
    shadowedSeqs:selected.flatMap(o=>nodes.slice(o.start,o.end+1)),transaction_kind:'native per-span replacements; retained assistant nodes never replayed'};
}
