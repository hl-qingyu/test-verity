const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function harness(response) {
  const source = fs.readFileSync(path.resolve(__dirname, '../src/cliEventsApi.ts'), 'utf8');
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText;
  const exports = {},
    requests = [];
  new Function('require', 'exports', code)((name) => {
    assert.equal(name, './api/http');
    return {
      apiRequest: async (...args) => {
        requests.push(args);
        return response;
      },
    };
  }, exports);
  return { ...exports, requests };
}
const sample = () => ({
  items: [
    {
      sequence: 1,
      at: null,
      elapsed_seconds: null,
      type: 'error',
      text: 'Reconnecting... 1/5',
      truncated: false,
    },
  ],
  next_cursor: 1,
  has_more: false,
  available: true,
  status: 'FAILED',
  attempt_index: 0,
  attempts: [{ index: 0, status: 'FAILED', started_at: null }],
});

test('CLI viewer uses authorized task endpoint and cursor without sending or retrying a model call', async () => {
  const h = harness(sample()),
    signal = new AbortController().signal;
  const result = await h.cliEvents(
    '/api/projects/7/case-generation/4/batches/3/cli-events',
    0,
    signal,
    0,
  );
  assert.equal(result.items[0].text, 'Reconnecting... 1/5');
  assert.equal(h.requests.length, 1);
  assert.equal(
    h.requests[0][0],
    '/api/projects/7/case-generation/4/batches/3/cli-events?cursor=0&attempt=0',
  );
  assert.equal(h.requests[0][1].signal, signal);
  assert.equal(h.requests[0][1].method, undefined);
});

test('CLI viewer rejects malformed, repeated or skipped event cursors', async () => {
  for (const alter of [
    (r) => (r.items[0].sequence = 2),
    (r) => (r.next_cursor = 0),
    (r) => (r.items[0].text = {}),
    (r) => (r.attempts[0].index = -1),
    (r) => {
      r.items = [];
      r.next_cursor = 0;
      r.has_more = true;
    },
  ]) {
    const response = sample();
    alter(response);
    await assert.rejects(
      harness(response).cliEvents('/events', 0, new AbortController().signal),
      /generation_response_invalid/,
    );
  }
});
