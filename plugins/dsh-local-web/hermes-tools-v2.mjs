/** Versioned Hermes handlers with native DSH tool-result image admission. */
import { spawn } from 'node:child_process';
import { readFile, mkdir, appendFile } from 'node:fs/promises';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { defineTool } from '../../deepseekHarness/packages/core/tools/lib/index.js';

export const inject = ['tools', 'attachments'];
export const TOOL_NAMES = ['web_search', 'web_extract', 'image_search', 'image_crop', 'image_zoom_in'];
const sha = bytes => createHash('sha256').update(bytes).digest('hex');

/** Adapt the schema vocabulary; handlers retain their original validation. */
export function parameterSpec(schema) {
  function node(value) {
    const result = {};
    for (const key of ['type', 'description', 'default', 'enum', 'const'])
      if (Object.hasOwn(value, key)) result[key] = value[key];
    if (value.minimum !== undefined || value.maximum !== undefined)
      result.description = `${result.description ?? ''} Hermes declared range: ${value.minimum ?? '-infinity'} to ${value.maximum ?? 'infinity'}; original handler validation/clamping applies.`.trim();
    if (value.items) result.items = node(value.items);
    if (value.anyOf) result.oneOf = value.anyOf.map(node);
    if (value.minItems !== undefined || value.maxItems !== undefined)
      result.description = `${result.description ?? ''} Hermes declared array length: ${value.minItems ?? 0} to ${value.maxItems ?? 'unbounded'}; original handler validation applies.`.trim();
    if (value.type === 'object') {
      result.properties = parameterSpec(value);
      result.additionalProperties = value.additionalProperties !== false;
    }
    return result;
  }
  return Object.fromEntries(Object.entries(schema.properties ?? {}).map(([key, value]) =>
    [key, { ...node(value), ...(schema.required?.includes(key) ? { required: true } : {}) }]));
}

/** One isolated tool invocation; cancellation terminates the child process. */
export function invokeBridge(config, request, signal, describe = false) {
  return new Promise((resolve, reject) => {
    const args = [config.bridge, '--workspace', config.workspace, ...(describe ? ['--describe'] : [])];
    const child = spawn(config.python, args, { env: process.env, stdio: ['pipe', 'pipe', 'pipe'] });
    let output = ''; let overflow = false; let finished = false;
    const stop = () => child.kill('SIGTERM');
    const timer = setTimeout(stop, config.timeoutMs);
    signal?.addEventListener('abort', stop, { once: true });
    if (signal?.aborted) stop();
    // Provider logs can contain URLs. Keep them out of exception messages and model output.
    child.stderr.resume();
    child.stdout.on('data', bytes => {
      output += bytes.toString('utf8');
      if (Buffer.byteLength(output) > config.maxResultBytes) { overflow = true; stop(); }
    });
    const finish = (error, result) => {
      if (finished) return;
      finished = true; clearTimeout(timer); signal?.removeEventListener('abort', stop);
      error ? reject(error) : resolve(result);
    };
    child.on('error', error => finish(error));
    child.on('close', (code, killedBy) => {
      if (code !== 0 || overflow) return finish(new Error(`Hermes bridge failed (${overflow ? 'output limit' : killedBy ?? code})`));
      try { finish(null, JSON.parse(output)); } catch { finish(new Error('Hermes bridge returned invalid JSON')); }
    });
    child.stdin.on('error', () => { /* Process completion owns the error. */ });
    child.stdin.end(describe ? '' : JSON.stringify(request));
  });
}

