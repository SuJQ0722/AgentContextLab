import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {projectLastTenImages} from '../scripts/dsh_pre_sdk_images.mjs';
import {apply} from '../scripts/dsh_wire_expectations.mjs';
const image=i=>({type:'image',attachment:{attachmentId:'sha256:'+i.toString(16).padStart(64,'0')},aclImageDetail:'high'});
const source=()=>Array.from({length:14},(_,i)=>({role:'user',content:[{type:'text',text:`position ${i}`},image(i)]}));
test('last ten before SDK, exact image identity and unchanged text/history',()=>{
 const messages=source(),saved=JSON.stringify(messages),projected=projectLastTenImages(messages);
 assert.equal(JSON.stringify(messages),saved);assert.equal(projected.audit.removed.length,4);
 assert.deepEqual(projected.messages.map(x=>x.content[0]),messages.map(x=>x.content[0]));
 assert.deepEqual(projected.messages.flatMap(x=>x.content.filter(p=>p.type==='image')),messages.slice(4).map(x=>x.content[1]));
 const small=messages.slice(0,5);assert.equal(projectLastTenImages(small).messages,small);
 messages.at(-1).content[1].offloaded=true;assert.throws(()=>projectLastTenImages(messages),/unavailable/);
});
test('middleware expectations match projected request and history restores on failure',async()=>{
 const root=await mkdtemp(join(tmpdir(),'acl-pre-sdk-')),expectedFile=join(root,'expected.json');
 const previous=process.env.ACL_INLINE_DSH_RETAIN_IMAGES;process.env.ACL_INLINE_DSH_RETAIN_IMAGES='10';
 let middleware;apply({on(event,handler){assert.equal(event,'llm/stream');middleware=handler;}},{expectedFile});
 const messages=source(),options={messages,purpose:'agent',sessionId:'fixture'};
 try{
  const next=async function*(){
   const expected=JSON.parse(await readFile(expectedFile));
   assert.equal(expected.wire_sha256.length,10);assert.equal(expected.pre_sdk_retention.removed.length,4);
   assert.deepEqual(expected.wire_sha256,options.messages.flatMap(x=>x.content.filter(p=>p.type==='image').map(p=>p.attachment.attachmentId.slice(7))));
   throw Error('fixture upstream failure');
  };
  await assert.rejects(async()=>{for await(const chunk of middleware(options,next)){}},/fixture upstream failure/);
  assert.equal(options.messages,messages);assert.equal(messages.flatMap(x=>x.content.filter(p=>p.type==='image')).length,14);
 }finally{if(previous===undefined)delete process.env.ACL_INLINE_DSH_RETAIN_IMAGES;else process.env.ACL_INLINE_DSH_RETAIN_IMAGES=previous;await rm(root,{recursive:true,force:true});}
});
