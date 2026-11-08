/** v1 external Node preload: observe final HTTP JSON image blocks, never headers. */
import {mkdirSync,appendFileSync,writeFileSync,readFileSync} from 'node:fs';
import {join} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {observeUsageResponse,recordUsageTransportFailure} from './dsh_raw_usage_observer.mjs';
export function dimensions(b){
 if(b.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])))return {format:'png',width:b.readUInt32BE(16),height:b.readUInt32BE(20)};
 if(b.length>=10&&['GIF87a','GIF89a'].includes(b.subarray(0,6).toString('ascii')))return {format:'gif',width:b.readUInt16LE(6),height:b.readUInt16LE(8)};
 if(b.length>=30&&b.subarray(0,4).toString()==='RIFF'&&b.subarray(8,12).toString()==='WEBP'){
  const chunk=b.subarray(12,16).toString('ascii');
  if(chunk==='VP8X')return {format:'webp',width:1+b.readUIntLE(24,3),height:1+b.readUIntLE(27,3)};
  if(chunk==='VP8 '&&b.subarray(23,26).equals(Buffer.from([157,1,42])))return {format:'webp',width:b.readUInt16LE(26)&16383,height:b.readUInt16LE(28)&16383};
 }
 if(b.length>=25&&b.subarray(0,4).toString()==='RIFF'&&b.subarray(8,16).toString()==='WEBPVP8L'&&b[20]===47){const packed=b.readUInt32LE(21);return {format:'webp',width:1+(packed&16383),height:1+((packed>>>14)&16383)};}
 if(b[0]===255&&b[1]===216){let i=2;while(i+8<b.length){if(b[i++]!==255)continue;let m=b[i++];if(m===216||m===217)continue;let n=b.readUInt16BE(i);if([192,193,194,195,197,198,199,201,202,203,205,206,207].includes(m))return {format:'jpeg',width:b.readUInt16BE(i+5),height:b.readUInt16BE(i+3)};if(n<2)break;i+=n;}}
 throw new Error('Wire image guard: unrecognized image geometry');
}
export function inspect(payload){
 const result=[];
 for(const [mi,m] of (payload.messages??[]).entries())for(const [pi,p] of (Array.isArray(m.content)?m.content:[]).entries()){
  if(p.type!=='image_url')continue;
  const url=typeof p.image_url==='string'?p.image_url:p.image_url?.url;
  const match=/^data:(image\/[a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\r\n]+)$/.exec(url??'');
  if(!match)throw new Error('Wire image guard: image is not inline bytes');
  const data=Buffer.from(match[2],'base64');if(!data.length)throw new Error('Wire image guard: empty image');
  result.push({message_index:mi,part_index:pi,type:p.type,detail_present:typeof p.image_url==='object'&&Object.hasOwn(p.image_url,'detail'),detail:typeof p.image_url==='object'?(p.image_url.detail??null):null,
   media_type:match[1],bytes:data.length,sha256:createHash('sha256').update(data).digest('hex'),...dimensions(data),data});
 }
 return result;
}
function plainText(content){
 if(typeof content==='string')return content;
 if(Array.isArray(content)&&content.every(p=>p.type==='text'&&typeof p.text==='string'))return content.map(p=>p.text).join('');
 return null;
}
export function isNativeTitleRequest(body){
 if(!Array.isArray(body.messages)||body.messages.length!==2||body.tools?.length)return false;
 const [system,user]=body.messages;
 if(system.role!=='system'||user.role!=='user')return false;
 const lines=plainText(system.content)?.split('\n');
 if(!lines||lines.length!==5||lines[0]!=='Create a concise title for an AI coding-assistant session from the supplied human messages.'||
 lines[1]!=='Return only the title on one line, **in plain text of natural language**, with no quotes, prefix, explanation, Markdown, XML, or terminal control codes. No code is allowed.'||
 lines[2]!=='Use the language of the messages.'||!/^Aim for about [1-9][0-9]* words in non-CJK languages or [1-9][0-9]* CJK characters\.$/.test(lines[3])||
 lines[4]!=='If the messages give little to name, still return a short best-effort title, such as Greeting, instead of explaining.')return false;
 const prefix='Generate the session title from this JSON array of human messages:\n';
 const text=plainText(user.content);if(!text?.startsWith(prefix))return false;
 try{return Array.isArray(JSON.parse(text.slice(prefix.length)));}catch{return false;}
}
/** Explicit v3 transport adapter: changes only detail, never image bytes or order. */
export function applyExpectedImageDetails(payload,expected){
 const images=inspect(payload);validate(images,{wire_sha256:expected.wire_sha256});
 const changes=[];
 for(const [i,detail] of (expected.details??[]).entries()){
  if(detail===null)continue;
  if(!['low','high','auto'].includes(detail))throw new Error('Invalid expected image detail');
  const meta=images[i];if(!meta)throw new Error('Image detail count exceeds image count');
  const part=payload.messages[meta.message_index].content[meta.part_index];
  const before=typeof part.image_url==='object'?(part.image_url.detail??null):null;
  if(typeof part.image_url==='string')part.image_url={url:part.image_url};
  part.image_url.detail=detail;
  if(before!==detail)changes.push({image_index:i,before,after:detail,sha256:meta.sha256});
 }
 validate(inspect(payload),expected);return changes;
}
export function validate(images,expected){
 if(images.length!==expected.wire_sha256.length)throw new Error('Wire image guard: image count changed');
 images.forEach((im,i)=>{if(im.sha256!==expected.wire_sha256[i])throw new Error('Wire image guard: wire image differs from expected identity');const detail=expected.details?.[i];if(detail!=null&&im.detail!==detail)throw new Error('Wire image guard: image detail differs from Hermes source');});
}
const output=process.env.ACL_IMAGE_WIRE_AUDIT_DIR;
if(output){
 mkdirSync(output,{recursive:true});const original=globalThis.fetch;let sequence=0;
 globalThis.fetch=async function(input,init){
  let observerOptions=null;
  let raw=init?.body;
  if(raw===undefined&&input instanceof Request)raw=await input.clone().text();
  let body;try{body=JSON.parse(typeof raw==='string'?raw:Buffer.isBuffer(raw)?raw.toString():'');}catch{}
  if(body&&Array.isArray(body.messages)){
   const isTitle=isNativeTitleRequest(body);
   const hasMarker=!isTitle&&body.messages.some(m=>JSON.stringify(m.content??'').includes('WIRE_CANVAS_AUDIT'));
   const id=randomUUID();let images=[];let error=null;let detailChanges=null;
   try{
    if(!isTitle&&process.env.ACL_IMAGE_WIRE_EXPECTED&&process.env.ACL_IMAGE_WIRE_APPLY_DETAILS==='1'){
     const expected=JSON.parse(readFileSync(process.env.ACL_IMAGE_WIRE_EXPECTED,'utf8'));
     detailChanges=applyExpectedImageDetails(body,expected);
     init={...init,body:JSON.stringify(body)};
    }
    images=inspect(body);
    if(hasMarker&&!images.length)throw new Error('Wire image guard: task lost all canvas images');
    if(!isTitle&&process.env.ACL_IMAGE_WIRE_EXPECTED)validate(images,JSON.parse(readFileSync(process.env.ACL_IMAGE_WIRE_EXPECTED,'utf8')));
   }catch(e){error=e.message;}
   for(const im of images)writeFileSync(join(output,im.sha256+'.'+im.format),im.data);
   const record={version:1,request_id:id,sequence:sequence++,timestamp:new Date().toISOString(),model:body.model,
    request_path:new URL(typeof input==='string'?input:input.url).pathname,task_marker_present:hasMarker,
    stream:body.stream??false,is_title_request:isTitle,image_count:images.length,images:images.map(({data,...meta})=>meta),
    detail_adaptation:detailChanges===null?null:{version:'hermes-image-detail-v1',changes:detailChanges,image_bytes_unchanged:true},
    guard_error:error,strict_reviewed_transform:!!process.env.ACL_IMAGE_WIRE_EXPECTED,request_sent:!error};
   appendFileSync(join(output,'requests.jsonl'),JSON.stringify(record)+'\n');
   if(error)throw new Error(error);
   let expectation={};
   if(!isTitle&&process.env.ACL_IMAGE_WIRE_EXPECTED)expectation=JSON.parse(readFileSync(process.env.ACL_IMAGE_WIRE_EXPECTED,'utf8'));
   observerOptions={ledgerPath:join(output,'raw-usage.jsonl'),requestId:id,requestModel:body.model,
    sessionId:expectation.session_id??null,purpose:isTitle?'title':expectation.purpose??'agent'};
  }
  try{
   const response=await original.call(this,input,init);
   if(observerOptions)void observeUsageResponse(response,observerOptions);
   return response;
  }catch(error){if(observerOptions)recordUsageTransportFailure(observerOptions,error);throw error;}
 };
}
