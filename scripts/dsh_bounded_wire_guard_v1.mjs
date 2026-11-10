/** Exact final DSH request limits; immutable canvas registry, no payload edits. */
import {readFileSync,readdirSync,existsSync,appendFileSync,mkdirSync} from 'node:fs';
import {resolve,relative,dirname,join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
const sha=b=>createHash('sha256').update(b).digest('hex');
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

const pixelVerified=new Map();
export function registry(root){
 const result=new Set();if(!existsSync(root))return result;
 const verified=new Map();
 function artifact(path,hash){const full=resolve(path),rel=relative(resolve(root),full);if(rel.startsWith('..')||rel==='')throw Error('Canvas path outside root');const b=readFileSync(full);if(sha(b)!==hash)throw Error('Canvas source hash mismatch');return b;}
 for(const name of readdirSync(root).filter(n=>/^compact_.*_bounded_manifest\.json$/.test(n))){
  const path=join(root,name),raw=readFileSync(path),m=JSON.parse(raw);if(m.version!=='rq3-bounded-pages-v1'||m.layout.far_scale!==.75||m.layout.recent_scale!==1||m.layout.vertical_merge!==false||m.layout.far_pre_enlargement!==false)throw Error('Wrong bounded canvas protocol');
  if(m.pages.length!==m.output_image_count)throw Error('Page count mismatch');
  const segments=new Map();for(const p of m.source_pdfs){artifact(p.path,p.sha256);segments.set(p.segment,p.page_dimensions.length);}
  const seen=new Set();
  for(const p of m.pages){const id=p.segment+':'+p.page_index;if(seen.has(id)||p.segment_pages!==segments.get(p.segment))throw Error('Incomplete page manifest');seen.add(id);const scale=p.segment==='history'?.75:1;if(p.scale!==scale||p.detail!=='high')throw Error('Wrong page scale/detail');
   const raw=artifact(p.raw_path,p.raw.sha256),source=artifact(p.path,p.output.sha256);const a=dimensions(raw),b=dimensions(source);if(a.width!==p.raw.dimensions[0]||a.height!==p.raw.dimensions[1]||b.width!==p.output.dimensions[0]||b.height!==p.output.dimensions[1]||b.width!==Math.max(1,Math.floor(a.width*scale))||b.height!==Math.max(1,Math.floor(a.height*scale)))throw Error('Page dimensions changed');result.add(p.output.sha256);}
  for(const [seg,count] of segments)for(let i=1;i<=count;i++)if(!seen.has(seg+':'+i))throw Error('Omitted bounded page');verified.set(resolve(path),{sha:sha(raw),value:m});
 }
 for(const name of readdirSync(root).filter(n=>/^compact_.*_transport_manifest\.json$/.test(n))){
  const m=JSON.parse(readFileSync(join(root,name))),source=verified.get(resolve(m.source_bounded_manifest));
  if(!source||source.sha!==m.source_bounded_manifest_sha256||m.version!=='bounded-canvas-lossless-webp-v1'||m.native_images_encoded!==0||m.pages.length!==source.value.pages.length)throw Error('Unbound lossless transport');
  m.pages.forEach((p,i)=>{if(p.source_sha256!==source.value.pages[i].output.sha256||!p.rgba_pixel_identical||p.resolution_changed!==false||p.encoder_parameters?.lossless!==true)throw Error('Lossless source proof changed');artifact(p.source_path,p.source_sha256);const b=artifact(p.path,p.output_sha256),dim=dimensions(b);if(dim.width!==p.dimensions[0]||dim.height!==p.dimensions[1])throw Error('Encoded geometry changed');result.add(p.output_sha256);});
 }
 const signature=sha(Buffer.from(readdirSync(root).filter(n=>/^compact_.*_(bounded|transport)_manifest\.json$/.test(n)).sort().map(n=>n+':'+sha(readFileSync(join(root,n)))).join('\n')));
 if(result.size&&pixelVerified.get(resolve(root))!==signature){
  if(!process.env.ACL_BOUNDED_PYTHON)throw Error('Bounded pixel verifier Python absent');
  const verifier=fileURLToPath(new URL('./dsh_bounded_registry_v1.py',import.meta.url));
  const check=spawnSync(process.env.ACL_BOUNDED_PYTHON,[verifier,resolve(root)],{encoding:'utf8',timeout:120000,maxBuffer:4194304});
  if(check.status!==0)throw Error('Hermes pixel/source registry verification failed');
  const hashes=JSON.parse(check.stdout);if(hashes.length!==result.size||hashes.some(h=>!result.has(h)))throw Error('Hermes registry hashes differ');
  pixelVerified.set(resolve(root),signature);
 }
 return result;
}
export function inspectBody(raw,canvases){
 const b=Buffer.isBuffer(raw)?raw:typeof raw==='string'?Buffer.from(raw):null;
 const row={version:'dsh-bounded-wire-v1',body_bytes:b?.length??null,images:[],violations:[],payload_modified:false};
 if(!b){row.violations.push('uninspectable_body');return row;}
 row.body_sha256=sha(b);if(b.length>8*1024*1024)row.violations.push('body_exceeds_8_mib');
 let payload;try{payload=JSON.parse(b);}catch{row.violations.push('invalid_json');return row;}
 for(const m of payload.messages??[])for(const p of Array.isArray(m.content)?m.content:[]){
  if(['image','input_image'].includes(p.type)){row.violations.push('unsupported_image');continue;}if(p.type!=='image_url')continue;
  const url=typeof p.image_url==='string'?p.image_url:p.image_url?.url;const match=/^data:image\/[a-zA-Z0-9.+-]+;base64,([A-Za-z0-9+/=]+)$/.exec(url??'');
  if(!match){row.violations.push('unverifiable_image');continue;}
  try{const data=Buffer.from(match[1],'base64');const hash=sha(data),d=dimensions(data),canvas=canvases.has(hash);row.images.push({sha256:hash,bytes:data.length,...d,rendered_canvas:canvas});if(canvas&&(Math.max(d.width,d.height)>2048||d.width*d.height>2097152))row.violations.push('canvas_exceeds_geometry');}catch{row.violations.push('invalid_inline_image');}
 }
 row.image_count=row.images.length;if(row.image_count>32)row.violations.push('image_count_exceeds_32');return row;
}
const root=process.env.ACL_BOUNDED_CANVAS_ROOT,ledger=process.env.ACL_BOUNDED_WIRE_LEDGER;
if(root||ledger){
 if(!root||!ledger)throw Error('Incomplete bounded wire environment');mkdirSync(dirname(ledger),{recursive:true});const original=globalThis.fetch;
 globalThis.fetch=async function(input,init){
  const url=new URL(typeof input==='string'?input:input.url);if(!url.pathname.endsWith('/chat/completions'))return original.call(this,input,init);
  let raw=init?.body;if(raw===undefined&&input instanceof Request)raw=await input.clone().text();let row;
  try{row=inspectBody(raw,registry(root));}catch(error){row={version:'dsh-bounded-wire-v1',violations:['registry_error'],error_type:error.name};}
  row.observed_at_unix=Date.now()/1000;row.network_send_authorized=row.violations.length===0;appendFileSync(ledger,JSON.stringify(row)+'\n');if(!row.network_send_authorized)throw Error('Bounded DSH wire rejected: '+row.violations.join(','));return original.call(this,input,init);
 };
}
