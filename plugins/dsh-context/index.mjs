/** Research policies use DSH's native compaction transaction and agent loop. */
import { BasicCompactionEngine } from '../../deepseekHarness/packages/compaction/compaction-basic/lib/index.js';
import { spawn } from 'node:child_process';
import { appendFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { separateImages, originalTask } from './content.mjs';

export function apply(ctx, config) {
  const { strategy, python, renderer, historyScale, fontSize = 8, metricsDir, postCompressionBudget, ...policy } = config;
  if (!['none', 'discard', 'summarize', 'summarize_native', 'sliding_window_native', 'visual_native'].includes(strategy)) {
    throw new Error(`Unsupported research compaction strategy: ${strategy}`);
  }
  class ResearchCompaction extends BasicCompactionEngine {
    static inject = [...BasicCompactionEngine.inject, 'attachments'];
    researchStrategy = strategy;
    tasks = new WeakMap();
    histories = new WeakMap();
    renderedIds = new Set();
    invalid = new WeakMap();

    constructor(context, options) {
      super(context, options);
      context.on('agent/pre-step', async ({ agent }, next) => {
        const decision = await next();
        const error = this.invalid.get(agent.session);
        if (error) throw error;
        return decision;
      });
    }

    async compactIfNeeded(agent, trigger, signal) {
      try {
        return await this.compactResearch(agent, trigger, signal);
      } catch (error) {
        this.invalid.set(agent.session, error);
        throw error;
      }
    }

    async compactResearch(agent, trigger, signal) {
      if (strategy === 'none') return null;
      let result;
      if (strategy === 'discard') {
        const header = agent.session.requestHeader();
        if (!header) return null;
        const measurement = this.ctx.tokenMeter.measure(agent.session);
        const threshold = Number(process.env.ACL_COMPRESSION_TRIGGER);
        if (!(threshold > 0)) throw new Error('Missing configured compression threshold');
        if (trigger === 'pressure' && measurement.totalTokens < threshold) return null;
        const messages = agent.session.deriveMessages();
        const nodes = agent.session.surface.nodes;
        if (messages.length !== nodes.length) throw new Error('Discard requires aligned surface messages');
        const start = messages[0]?.role === 'system' ? 1 : 0;
        if (nodes.length - start < 2) return null;
        result = await this.compactRegion(nodes[start], nodes.at(-1), agent, signal);
      } else {
        result = await super.compactIfNeeded(agent, trigger, signal);
      }
      if (result) {
        const measurement = this.ctx.tokenMeter.measure(agent.session);
        if (!Number.isInteger(postCompressionBudget) || postCompressionBudget <= 0) {
          throw new Error('A positive postCompressionBudget is required for research runs');
        }
        const valid = measurement.totalTokens <= postCompressionBudget;
        if (metricsDir) {
          await mkdir(metricsDir, { recursive: true });
          await appendFile(join(metricsDir, 'compression.jsonl'), JSON.stringify({
            session_id: agent.session.id, strategy, trigger,
            post_compression_tokens: measurement.totalTokens,
            token_measurement: 'dsh_token_meter_estimate',
            budget: postCompressionBudget, valid,
            compaction_id: result.compactionId,
          }) + '\n');
        }
        if (!valid) {
          const error = new Error('Post-compression budget exceeded; controlled run invalid');
          this.invalid.set(agent.session, error);
          throw error;
        }
      }
      return result;
    }

    async summarize(input, agent, signal) {
      const { text, images: allImages } = separateImages(input.messages);
      const images = allImages.filter(block => !this.renderedIds.has(block.attachment.attachmentId));
      if (images.some(block => block.offloaded)) throw new Error('Native evidence has been offloaded; invalid controlled run');
      let task = this.tasks.get(agent.session);
      if (!task) {
        task = originalTask(strategy === 'discard' ? input.messages : text);
        this.tasks.set(agent.session, task);
      }
      const target = agent.session.requestHeader()?.config;
      if (!target) throw new Error('Compaction requires a routed model');
      if (strategy === 'discard') {
        return { summary: task, provider: target.provider, model: target.model };
      }
      if (strategy === 'sliding_window_native') {
        return { summary: [...task, ...images], provider: target.provider, model: target.model };
      }
      if (strategy === 'visual_native') {
        if (!python || !renderer || !metricsDir || !(historyScale > 0 && historyScale <= 1)) {
          throw new Error('Visual rendering requires python, renderer, metricsDir and historyScale');
        }
        const previous = this.histories.get(agent.session) ?? [];
        const history = [...previous, ...text.filter(message =>
          message.role !== 'system' && message.source?.kind !== 'compact-checkpoint')];
        const rendered = await renderHistory(python, renderer, { messages: history, history_scale: historyScale, font_size: fontSize }, signal);
        const refs = await this.ctx.attachments.saveImages(rendered.images.map(url => ({
          data: Buffer.from(url.split(',')[1], 'base64'), mediaType: 'image/png',
        })));
        this.histories.set(agent.session, history);
        for (const ref of refs) this.renderedIds.add(ref.attachmentId);
        await mkdir(metricsDir, { recursive: true });
        await appendFile(join(metricsDir, 'render.jsonl'), JSON.stringify({
          session_id: agent.session.id, render_seconds: rendered.render_seconds,
          renderer: rendered.renderer, font_size: fontSize, history_scale: historyScale,
          stats: rendered.stats, native_image_ids: images.map(block => block.attachment.attachmentId),
        }) + '\n');
        return { summary: [...task, ...refs.map(attachment => ({ type: 'image', attachment })), ...images],
          provider: target.provider, model: target.model };
      }
      const result = await super.summarize({ ...input, messages: text }, agent, signal);
      return {
        ...result,
        summary: [...task, ...result.summary, ...(strategy === 'summarize_native' ? images : [])],
      };
    }
  }
  ctx.plugin(ResearchCompaction, policy);
}

/** Invoke the shared renderer without a shell; cancellation kills the child. */
function renderHistory(python, renderer, payload, signal) {
  return new Promise((resolve, reject) => {
    const child = spawn(python, [renderer], { stdio: ['pipe', 'pipe', 'pipe'], signal });
    const output = [];
    const errors = [];
    child.stdout.on('data', data => output.push(data));
    child.stderr.on('data', data => errors.push(data));
    child.on('error', reject);
    child.stdin.on('error', reject);
    child.on('close', code => {
      if (code !== 0) return reject(new Error(`Renderer exited ${code}: ${Buffer.concat(errors).toString().slice(-1000)}`));
      try { resolve(JSON.parse(Buffer.concat(output).toString())); } catch (error) { reject(error); }
    });
    child.stdin.end(JSON.stringify(payload));
  });
}
