/** Recorded image admission and per-call instrumentation for bounded experiments. */
import { readFile, mkdir, appendFile } from 'node:fs/promises';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { createUserMessage } from '../../deepseekHarness/packages/llm/llm/lib/index.js';

export const inject = ['attachments', 'llm', 'tools'];

export function apply(ctx, config) {
  const { inputFile, metricsDir, maxSteps } = config;
  if (!inputFile || !metricsDir || !Number.isInteger(maxSteps) || maxSteps < 1) {
    throw new Error('Evaluation requires inputFile, metricsDir and positive maxSteps');
  }
  const admitted = new WeakSet();
  const restricted = new WeakSet();
  async function log(file, record) {
    await mkdir(metricsDir, { recursive: true });
    await appendFile(join(metricsDir, file), JSON.stringify(record) + '\n');
  }
  ctx.on('agent/pre-step', async ({ agent, step, signal }, next) => {
    if (config.expectedStrategy) {
      const engine = agent.ctx.get('compaction');
      if (engine?.researchStrategy !== config.expectedStrategy) {
        throw new Error('Research compaction policy was not mounted; refusing model requests');
      }
      if (!admitted.has(agent.session)) await log('policy.jsonl', {
        timestamp: new Date().toISOString(), strategy: engine.researchStrategy,
        engine: engine.constructor.name, verified: true,
      });
    }
    await log('steps.jsonl', { timestamp: new Date().toISOString(), session_id: agent.session.id, step });
    if (step > maxSteps) {
      await log('limits.jsonl', { timestamp: new Date().toISOString(), kind: 'step_limit', step, maxSteps });
      throw new Error('Experiment step limit reached');
    }
    if (config.allowedTools && !restricted.has(agent)) {
      agent.ctx.tools.restrict({ allow: config.allowedTools });
      restricted.add(agent);
    }
    const decision = await next();
    if (decision.kind === 'reject') return decision;
    if (decision.messages.length === 0) return decision;
    if (!admitted.has(agent.session)) {
      const input = JSON.parse(await readFile(inputFile, 'utf8'));
      const index = decision.messages.findLastIndex(message => message.source.kind === 'user');
      if (index < 0) throw new Error('Evaluation requires an initial user task');
      const images = [];
      for (const image of input.images ?? []) {
        signal.throwIfAborted();
        const data = await readFile(image.path);
        images.push({ data, mediaType: image.media_type });
      }
      const refs = images.length ? await ctx.attachments.saveImages(images) : [];
      admitted.add(agent.session);
      await mkdir(metricsDir, { recursive: true });
      await appendFile(join(metricsDir, 'input.jsonl'), JSON.stringify({
        session_id: agent.session.id, image_ids: refs.map(ref => ref.attachmentId),
        question_id: input.question_id,
      }) + '\n');
      if (refs.length) return { ...decision, messages: decision.messages.map((message, position) =>
        position === index ? createUserMessage({
          content: [...message.content, ...refs.map(attachment => ({ type: 'image', attachment }))],
          source: message.source,
        }) : message) };
    }
    return decision;
  });
  ctx.on('llm/stream', async function* (options, next) {
    if (config.expectedStrategy && ctx.get('compaction')?.researchStrategy !== config.expectedStrategy) {
      throw new Error('Research compaction policy missing; refusing model request');
    }
    const start = performance.now();
    const startedAt = new Date().toISOString(), callId = randomUUID();
    let usage = null, finish = null, firstChunk = null, firstText = null, usageChunks = 0;
    await log('call-starts.jsonl', { call_id: callId, started_at: startedAt,
      session_id: options.sessionId, purpose: options.purpose ?? 'agent' });
    try {
      for await (const chunk of next()) {
        if (firstChunk === null) firstChunk = (performance.now() - start) / 1000;
        if (chunk.type === 'text-delta' && firstText === null) firstText = (performance.now() - start) / 1000;
        if (chunk.type === 'usage') { usage = chunk.usage; usageChunks++; }
        if (chunk.type === 'finish') finish = chunk.reason;
        yield chunk;
      }
    } finally {
      await mkdir(metricsDir, { recursive: true });
      await appendFile(join(metricsDir, 'calls.jsonl'), JSON.stringify({
        instrumentation_version: 2, call_id: callId, started_at: startedAt, ended_at: new Date().toISOString(),
        session_id: options.sessionId, provider: options.provider, model: options.model,
        purpose: options.purpose ?? 'agent', usage, finish,
        usage_chunks: usageChunks, first_chunk_seconds: firstChunk, first_text_delta_seconds: firstText,
        usage_source: 'pinned DSH llm-pi-ai normalized provider usage; reasoning folded into output',
        provider_request_id: null, provider_internal_latency_seconds: null,
        client_stream_seconds: (performance.now() - start) / 1000,
        timing_definition: 'DSH llm/stream wall time, including adapter retries; not provider-internal latency',
      }) + '\n');
    }
  });
}
