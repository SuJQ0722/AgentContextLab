/** Same wire protocol and endpoints as Hermes plugins/local_web. Secrets stay in env. */
import { mkdir, appendFile } from 'node:fs/promises';
import { join } from 'node:path';

export const inject = ['web', 'tools'];

export function providers(settings, metricsDir, transport = fetch) {
  async function post(kind, endpoint, body, headers, seconds, signal) {
    const started = performance.now();
    let status = null, cached = null, success = false;
    try {
      const response = await transport(endpoint, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...headers },
        body: JSON.stringify(body),
        signal: AbortSignal.any([AbortSignal.timeout(seconds * 1000), ...signal ? [signal] : []]),
      });
      status = response.status;
      cached = response.headers.get('x-cached');
      if (!response.ok) throw new Error(`${kind} proxy HTTP ${status}`);
      const data = await response.json();
      if (data.success === false) throw new Error(`${kind} service reported failure`);
      success = true;
      return { data, status };
    } finally {
      if (metricsDir) {
        await mkdir(metricsDir, { recursive: true });
        await appendFile(join(metricsDir, 'web.jsonl'), JSON.stringify({
          timestamp: new Date().toISOString(),
          kind, proxy_http_status: status, cache_header: cached, success,
          client_http_seconds: (performance.now() - started) / 1000,
          origin_http_status: null,
        }) + '\n');
      }
    }
  }
  const s = settings.search, f = settings.fetch;
  return {
    search: {
      id: 'acl-serper-cache', available: () => Boolean(s.url && s.port && s.api_key),
      async search({ query, maxResults = 5 }, signal) {
        const zh = /[\u4e00-\u9fff]/u.test(query);
        const { data } = await post('search', `http://${s.url}:${s.port}/search`, {
          q: query, location: zh ? 'China' : 'United States', gl: zh ? 'cn' : 'us', hl: zh ? 'zh-cn' : 'en',
        }, { 'X-API-KEY': s.api_key }, 30, signal);
        if (!Array.isArray(data.organic)) throw new Error('Serper response has no organic results array');
        return { sources: data.organic.slice(0, maxResults).map(r => ({
          url: r.link, title: r.title ?? '', snippet: r.snippet ?? '',
        })), truncated: data.organic.length > maxResults };
      },
    },
    fetch: {
      id: 'acl-jina-reader', available: () => Boolean(f.base_url),
      async fetch({ url }, signal) {
        const parsed = new URL(url);
        if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password)
          throw new Error('Only HTTP(S) URLs without credentials are accepted');
        const mode = f.extract_mode ?? 'markdown';
        const body = { url, extractMode: mode, jina_api_key: f.jina_api_key ?? '' };
        if (mode === 'markdown') Object.assign(body, {
          llm_base_url: f.llm_base_url, llm_model: f.llm_model, llm_api_key: f.llm_api_key ?? '',
        });
        const { data, status } = await post('fetch', f.base_url.replace(/\/$/, '') + '/fetch', body,
          {}, f.timeout ?? 180, signal);
        if (typeof data.data !== 'string') throw new Error('Reader response has no text body');
        // Reader exposes only its own HTTP status; origin status is unavailable in this protocol.
        return { url, statusCode: status, body: { kind: 'text', content: data.data }, truncated: false };
      },
    },
  };
}

export function apply(ctx, { metricsDir }) {
  const p = providers(JSON.parse(process.env.ACL_WEB_SECRETS), metricsDir);
  ctx.web.registerSearchProvider(p.search);
  ctx.web.registerFetchProvider(p.fetch);
  const restricted = new WeakSet();
  ctx.on('agent/pre-step', async ({ agent }, next) => {
    if (!restricted.has(agent)) {
      agent.ctx.tools.restrict({ allow: ['web_search', 'web_fetch'] });
      restricted.add(agent);
    }
    return next();
  });
}
