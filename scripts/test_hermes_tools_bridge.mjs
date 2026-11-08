import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { admitResult, registerTools, parameterSpec, invokeBridge } from '../plugins/dsh-local-web/hermes-tools-v2.mjs';

test('native image admission preserves surrounding text, duplicate images and metadata', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'hermes-tools-'));
  try {
    const data = Buffer.from('fixture-image-bytes');
    const path = join(dir, 'source.png'); await writeFile(path, data);
    const sha256 = createHash('sha256').update(data).digest('hex');
    const refs = [{ attachmentId: 'first' }, { attachmentId: 'second' }];
    const ctx = { attachments: {
      saveImages: async images => { assert.equal(images.length, 2); assert.deepEqual(images[0].data, data); return refs; },
      readImage: async () => ({ data }),
    } };
    const image = { type: 'image', path, sha256, media_type: 'image/png', width: 10, height: 10, detail: 'auto' };
    const result = { tool: 'image_crop', call_id: 'crop-1', handler_seconds: 0.1,
      metadata: { source: 'input.png', bbox: [1, 2, 3, 4] },
      content: [{ type: 'text', text: 'before' }, image, { type: 'text', text: 'between' }, image] };
    const actual = await admitResult(ctx, result, {});
    assert.deepEqual(actual.content, [{ type: 'text', text: 'before' }, { type: 'image', attachment: refs[0], aclImageDetail: 'auto' },
      { type: 'text', text: 'between' }, { type: 'image', attachment: refs[1], aclImageDetail: 'auto' }]);
    assert.equal(actual.images[0].sha256, sha256);
    assert.deepEqual(actual.metadata, result.metadata);
    ctx.attachments.readImage = async () => ({ data: Buffer.from('changed') });
    await assert.rejects(admitResult(ctx, result, {}), /normalization changed/);
    await writeFile(path, 'corrupt');
    await assert.rejects(admitResult(ctx, result, {}), /artifact changed/);
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test('real DSH definitions register Hermes vocabulary and render text verbatim', async () => {
  const definitions = [];
  const ctx = { tools: { register: tool => definitions.push(tool) }, attachments: {} };
  const schema = { name: 'web_search', description: 'search', parameters: { type: 'object',
    properties: { query: { type: 'string' }, limit: { type: 'integer', minimum: 1, maximum: 100, default: 5 } }, required: ['query'] } };
  const text = '{"success":true,"data":{"web":[]}}';
  registerTools(ctx, { timeoutMs: 1000 }, [schema], async (_config, request) => ({
    tool: request.tool, call_id: request.call_id, handler_seconds: 0.01,
    content: [{ type: 'text', text }], metadata: {},
  }));
  const tool = definitions[0];
  assert.deepEqual(tool.parameters.required, ['query']);
  assert.equal(tool.parameters.properties.query.type, 'string');
  const value = await tool.execute({ query: 'actual query' }, { callId: 'id', signal: new AbortController().signal });
  assert.deepEqual(tool.output.render({}, value), [{ type: 'text', text }]);
  await assert.rejects(tool.execute({ queries: ['wrong API'] }, {}), /query/);
  const padding = parameterSpec({ properties: { padding: { anyOf: [{ type: 'number' }, { type: 'array', items: { type: 'number' }, minItems: 2, maxItems: 2 }] } } });
  assert.equal(padding.padding.oneOf.length, 2);
});

test('subprocess cancellation terminates a pending bridge', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'hermes-bridge-cancel-'));
  try {
    const script = join(dir, 'wait.mjs'); await writeFile(script, 'setTimeout(()=>{},60000);');
    const controller = new AbortController();
    const pending = invokeBridge({ python: process.execPath, bridge: script, workspace: dir, timeoutMs: 2000, maxResultBytes: 1024 }, {}, controller.signal);
    setTimeout(() => controller.abort(), 30);
    await assert.rejects(pending, /Hermes bridge failed/);
  } finally { await rm(dir, { recursive: true, force: true }); }
});
