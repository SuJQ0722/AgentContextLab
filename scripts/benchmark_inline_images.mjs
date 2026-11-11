/** Offline image preparation benchmark. Input: JSON array of existing local files. */
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {imageDataURL} from '../plugins/dsh-context/image-data-url-cache.mjs';
const [manifest,out]=process.argv.slice(2);if(!manifest||!out)throw Error('Usage: node benchmark_inline_images.mjs images.json result.json');
const paths=JSON.parse(await readFile(manifest,'utf8'));if(!Array.isArray(paths)||paths.length<1||paths.length>10)throw Error('Provide 1–10 image paths');
const source=await Promise.all(paths.map(async path=>({path,data:await readFile(path)})));
const refs=source.map(x=>({attachmentId:'sha256:'+createHash('sha256').update(x.data).digest('hex'),mediaType:x.path.endsWith('.webp')?'image/webp':x.path.endsWith('.jpg')?'image/jpeg':'image/png'}));
const byId=new Map(source.map((x,i)=>[refs[i].attachmentId,x]));let reads=0;
const store={async readImage(ref){reads++;return {ref,data:await readFile(byId.get(ref.attachmentId).path)};}};
const url=(data,i)=>`data:${refs[i].mediaType};base64,${data.toString('base64')}`;
const memoryURLs=source.map((x,i)=>url(x.data,i));
const message=urls=>({messages:[{role:'user',content:urls.map(url=>({type:'image_url',image_url:{url,detail:'high'}}))}]});
const expectedJSON=JSON.stringify(message(memoryURLs));
const methods={
 path_read_encode:async()=>{const values=[];for(let i=0;i<source.length;i++)values.push(url(await readFile(source[i].path),i));return values;},
 in_memory_encode:async()=>source.map((x,i)=>url(x.data,i)),
 verified_cache_hit:async()=>{const values=[];for(const ref of refs)values.push(await imageDataURL(store,ref));return values;},
 reused_data_urls:async()=>memoryURLs,
 json_serialize_only:async()=>JSON.stringify(message(memoryURLs)),
};
const initial=performance.now();await methods.verified_cache_hit();const firstVerifiedMs=performance.now()-initial;
const samples=Object.fromEntries(Object.keys(methods).map(x=>[x,[]]));
for(let iteration=0;iteration<30;iteration++){
 const names=Object.keys(methods);for(let k=0;k<names.length;k++){
  const name=names[(k+iteration)%names.length],started=performance.now(),result=await methods[name]();samples[name].push(performance.now()-started);
  if(iteration===0&&name!=='json_serialize_only'&&JSON.stringify(message(result))!==expectedJSON)throw Error('Prepared wire bytes changed');
 }
}
const stats=Object.fromEntries(Object.entries(samples).map(([name,values])=>{const sorted=values.toSorted((a,b)=>a-b);return[name,{n:values.length,median_ms:(sorted[14]+sorted[15])/2,p95_ms:sorted[Math.ceil(sorted.length*.95)-1]}];}));
const result={version:1,measurement:'local client preparation only; zero model/API calls; warm filesystem cache, not cold disk',image_count:source.length,raw_bytes:source.reduce((sum,x)=>sum+x.data.length,0),data_url_bytes:memoryURLs.reduce((sum,x)=>sum+x.length,0),json_bytes:Buffer.byteLength(expectedJSON),first_verified_cache_fill_ms:firstVerifiedMs,attachment_reads_including_fill:reads,cache_limit_bytes:16*1024*1024,stats,source:source.map((x,i)=>({path:x.path,sha256:refs[i].attachmentId.slice(7),bytes:x.data.length}))};
await writeFile(out,JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({...result,source:undefined},null,2));
