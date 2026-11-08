import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {inspect,validate} from './dsh_wire_image_guard_capacity1.mjs';

test('rejection records actual retained images and never calls transport; details still exact',async()=>{
 const output=await mkdtemp(join(tmpdir(),'capacity1-guard-'));
 const png=Buffer.alloc(24);Buffer.from([137,80,78,71,13,10,26,10]).copy(png);png.writeUInt32BE(100,16);png.writeUInt32BE(200,20);
 const body={model:'local-fixture',messages:[{role:'user',content:[{type:'image_url',image_url:{url:'data:image/png;base64,'+png.toString('base64')}}]}]};
 const [im]=inspect(body),expected=join(output,'expected.json');
 await writeFile(expected,JSON.stringify({wire_sha256:[im.sha256,im.sha256],details:['low','high']}));
 const original=globalThis.fetch,previous={...process.env};let sends=0;
 globalThis.fetch=async(input,init)=>{sends++;const parsed=JSON.parse(init.body);validate(inspect(parsed),{wire_sha256:[im.sha256],details:['high']});return new Response(JSON.stringify({usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2}}),{headers:{'content-type':'application/json'}});};
 process.env.ACL_IMAGE_WIRE_AUDIT_DIR=output;process.env.ACL_IMAGE_WIRE_EXPECTED=expected;process.env.ACL_IMAGE_WIRE_APPLY_DETAILS='1';
 try{
  await import('./dsh_wire_image_guard_capacity1.mjs?install-test');
  await assert.rejects(fetch('http://127.0.0.1/fixture',{method:'POST',body:JSON.stringify(body)}),/image count changed/);
  assert.equal(sends,0);
  const rejected=JSON.parse((await readFile(join(output,'requests.jsonl'),'utf8')).trim());
  assert.equal(rejected.image_count,1);assert.equal(rejected.images[0].sha256,im.sha256);assert.equal(rejected.request_sent,false);
  await writeFile(expected,JSON.stringify({wire_sha256:[im.sha256],details:['high']}));
  await fetch('http://127.0.0.1/fixture',{method:'POST',body:JSON.stringify(body)});
  assert.equal(sends,1);
 }finally{
  globalThis.fetch=original;
  for(const key of ['ACL_IMAGE_WIRE_AUDIT_DIR','ACL_IMAGE_WIRE_EXPECTED','ACL_IMAGE_WIRE_APPLY_DETAILS']){
   if(previous[key]===undefined)delete process.env[key];else process.env[key]=previous[key];
  }
 }
});
