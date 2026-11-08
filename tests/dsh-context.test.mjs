import assert from 'node:assert/strict';
import { test } from 'node:test';
import { separateImages, originalTask } from '../plugins/dsh-context/content.mjs';

test('native image payloads and order survive without reaching text summarization', () => {
  const image = { type: 'image', attachment: { attachmentId: 'sha256:abc', width: 1024, height: 768 } };
  const messages = [{ role: 'user', content: [{ type: 'text', text: 'task' }, image] }];
  const split = separateImages(messages);
  assert.deepEqual(split.images, [image]);
  assert.equal(split.images[0], image);
  assert.equal(messages[0].content[1], image);
  assert.equal(split.text[0].content.some(block => block.type === 'image'), false);
  assert.deepEqual(originalTask(split.text), split.text[0].content);
});

test('repeated attachment references occupy one retained image slot', () => {
  const image = { type: 'image', attachment: { attachmentId: 'same' } };
  assert.equal(separateImages([{ role: 'user', content: [image, image] }]).images.length, 1);
});

import { inlineImagesForRenderer } from '../plugins/dsh-context/content.mjs';

test('visual rendering keeps each image at its original text position and resolves bytes once', async () => {
  const ref = {attachmentId: 'sha256:fixture', mediaType: 'image/png'};
  const image = {type: 'image', attachment: ref};
  const bytes = Buffer.from('actual admitted image bytes');
  let reads = 0;
  const store = {async readImage(got) { assert.equal(got, ref); reads++; return {ref, data: bytes}; }};
  const original = [{id:'tool-result-7', role:'tool', toolCallId:'crop-7', content:[
    {type:'text',text:'Crop coordinates (10,20,90,80).'}, image,
    {type:'text',text:'Compare this magnified chart.'}, image,
  ]}];
  const converted = await inlineImagesForRenderer(original, store, new AbortController().signal);
  assert.deepEqual(converted[0].content.map(b=>b.type), ['text','image_url','text','image_url']);
  assert.equal(converted[0].content[1].image_url.url,'data:image/png;base64,'+bytes.toString('base64'));
  assert.equal(converted[0].content[1].source_attachment_id,ref.attachmentId);
  assert.notEqual(converted[0].content[1].source_occurrence,converted[0].content[3].source_occurrence);
  assert.equal(reads,1);
  assert.equal(original[0].content[1],image);
  assert.equal(converted[0].toolCallId,'crop-7');
});

test('visual rendering rejects offloaded or missing evidence rather than captioning or dropping it', async () => {
  const ref={attachmentId:'sha256:fixture',mediaType:'image/png'};
  await assert.rejects(inlineImagesForRenderer([{role:'tool',content:[{type:'image',attachment:ref,offloaded:true}]}],{}),/offloaded/);
  await assert.rejects(inlineImagesForRenderer([{role:'tool',content:[{type:'image',attachment:ref}]}],{async readImage(){return {ref,data:Buffer.alloc(0)}}}),/missing/);
});
