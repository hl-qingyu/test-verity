const { load } = require('./helpers/load.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
function harness(response) {
  const calls = [];
  return {
    ...load(path.resolve(__dirname, '../src/nativeTerminalApi.ts'), {
      './api/http': {
        apiRequest: async (...args) => {
          calls.push(args);
          return response;
        },
      },
    }),
    calls,
  };
}
test('generation transport uses the batch namespace and retains attempt identity', () => {
  const h = harness(null);
  const session = h.sessionResponse({
    session: {
      id: 9,
      status: 'QUEUED',
      error_code: '',
      kind: 'generation',
      epoch: 'attempt-one',
    },
  });
  assert.equal(h.nativeSessionUrl('/terminal', session), '/terminal/generation/9');
  assert.equal(session.epoch, 'attempt-one');
  assert.equal(h.nativeSessionUrl('/terminal', { ...session, kind: 'chat' }), '/terminal/9');
  assert.throws(() => h.sessionResponse({ session: { ...session, kind: 'unknown' } }));
});

test('transport signals that historical screen replay is fully delivered', () => {
  const h = harness(null);
  assert.deepEqual(h.parseTerminalFrame('{"type":"ready"}'), { type: 'ready' });
});

test('terminal reconnection uses the cached cursor and rejects invalid positions', () => {
  const previous = { WebSocket: global.WebSocket, location: global.location };
  try {
    global.location = { protocol: 'http:', host: '127.0.0.1:5173' };
    global.WebSocket = class {
      constructor(url) {
        this.url = url;
      }
    };
    const api = harness(null);
    assert.equal(
      api.terminalSocket('/terminal/7', 123).url,
      'ws://127.0.0.1:5173/terminal/7/socket?cursor=123',
    );
    for (const cursor of [-1, 1.5, NaN, Infinity, 2 ** 53])
      assert.throws(() => api.terminalSocket('/terminal/7', cursor));
  } finally {
    Object.assign(global, previous);
  }
});

test('failed native turn is shown as failed while its terminal process stays open', () => {
  const h = harness(null);
  const session = h.sessionResponse({
    session: {
      id: 92,
      kind: 'chat',
      status: 'RUNNING',
      error_code: '',
      turn_status: 'failed',
      turn_error: 'stream disconnected before completion: stream closed before response.completed',
    },
  });
  assert.equal(h.nativeSessionLabel(session), '本轮已失败 · CLI 等待输入');
  assert.equal(h.nativeTurnFailure(session), '上游响应在完成前断开，CLI 本轮分析已失败。');
  assert.equal(
    h.nativeSessionLabel({ ...session, turn_status: 'running', turn_error: '' }),
    '正在分析',
  );
  assert.equal(h.nativeTurnFailure({ ...session, turn_status: 'running', turn_error: '' }), '');
  assert.equal(
    h.nativeSessionLabel({ ...session, status: 'FAILED', turn_status: 'running' }),
    'CLI 进程已结束',
  );
  assert.throws(() => h.sessionResponse({ session: { ...session, turn_status: 'unknown' } }));
});

test('recorded terminal sizes and frame boundaries are validated before playback', () => {
  const h = harness(null),
    value = {
      type: 'output',
      chunks: ['raw1', 'raw2'],
      resizes: [{ index: 1, rows: 34, cols: 126 }],
    };
  assert.deepEqual(h.parseTerminalFrame(JSON.stringify(value)).resizes, value.resizes);
  for (const size of [
    { index: -1, rows: 34, cols: 126 },
    { index: 2, rows: 34, cols: 126 },
    { index: 0, rows: 0, cols: 126 },
    { index: 0, rows: 34, cols: 1000000 },
  ])
    assert.throws(() => h.parseTerminalFrame(JSON.stringify({ ...value, resizes: [size] })));
  const session = {
    id: 93,
    status: 'COMPLETED',
    error_code: '',
    replay_rows: 34,
    replay_cols: 126,
  };
  assert.equal(h.sessionResponse({ session }).replay_cols, 126);
  assert.throws(() => h.sessionResponse({ session: { ...session, replay_cols: 1000000 } }));
});
