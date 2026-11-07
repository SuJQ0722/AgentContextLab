import test from 'node:test';
import assert from 'node:assert/strict';
import { providers } from '../plugins/dsh-local-web/index.mjs';

test('Hermes wire compatibility: cached Serper and text Reader', async () => {
  const requests = [];
  const transport = async (url, options) => {
    requests.push({ url, ...options, body: JSON.parse(options.body) });
    return new Response(JSON.stringify(url.endsWith('/search')
      ? { organic: [{ title: 't', link: 'https://example.com', snippet: 's' }] }
      : { success: true, data: 'fetched text' }), { status: 200, headers: { 'x-cached': 'true' } });
  };
  const p = providers({ search: { url: 'proxy', port: 80, api_key: 'search-key' },
    fetch: { base_url: 'http://reader', extract_mode: 'text', jina_api_key: 'reader-key', llm_api_key: 'unused' } }, null, transport);
  assert.equal((await p.search.search({ query: '中文', maxResults: 5 })).sources[0].url, 'https://example.com');
  assert.deepEqual(requests[0].body, { q: '中文', location: 'China', gl: 'cn', hl: 'zh-cn' });
  assert.equal(requests[0].headers['X-API-KEY'], 'search-key');
  assert.equal((await p.fetch.fetch({ url: 'https://example.com' })).body.content, 'fetched text');
  assert.deepEqual(requests[1].body, { url: 'https://example.com', extractMode: 'text', jina_api_key: 'reader-key' });
});

test('Reader errors remain failures instead of empty successful evidence', async () => {
  const p = providers({ search: {}, fetch: { base_url: 'http://reader' } }, null,
    async () => new Response(JSON.stringify({ success: false, error: 'sensitive upstream body' })));
  await assert.rejects(() => p.fetch.fetch({ url: 'https://example.com' }), /service reported failure/);
});
