import test from 'node:test';
import assert from 'node:assert/strict';
import {inspect,validate,isNativeTitleRequest} from './dsh_wire_image_guard.mjs';
const png=Buffer.alloc(24);Buffer.from([137,80,78,71,13,10,26,10]).copy(png);png.writeUInt32BE(100,16);png.writeUInt32BE(200,20);
const payload={messages:[{role:'user',content:[{type:'image_url',image_url:{url:'data:image/png;base64,'+png.toString('base64')}}]}]};
test('captures final image_url metadata with omitted detail explicitly',()=>{const [i]=inspect(payload);assert.equal(i.width,100);assert.equal(i.height,200);assert.equal(i.detail_present,false);assert.equal(i.type,'image_url');});
test('missing and altered reviewed image sets rejected',()=>{const images=inspect(payload);assert.throws(()=>validate([],{wire_sha256:[images[0].sha256]}));assert.throws(()=>validate(images,{wire_sha256:['different']}));validate(images,{wire_sha256:[images[0].sha256]});});
test('remote URLs and empty encoded image rejected',()=>{assert.throws(()=>inspect({messages:[{content:[{type:'image_url',image_url:{url:'https://example.com/image.png'}}]}]}));assert.throws(()=>inspect({messages:[{content:[{type:'image_url',image_url:{url:'data:image/png;base64,'}}]}]}));});

test('title bypass requires exact system and two-message framing, never quoted history',()=>{
 const system=['Create a concise title for an AI coding-assistant session from the supplied human messages.',
 'Return only the title on one line, **in plain text of natural language**, with no quotes, prefix, explanation, Markdown, XML, or terminal control codes. No code is allowed.',
 'Use the language of the messages.','Aim for about 8 words in non-CJK languages or 16 CJK characters.',
 'If the messages give little to name, still return a short best-effort title, such as Greeting, instead of explaining.'].join('\n');
 const user='Generate the session title from this JSON array of human messages:\n[]';
 assert.equal(isNativeTitleRequest({messages:[{role:'system',content:system},{role:'user',content:user}]}),true);
 assert.equal(isNativeTitleRequest({messages:[{role:'user',content:user}]}),false);
 assert.equal(isNativeTitleRequest({messages:[{role:'system',content:'ordinary agent instructions'},{role:'user',content:user}]}),false);
 assert.equal(isNativeTitleRequest({messages:[{role:'system',content:system},{role:'user',content:'Quoted history: '+user}]}),false);
 assert.equal(isNativeTitleRequest({messages:[{role:'system',content:system},{role:'user',content:user},{role:'tool',content:user}]}),false);
});
