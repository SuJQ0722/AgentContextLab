/** Offline native SDK replay with saved attachments. Never invokes an API. */
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {toPiContext} from '../deepseekHarness/packages/llm/llm-pi-ai/src/context.ts';
import {projectLastTenImages} from './dsh_pre_sdk_images.mjs';
import {inspect,validate,applyExpectedImageDetails} from './dsh_wire_image_guard.mjs';
const [expectedPath,objects,out]=process.argv.slice(2);
if(!out)throw Error('Usage: node check_dsh_pre_sdk_retention.mjs expected.json attachment-objects-dir result.json');
const expected=JSON.parse(await readFile(expectedPath,'utf8'));
const original=[{role:'user',content:expected.native_attachments.map((attachment,i)=>({type:'image',attachment,aclImageDetail:expected.details?.[i]??'high'}))}];
const before=JSON.stringify(original),projection=projectLastTenImages(original),parts=projection.messages.flatMap(m=>m.content.filter(p=>p.type==='image'));
let reads=0;
const attachments={async readImageRequest(ref){
 reads++;const hash=ref.attachmentId.replace(/^sha256:/,''),data=await readFile(`${objects}/${hash.slice(0,2)}/${hash}`);
 return {variantId:ref.attachmentId,attachment:ref,data,bytes:data.length,mediaType:ref.mediaType,width:ref.width,height:ref.height};
}};
const pi=await toPiContext({provider:'tokenhub',model:'offline-fixture',messages:projection.messages},
 {attachments,resolveImageAccess:()=>undefined,maxRequestImageBytes:20*1024*1024,maxRequestImages:10,requestImagePolicy:{maxPixels:64_000_000,maxBytes:50*1024*1024}});
const body={messages:pi.messages.map(m=>({role:m.role,content:typeof m.content==='string'?m.content:m.content.map(p=>p.type==='image'?{type:'image_url',image_url:{url:`data:${p.mimeType};base64,${p.data}`}}:p)}))};
const retained={wire_sha256:parts.map(p=>p.attachment.attachmentId.slice(7)),details:parts.map(p=>p.aclImageDetail)};
applyExpectedImageDetails(body,retained);validate(inspect(body),retained);assert.equal(JSON.stringify(original),before);
const report={api_calls:0,network_requests:0,expected_path:expectedPath,projection:projection.audit,wire_images:inspect(body).length,attachment_reads:reads,native_sdk_budget_bytes:20*1024*1024,all_retained_hashes_and_details_match:true,history_unchanged:true};
await writeFile(out,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({...report,projection:{...report.projection,removed:report.projection.removed.length}}));
