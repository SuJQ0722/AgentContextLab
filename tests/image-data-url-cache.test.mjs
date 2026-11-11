import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {ImageDataURLCache,imageDataURL} from '../plugins/dsh-context/image-data-url-cache.mjs';
import {inlineImagesForRenderer} from '../plugins/dsh-context/content.mjs';
const bytes=Buffer.from('unchanged pixels');
const ref={attachmentId:'sha256:'+createHash('sha256').update(bytes).digest('hex'),mediaType:'image/png'};
test('reuses verified encoding across turns, keeps positions and separate stores',async()=>{
 let reads=0;const store={async readImage(){reads++;return {ref,data:bytes};}};
 const messages=[{role:'tool',content:[{type:'text',text:'before'},{type:'image',attachment:ref},{type:'text',text:'after'}]}];
 const first=await inlineImagesForRenderer(messages,store);
 const second=await inlineImagesForRenderer(messages,store);
 assert.deepEqual(second,first);assert.equal(reads,1);assert.deepEqual(first[0].content.map(x=>x.type),['text','image_url','text']);
 assert.equal(first[0].content[1].image_url.url,'data:image/png;base64,'+bytes.toString('base64'));
 await imageDataURL({async readImage(){reads++;return {ref,data:bytes};}},ref);assert.equal(reads,2);
 const controller=new AbortController();controller.abort();await assert.rejects(imageDataURL(store,ref,controller.signal));
});
test('rejects identity mismatch and never caches failed reads',async()=>{
 let count=0;const store={async readImage(){return {ref,data:++count===1?Buffer.from('corrupt'):bytes};}};
 await assert.rejects(imageDataURL(store,ref),/SHA-256/);
 assert.equal(await imageDataURL(store,ref),'data:image/png;base64,'+bytes.toString('base64'));
 assert.equal(count,2);
});
test('LRU enforces the byte bound and does not retain oversized entries',()=>{
 const cache=new ImageDataURLCache(6);cache.set('a','aaa');cache.set('b','bbb');cache.get('a');cache.set('c','ccc');
 assert.equal(cache.get('b'),undefined);assert.equal(cache.get('a'),'aaa');assert.equal(cache.bytes,6);
 cache.set('huge','x'.repeat(7));assert.equal(cache.get('huge'),undefined);assert.equal(cache.bytes,6);
 cache.set('a','a');assert.equal(cache.bytes,4);
});
