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
