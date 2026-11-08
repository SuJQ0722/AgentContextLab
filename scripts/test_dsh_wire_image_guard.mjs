import test from 'node:test';
import assert from 'node:assert/strict';
import {inspect,validate,isNativeTitleRequest,dimensions,applyExpectedImageDetails} from './dsh_wire_image_guard.mjs';
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

test('preserved WebP and GIF geometry is audited instead of silently skipped',()=>{
 const gif=Buffer.alloc(10);gif.write('GIF89a');gif.writeUInt16LE(640,6);gif.writeUInt16LE(480,8);
 assert.deepEqual(dimensions(gif),{format:'gif',width:640,height:480});
 const x=Buffer.alloc(30);x.write('RIFF');x.write('WEBPVP8X',8);x.writeUIntLE(639,24,3);x.writeUIntLE(479,27,3);
 assert.deepEqual(dimensions(x),{format:'webp',width:640,height:480});
 const l=Buffer.alloc(25);l.write('RIFF');l.write('WEBPVP8L',8);l[20]=47;l.writeUInt32LE(639|(479<<14),21);
 assert.deepEqual(dimensions(l),{format:'webp',width:640,height:480});
 const v=Buffer.alloc(30);v.write('RIFF');v.write('WEBPVP8 ',8);Buffer.from([157,1,42]).copy(v,23);v.writeUInt16LE(640,26);v.writeUInt16LE(480,28);
 assert.deepEqual(dimensions(v),{format:'webp',width:640,height:480});
 assert.throws(()=>dimensions(Buffer.from('not-an-image')));
});

test('explicit detail adapter preserves image bytes/order and guard enforces final Hermes detail',()=>{
 const p=structuredClone(payload),before=inspect(p),expected={wire_sha256:before.map(x=>x.sha256),details:['low']};
 assert.throws(()=>validate(before,expected),/detail/);
 const changes=applyExpectedImageDetails(p,expected);assert.equal(changes.length,1);assert.equal(changes[0].before,null);
 const after=inspect(p);assert.equal(after[0].detail,'low');assert.equal(after[0].sha256,before[0].sha256);validate(after,expected);
});
