import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Context } from '../deepseekHarness/vendor/cordis/lib/index.js';
import LlmRuntime, { LlmAdapter, createUserMessage, createMessage, createToolResultMessage } from '../deepseekHarness/packages/llm/llm/lib/index.js';
import { Session } from '../deepseekHarness/packages/core/session/lib/index.js';
import ProjectionRegistry from '../deepseekHarness/packages/session/session-projection/lib/index.js';
import TokenMeter from '../deepseekHarness/packages/llm/token-meter/lib/index.js';
import { apply } from '../plugins/dsh-context/index.mjs';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

class Adapter extends LlmAdapter {
  async resolveModel(provider, model) {
    return { provider, id: model, name: model, context: { contextWindow: 131072 } };
  }
  async *stream(options) {
    assert.equal(options.messages.flatMap(message => message.content).some(block => block.type === 'image'), false);
    yield { type: 'block-start', index: 0, blockType: 'text' };
    yield { type: 'block-end', index: 0, block: { type: 'text', text: 'A compact record of prior facts.' } };
    yield { type: 'finish', reason: { kind: 'stop' } };
  }
}

test('visual policy renders and commits images with an observed compression event', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'acl-visual-policy-'));
  const ctx = new Context();
  new LlmRuntime(ctx); new ProjectionRegistry(ctx); new TokenMeter(ctx);
  ctx.llm.registerAdapter(['test'], new Adapter());
  ctx.provide('attachments');
  ctx.set('attachments', { async saveImages(images) {
    assert.ok(images.length > 0);
    assert.ok(images.every(image => image.data.length > 100 && image.mediaType === 'image/png'));
    return images.map((image, i) => ({ attachmentId: `sha256:${String(i).padStart(64, '0')}`,
      mediaType: image.mediaType, bytes: image.data.length, width: 1000, height: 1400 }));
  } });
  let Engine, options;
  apply({ plugin(engine, config) { Engine = engine; options = config; } }, {
    strategy: 'visual_native', auto: false, postCompressionBudget: 16000,
    metricsDir: directory, python: process.env.ACL_PYTHON || 'python',
    renderer: fileURLToPath(new URL('../scripts/render_dsh_history.py', import.meta.url)),
    historyScale: 1, fontSize: 16,
  });
  try {
    const engine = new Engine(ctx, options);
    const session = Session.create('visual-render-test');
    session.append('turn/start', { turn: 1 });
    session.append('user/message', createUserMessage({content: [{ type: 'text', text: 'Recall code 7319.' }],
      source: { kind: 'user' } }), { surfaceOp: 'append' });
    session.append('step/start', { turn: 1, step: 1 });
    session.append('request/header', {header: {config: {provider: 'test', model: 'test'}}, reason: 'initial'});
    session.append('assistant/message', {turn: 1, step: 1, stream: [], message: createMessage({
      role: 'assistant', source: {kind: 'model', provider: 'test', model: 'test'},
      content: [{type: 'tool-call', id: 'fixture-call', name: 'web_fetch', arguments: '{}'}],
    })}, {surfaceOp: 'append'});
    session.append('tool/call', {turn: 1, step: 1, callId: 'fixture-call', name: 'web_fetch', arguments: '{}'});
    session.append('tool/result', {turn: 1, step: 1, message: createToolResultMessage({
      callId: 'fixture-call', content: [{type: 'text', text: 'Observed fact: code 7319. '.repeat(40)}], isError: false,
    })}, {surfaceOp: 'append'});
    session.append('step/end', {turn: 1, step: 1});
    session.append('turn/end', {turn: 1, reason: {kind: 'completed'}});
    session.append('turn/start', {turn: 2});
    session.append('user/message', createUserMessage({content: [{type: 'text', text: 'Continue.'}],
      source: {kind: 'user'}}), {surfaceOp: 'append'});
    const result = await engine.compactIfNeeded({session, options: {provider: 'test', model: 'test'}},
      'context-overflow', new AbortController().signal);
    assert.ok(result.compactionId);
    assert.ok(session.deriveMessages().flatMap(m => m.content).some(b => b.type === 'image'));
    const compression = JSON.parse((await readFile(join(directory, 'compression.jsonl'), 'utf8')).trim());
    assert.equal(compression.valid, true);
    assert.equal(compression.compaction_id, result.compactionId);
    const render = JSON.parse((await readFile(join(directory, 'render.jsonl'), 'utf8')).trim());
    assert.ok(render.render_seconds > 0);
    assert.match(render.renderer, /PDF\/Poppler/);
  } finally {
    await ctx.fiber.dispose();
    await rm(directory, {recursive: true, force: true});
  }
});

for (const strategy of ['sliding_window_native', 'summarize_native', 'discard']) {
test(`${strategy} commits the selected evidence to the durable DSH surface`, async () => {
  const ctx = new Context();
  new LlmRuntime(ctx);
  new ProjectionRegistry(ctx);
  new TokenMeter(ctx);
  ctx.llm.registerAdapter(['test'], new Adapter());
  let Engine, options;
  apply({ plugin(engine, config) { Engine = engine; options = config; } }, {
    strategy, auto: false, postCompressionBudget: 16000,
  });
  const engine = new Engine(ctx, options);
  const session = Session.create('native-window-test');
  const image = { type: 'image', attachment: {
    attachmentId: `sha256:${'a'.repeat(64)}`, mediaType: 'image/png', bytes: 1, width: 1, height: 1,
  } };
  session.append('turn/start', { turn: 1 });
  session.append('user/message', createUserMessage({
    content: [{ type: 'text', text: 'Original task' }], source: { kind: 'user' },
  }), { surfaceOp: 'append' });
  session.append('step/start', { turn: 1, step: 1 });
  session.append('request/header', { header: { config: { provider: 'test', model: 'test' } }, reason: 'initial' });
  session.append('assistant/message', { turn: 1, step: 1, stream: [], message: createMessage({
    role: 'assistant', source: { kind: 'model', provider: 'test', model: 'test' },
    content: [{ type: 'text', text: 'Old intermediate reasoning. '.repeat(1500) }],
  }) }, { surfaceOp: 'append' });
  session.append('step/end', { turn: 1, step: 1 });
  session.append('turn/end', { turn: 1, reason: { kind: 'completed' } });
  session.append('turn/start', { turn: 2 });
  session.append('user/message', createUserMessage({ content: [image], source: { kind: 'user' } }), { surfaceOp: 'append' });
  const nodes = [...session.surface.nodes];
  const result = await engine.compactRegion(nodes[0], nodes.at(-1), {
    session, options: { provider: 'test', model: 'test' },
  }, new AbortController().signal);
  assert.ok(result.compactionId);
  const messages = session.deriveMessages();
  assert.equal(messages.length, 1);
  assert.equal(messages[0].source.kind, 'compact-checkpoint');
  assert.deepEqual(messages[0].content.filter(block => block.type === 'image'), strategy === 'discard' ? [] : [image]);
  const text = messages[0].content.filter(block => block.type === 'text').map(block => block.text).join(' ');
  assert.ok(text.includes('Original task'));
  assert.equal(text.includes('Old intermediate reasoning'), false);
  await ctx.fiber.dispose();
});
}