/** Admit image bytes in original content order and verify the stored bytes. */
export async function admitResult(ctx, result, config, signal) {
  const sourceImages = result.content.filter(part => part.type === 'image');
  const inputs = [];
  for (const part of sourceImages) {
    signal?.throwIfAborted();
    const data = await readFile(part.path);
    if (sha(data) !== part.sha256) throw new Error('Hermes image artifact changed before attachment admission');
    inputs.push({ data, mediaType: part.media_type });
  }
  const refs = inputs.length ? await ctx.attachments.saveImages(inputs) : [];
  if (refs.length !== inputs.length) throw new Error('Attachment admission changed image count');
  for (let index = 0; index < refs.length; index++) {
    const stored = await ctx.attachments.readImage(refs[index], signal);
    if (sha(stored.data) !== sourceImages[index].sha256)
      throw new Error('Attachment normalization changed Hermes tool image bytes; configure preserve mode');
  }
  let index = 0;
  const content = result.content.map(part => part.type === 'text' ? { type: 'text', text: part.text }
    : { type: 'image', attachment: refs[index++], aclImageDetail: part.detail ?? 'auto' });
  const images = sourceImages.map((part, offset) => ({ ...part, attachment: refs[offset] }));
  const value = { tool: result.tool, call_id: String(result.call_id ?? ''), content, images,
    metadata: result.metadata, handler_seconds: result.handler_seconds,
    bridge_seconds: result.bridge_seconds ?? null };
  if (config.metricsDir) {
    await mkdir(config.metricsDir, { recursive: true });
    await appendFile(join(config.metricsDir, 'hermes-tool-bridge.jsonl'), JSON.stringify(value) + '\n');
  }
  return value;
}

/** Register original names/handler output; injection is only for offline fixtures. */
export function registerTools(ctx, config, schemas, invoke = invokeBridge) {
  for (const schema of schemas) {
    if (!TOOL_NAMES.includes(schema.name)) throw new Error('Unexpected Hermes bridge tool');
    ctx.tools.register(defineTool({
      name: schema.name, description: schema.description, parameters: parameterSpec(schema.parameters),
      timeoutMs: config.timeoutMs, isConcurrencySafe: () => false,
      output: {
        schema: { type: 'object', additionalProperties: false, properties: {
          tool: { type: 'string', required: true }, call_id: { type: 'string', required: true },
          content: { type: 'array', items: { type: 'json' }, required: true },
          images: { type: 'array', items: { type: 'json' }, required: true },
          metadata: { type: 'json', required: true }, handler_seconds: { type: 'number', required: true },
          bridge_seconds: { oneOf: [{ type: 'number' }, { type: 'null' }], required: true },
        } },
        render: (_args, value) => value.content,
        presentationMeta: (_args, value) => ({ tool: value.tool, call_id: value.call_id,
          images: value.images, metadata: value.metadata, handler_seconds: value.handler_seconds,
          bridge_seconds: value.bridge_seconds }),
      },
      async execute(args, exec) {
        const started = performance.now();
        const result = await invoke(config, { tool: schema.name, arguments: args, call_id: exec.callId }, exec.signal);
        result.bridge_seconds = (performance.now() - started) / 1000;
        if (result.tool !== schema.name) throw new Error('Hermes bridge tool identity mismatch');
        return admitResult(ctx, result, config, exec.signal);
      },
    }));
  }
}

export async function apply(ctx, config) {
  for (const key of ['python', 'bridge', 'workspace', 'metricsDir'])
    if (typeof config[key] !== 'string' || !config[key]) throw new Error(`Hermes bridge requires ${key}`);
  for (const key of ['timeoutMs', 'maxResultBytes'])
    if (!Number.isInteger(config[key]) || config[key] <= 0) throw new Error(`Hermes bridge requires positive ${key}`);
  const { tools } = await invokeBridge(config, null, undefined, true);
  if (tools.map(tool => tool.name).join(',') !== TOOL_NAMES.join(',')) throw new Error('Hermes tool manifest mismatch');
  registerTools(ctx, config, tools);
  // Tool admission is snapshotted before pre-step; restrict at creation so the
  // first model request cannot expose unrelated filesystem/subagent tools.
  ctx.on('agent/created', ({ agent }) => {
    agent.ctx.tools.restrict({ allow: TOOL_NAMES });
  });
}
