import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { applyEntryPatches, entryListSchema } from '../deepseekHarness/vendor/include/lib/index.js';
const require = createRequire(new URL('../deepseekHarness/vendor/include/package.json', import.meta.url));
const yaml = require('js-yaml');

test('research patch disables the default and inserts a distinct policy without name mismatch', () => {
  const patches = yaml.load(readFileSync(new URL('../configs/research.dsh.patch.yml', import.meta.url), 'utf8'), { schema: entryListSchema });
  const warnings = [];
  const entries = applyEntryPatches([
    { id: 'compaction-basic', name: '@deepseek-ai/dsh-compaction-basic' },
    { id: 'tool-result-pruner', name: '@deepseek-ai/dsh-compaction-tool-result-pruner' },
  ], patches, (...args) => warnings.push(args));
  assert.deepEqual(warnings, []);
  assert.equal(entries.find(e => e.id === 'compaction-basic').disabled, true);
  assert.equal(entries.find(e => e.id === 'tool-result-pruner').disabled, true);
  assert.equal(entries.filter(e => !e.disabled).length, 1);
  assert.equal(entries.find(e => !e.disabled).id, 'acl-research-compaction');
});
