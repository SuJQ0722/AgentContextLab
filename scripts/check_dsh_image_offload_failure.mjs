/** Offline replay of the native image budget/projection and unchanged wire guard.
 * Reads retained PNGs only; no model calls, no network, no campaign mutation.
 */
import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {toPiContext} from '../deepseekHarness/packages/llm/llm-pi-ai/src/context.ts';
import {offloadMessageImages} from '../deepseekHarness/packages/compaction/compaction-image-offload/src/project-message.ts';
import {inspect,validate,applyExpectedImageDetails} from './dsh_wire_image_guard.mjs';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const out=resolve(process.argv[2]??`${root}/outputs/preflight/dsh-image-offload-diagnosis`);
const rows=[];
for(const q of ['q_039','q_048']){
 const native=resolve(root,`outputs/campaigns/bc100-r3-hermes-parity-v3/jobs/dsh/visual/${q}_r01/attempts/attempt_001/native/visual_native/${q}`);
 const expected=JSON.parse(await readFile(`${native}/workspace/metrics/expected-wire.json`,'utf8'));
 const refs=expected.native_attachments;
 const message={role:'user',content:refs.map(attachment=>({type:'image',attachment}))};
 const attachments={async readImageRequest(ref){
  const hash=ref.attachmentId.replace(/^sha256:/,'');
  const data=await readFile(`${native}/dsh-home/attachments/v1/objects/${hash.slice(0,2)}/${hash}`);
  return {variantId:ref.attachmentId,attachment:ref,data,bytes:data.length,mediaType:ref.mediaType,width:ref.width,height:ref.height};
 }};
 const ctx={attachments,resolveImageAccess:()=>undefined,maxRequestImageBytes:20*1024*1024,
  requestImagePolicy:{maxPixels:64_000_000,maxBytes:50*1024*1024}};
 const request=messages=>({provider:'tokenhub',model:'offline-fixture',messages});
 let failure;
 try{await toPiContext(request([message]),ctx);}catch(error){failure=error;}
 assert.equal(failure?.code,'IMAGE_OFFLOAD_REQUIRED');
 assert.equal(failure.failure.offloadImages,1);
 const projected=offloadMessageImages(message,[0]);
 const pi=await toPiContext(request([projected]),ctx);
 // pi-ai image vocabulary to Chat Completions vocabulary; no model adapter/HTTP invoked.
 const bodyOf=pi=>({messages:pi.messages.map(m=>({role:m.role,content:typeof m.content==='string'?m.content:m.content.map(p=>p.type==='image'?{type:'image_url',image_url:{url:`data:${p.mimeType};base64,${p.data}`}}:p)}))});
 const body=bodyOf(pi),actual=inspect(body);
 assert.equal(actual.length,refs.length-1);
 assert.throws(()=>validate(actual,expected),/image count changed/);
 // Reproduce current logger's empty array artifact even though body retains images.
 let loggedImages=[],guardError=null;
 try{applyExpectedImageDetails(body,expected);loggedImages=inspect(body);}catch(error){guardError=error.message;}
 assert.equal(loggedImages.length,0);
 assert.ok(guardError);
 const base64Bytes=refs.reduce((sum,r)=>sum+4*Math.ceil(r.bytes/3),0);
 // Counterfactual is offline only: a sufficient explicit budget preserves every byte.
 const full=bodyOf(await toPiContext(request([message]),{...ctx,maxRequestImageBytes:base64Bytes}));
 applyExpectedImageDetails(full,expected);validate(inspect(full),expected);
 rows.push({question:q,expected_images:refs.length,base64_bytes:base64Bytes,configured_cap:ctx.maxRequestImageBytes,
  native_failure:{code:failure.code,offloadImages:failure.failure.offloadImages},
  projected_actual_images:actual.length,current_guard_logged_images:loggedImages.length,guard_error:guardError,
  sufficient_budget_offline_all_hashes_and_details_match:true});
}
await mkdir(out,{recursive:true});
const report={paid_requests:0,network_requests:0,scope:'Native toPiContext and durable offload projection with real retained PNGs; unchanged guard; HTTP conversion is fixture-only. No production repair applied.',rows};
await writeFile(`${out}/result.json`,JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({output:out,...report}));
