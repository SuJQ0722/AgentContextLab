/** Bounded, store-scoped cache for immutable SHA-256 attachment bytes.
 * Does not change pixels, image order, detail, or provider prefix-cache policy.
 */
import {createHash} from 'node:crypto';
export class ImageDataURLCache {
 constructor(maxBytes=16*1024*1024){this.maxBytes=maxBytes;this.bytes=0;this.entries=new Map();}
 get(key){const value=this.entries.get(key);if(value!==undefined){this.entries.delete(key);this.entries.set(key,value);}return value;}
 set(key,value){
  const size=Buffer.byteLength(value,'ascii');if(size>this.maxBytes)return;
  if(this.entries.has(key)){this.bytes-=this.entries.get(key).length;this.entries.delete(key);}
  while(this.bytes+size>this.maxBytes){const oldest=this.entries.keys().next().value;this.bytes-=this.entries.get(oldest).length;this.entries.delete(oldest);}
  this.entries.set(key,value);this.bytes+=size;
 }
}
const stores=new WeakMap();
export async function imageDataURL(attachments,ref,signal){
 signal?.throwIfAborted();
 const hash=/^sha256:([a-f0-9]{64})$/.exec(ref.attachmentId)?.[1];
 const key=`${ref.attachmentId}:${ref.mediaType??''}`;
 let cache=stores.get(attachments);if(!cache){cache=new ImageDataURLCache();stores.set(attachments,cache);}
 if(hash){const hit=cache.get(key);if(hit!==undefined)return hit;}
 const stored=await attachments.readImage(ref,signal);signal?.throwIfAborted();
 if(!stored?.data?.length)throw new Error('Visual evidence bytes are missing');
 const mediaType=stored.ref?.mediaType??ref.mediaType;
 if(!['image/png','image/jpeg','image/webp','image/gif'].includes(mediaType))throw new Error(`Unsupported visual evidence media type: ${mediaType}`);
 // No copy when the attachment API already provides a Buffer.
 const bytes=Buffer.isBuffer(stored.data)?stored.data:Buffer.from(stored.data);
 if(hash&&createHash('sha256').update(bytes).digest('hex')!==hash)throw new Error('Visual evidence does not match its SHA-256 attachment identity');
 const url=`data:${mediaType};base64,${bytes.toString('base64')}`;
 if(hash)cache.set(key,url);
 return url;
}
