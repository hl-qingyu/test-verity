const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { Terminal: Xterm } = require('@xterm/xterm');

function harness({ fitCols } = {}) {
  const hooks = [],
    effects = [],
    sockets = [],
    calls = [],
    terminals = [],
    timers = [];
  let cursor = 0,
    tree,
    closed = 0;
  const react = {
    useRef(value) {
      return (hooks[cursor++] ||= { current: value });
    },
    useState(value) {
      const index = cursor++;
      hooks[index] ||= { value };
      return [
        hooks[index].value,
        (next) => {
          hooks[index].value = next;
        },
      ];
    },
    useEffect(fn, deps) {
      const index = cursor++,
        prior = hooks[index];
      if (!prior || deps.some((d, i) => !Object.is(d, prior.deps[i]))) {
        prior?.cleanup?.();
        hooks[index] = { deps };
        effects.push(() => {
          hooks[index].cleanup = fn();
        });
      }
    },
  };
  class Terminal extends Xterm {
    constructor(options) {
      super(options);
      terminals.push(this);
    }
    attachCustomKeyEventHandler(fn) {
      this.keyHandler = fn;
      super.attachCustomKeyEventHandler(fn);
    }
  }
  const globals = {
    ResizeObserver: global.ResizeObserver,
    WebSocket: global.WebSocket,
    window: global.window,
  };
  global.ResizeObserver = class {
    observe() {}
    disconnect() {}
  };
  global.WebSocket = { OPEN: 1 };
  global.window = {
    clearTimeout() {},
    setTimeout(fn) {
      timers.push(fn);
      return timers.length;
    },
  };
  const session = { id: 90, kind: 'chat', epoch: '90', status: 'RUNNING', error_code: '' };
  const api = {
    async apiRequest(url, options) {
      calls.push({ url, options });
      return { session, enabled: true, generation_bound: true };
    },
  };
  const cache = new Map();
  function load(name) {
    if (cache.has(name)) return cache.get(name);
    const exports = {};
    cache.set(name, exports);
    const source = fs.readFileSync(path.resolve(__dirname, '../src/' + name), 'utf8');
    const code = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.ReactJSX,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText;
    new Function('require', 'exports', code)((name) => {
      if (name === 'react') return react;
      if (name === '@xterm/xterm') return { Terminal };
      if (name === '@xterm/addon-fit')
        return {
          FitAddon: class {
            activate(term) {
              this.term = term;
            }
            dispose() {}
            fit() {
              if (fitCols) this.term.resize(fitCols, 24);
            }
          },
        };
      if (name.endsWith('.css')) return {};
      if (name === './NativeResultReview')
        return { NativeResultReview: function NativeResultReview() {} };
      if (name === './CaseDialog') return { CaseDialog: function CaseDialog() {} };
      if (name === './api/http') return api;
      if (name === './generationApi')
        return { generationBase: () => '/generation', generationError: (e) => e.message };
      if (name === './nativeTerminalApi')
        return {
          ...load('nativeTerminalApi.ts'),
          terminalSocket(url, cursor) {
            const ws = {
              readyState: 1,
              cursor,
              url,
              sent: [],
              send(data) {
                this.sent.push(JSON.parse(data));
              },
              close() {
                this.readyState = 3;
                this.onclose?.();
              },
            };
            sockets.push(ws);
            return ws;
          },
        };
      return require(name);
    }, exports);
    return exports;
  }
  const { GenerationCliWorkspace } = load('GenerationCliWorkspace.tsx');
  const props = {
    projectId: 7,
    runId: '1752',
    onSessionEnd() {},
    onClose() {
      closed++;
    },
  };
  function render() {
    cursor = 0;
    tree = GenerationCliWorkspace(props);
    while (effects.length) effects.shift()();
  }
  async function settle() {
    for (let n = 0; n < 4; n++) {
      await Promise.resolve();
      render();
    }
  }
  return {
    render,
    settle,
    sockets,
    calls,
    terminals,
    text: () => JSON.stringify(tree.props.children),
    tree: () => tree,
    dimensions(cols, rows) {
      session.replay_cols = cols;
      session.replay_rows = rows;
    },
    setSessionEnd(value) {
      props.onSessionEnd = value;
      render();
    },
    setOpen(value) {
      props.open = value;
      render();
    },
    reconnect() {
      sockets.at(-1).close();
      timers.shift()?.();
      sockets.at(-1).onopen();
    },
    frame(frame) {
      sockets.at(-1).onmessage({ data: JSON.stringify(frame) });
    },
    flush: () => new Promise((resolve) => terminals.at(-1).write('', resolve)),
    close() {
      tree.props.onClose();
    },
    closed: () => closed,
    dispose() {
      hooks.forEach((h) => h?.cleanup?.());
      Object.assign(global, globals);
    },
  };
}

test('real xterm renders replay without returning old query replies, then forwards live input', async () => {
  const h = harness();
  try {
    h.render();
    await h.settle();
    const ws = h.sockets[0],
      term = h.terminals[0];
    ws.onopen();
    h.frame({ type: 'output', chunks: ['History\r\n\x1b[c\x1b[6n'] });
    h.frame({ type: 'ready' });
    assert.equal(term.options.disableStdin, true, 'queued writes must finish before stdin resumes');
    await h.flush();
    assert.deepEqual(
      ws.sent.map((f) => f.type),
      ['resize'],
    );
    assert.equal(term.buffer.active.getLine(0).translateToString(true), 'History');
    h.frame({ type: 'output', chunks: ['\x1b[c'] });
    await h.flush();
    assert.equal(
      ws.sent.at(-1).data,
      '\x1b[?1;2c',
      'new live query receives its normal xterm reply',
    );
    term.input('继续分析\r');
    assert.equal(ws.sent.at(-1).data, '继续分析\r');
    const before = ws.sent.length;
    const event = { key: 'Escape', type: 'keydown', preventDefault() {}, stopPropagation() {} };
    assert.equal(term.keyHandler(event), false);
    assert.equal(h.closed(), 1);
    assert.equal(
      ws.sent.length,
      before,
      'Escape closes the window without sending an interrupt key',
    );
    assert.ok(
      h.calls.every((c) => !c.options?.method),
      'opening/closing must not submit or cancel tasks',
    );
  } finally {
    h.dispose();
  }
});

test('native failure updates the visible label without closing or resubmitting the CLI', async () => {
  const h = harness();
  try {
    h.render();
    await h.settle();
    h.sockets[0].onopen();
    h.frame({
      type: 'state',
      session: {
        id: 90,
        kind: 'chat',
        epoch: '90',
        status: 'RUNNING',
        error_code: '',
        turn_status: 'failed',
        turn_error: 'stream closed before response.completed',
      },
    });
    await h.settle();
    assert.match(h.text(), /本轮已失败 · CLI 等待输入/);
    assert.match(h.text(), /上游响应在完成前断开/);
    assert.equal(h.calls.length, 1);
    assert.equal(h.sockets.length, 1);
    assert.deepEqual(h.sockets[0].sent, []);
  } finally {
    h.dispose();
  }
});

test('unmount and reopen replays the same session without commands or stale callbacks', async () => {
  const first = harness();
  first.render();
  await first.settle();
  const oldSocket = first.sockets[0];
  oldSocket.onopen();
  first.frame({ type: 'output', chunks: ['same task\x1b[c'] });
  first.frame({ type: 'ready' });
  first.dispose();
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.deepEqual(oldSocket.sent, [], 'disposed replay callback must not write to the old PTY');
  const reopened = harness();
  try {
    reopened.render();
    await reopened.settle();
    reopened.sockets[0].onopen();
    reopened.frame({ type: 'output', chunks: ['same task\r\nbackground result\x1b[c'] });
    reopened.frame({ type: 'ready' });
    await reopened.flush();
    assert.equal(
      reopened.terminals[0].buffer.active.getLine(1).translateToString(true),
      'background result',
    );
    assert.deepEqual(
      reopened.sockets[0].sent.map((f) => f.type),
      ['resize'],
    );
    assert.ok(reopened.calls.every((c) => !c.options?.method));
  } finally {
    reopened.dispose();
  }
});

test('history view caches the same terminal while hidden and receives only new output on reopen or reconnect', async () => {
  const h = harness();
  try {
    h.render();
    await h.settle();
    const term = h.terminals[0];
    h.sockets[0].onopen();
    h.frame({ type: 'output', chunks: ['cached history\r\n'] });
    h.frame({ type: 'ready' });
    await h.flush();
    await h.settle();
    assert.equal(h.tree().type, 'section');
    assert.equal(h.tree().props['aria-label'], '用例生成历史对话');
    assert.doesNotMatch(h.text(), /正在恢复终端最新画面/);
    h.setOpen(false);
    await h.settle();
    assert.equal(h.tree().props.hidden, true);
    const sent = h.sockets[0].sent.length;
    term.input('must not send');
    h.frame({ type: 'output', chunks: ['background answer\r\n'] });
    await h.flush();
    assert.equal(h.sockets[0].sent.length, sent);
    h.setOpen(true);
    await h.settle();
    assert.equal(h.terminals.length, 1);
    assert.equal(h.sockets.length, 1);
    assert.equal(term.buffer.active.getLine(1).translateToString(true), 'background answer');
    assert.equal(h.tree().props.hidden, false);
    h.reconnect();
    assert.equal(h.sockets[1].cursor, 2);
    assert.equal(term.buffer.active.getLine(0).translateToString(true), 'cached history');
    h.frame({ type: 'output', chunks: ['incremental tail'] });
    h.frame({ type: 'ready' });
    await h.flush();
    assert.equal(term.buffer.active.getLine(2).translateToString(true), 'incremental tail');
    assert.ok(
      h.calls.every((c) => !c.options?.method),
      'view navigation must not create model requests',
    );
  } finally {
    h.dispose();
  }
});

test('a fresh screen is hidden until parsed and opens at the bottom even if a completed socket closes first', async () => {
  const h = harness();
  try {
    h.render();
    await h.settle();
    h.sockets[0].onopen();
    h.frame({
      type: 'output',
      chunks: [Array.from({ length: 200 }, (_, i) => `line ${i}\r\n`).join('')],
    });
    await h.flush();
    h.terminals[0].scrollToTop();
    assert.match(h.text(), /正在恢复终端最新画面/);
    h.frame({
      type: 'state',
      session: { id: 90, kind: 'chat', epoch: '90', status: 'COMPLETED', error_code: '' },
    });
    h.frame({ type: 'ready' });
    h.sockets[0].close();
    await h.flush();
    await h.settle();
    const buffer = h.terminals[0].buffer.active;
    assert.equal(buffer.viewportY, buffer.baseY);
    assert.ok(buffer.baseY > 0);
    assert.doesNotMatch(h.text(), /正在恢复终端最新画面/);
    assert.equal(h.terminals[0].options.disableStdin, true);
    assert.deepEqual(h.sockets[0].sent, []);
  } finally {
    h.dispose();
  }
});

test('parent callback changes never recreate the cached renderer or its connection', async () => {
  const h = harness();
  try {
    h.render();
    await h.settle();
    h.sockets[0].onopen();
    h.frame({ type: 'output', chunks: ['original cached screen'] });
    h.frame({ type: 'ready' });
    await h.flush();
    await h.settle();
    const count = h.calls.length;
    for (let i = 0; i < 5; i++) {
      h.setSessionEnd(() => {});
      await h.settle();
    }
    assert.equal(h.terminals.length, 1);
    assert.equal(h.sockets.length, 1);
    assert.equal(h.calls.length, count);
    assert.equal(
      h.terminals[0].buffer.active.getLine(0).translateToString(true),
      'original cached screen',
    );
  } finally {
    h.dispose();
  }
});

test('a new execution epoch discards the old cached screen and resumes from zero', async () => {
  const h = harness();
  try {
    h.render();
    await h.settle();
    const old = h.sockets[0];
    old.onopen();
    h.frame({ type: 'output', chunks: ['previous attempt'] });
    h.frame({ type: 'ready' });
    await h.flush();
    h.frame({
      type: 'state',
      session: { id: 90, kind: 'chat', epoch: 'new-attempt', status: 'RUNNING', error_code: '' },
    });
    await h.settle();
    assert.equal(h.sockets.length, 2);
    assert.equal(h.sockets[1].cursor, 0);
    h.sockets[1].onopen();
    old.onmessage({ data: JSON.stringify({ type: 'output', chunks: ['stale old frame'] }) });
    h.frame({ type: 'output', chunks: ['new attempt'] });
    h.frame({ type: 'ready' });
    await h.flush();
    assert.equal(h.terminals[0].buffer.active.getLine(0).translateToString(true), 'new attempt');
  } finally {
    h.dispose();
  }
});

test('recorded terminal width is restored before fitting without stale wrapped characters', async () => {
  const h = harness({ fitCols: 20 });
  try {
    h.dimensions(30, 24);
    h.render();
    await h.settle();
    h.sockets[0].onopen();
    assert.equal(h.terminals[0].cols, 30);
    assert.match(h.text(), /generation-spinner/);
    h.frame({
      type: 'output',
      chunks: ['1234567890123456789012345678配', '\x1b[1;1H\x1b[2Kclean'],
    });
    h.frame({ type: 'ready' });
    await h.flush();
    await h.settle();
    assert.equal(h.terminals[0].cols, 20);
    const buffer = h.terminals[0].buffer.active;
    assert.equal(buffer.getLine(0).translateToString(true), 'clean');
    assert.equal(buffer.getLine(1).translateToString(true), '');
    assert.doesNotMatch(h.text(), /generation-spinner/);
  } finally {
    h.dispose();
  }
});

test('historical resize positions are applied between unchanged output chunks', async () => {
  const h = harness();
  try {
    h.dimensions(30, 24);
    h.render();
    await h.settle();
    h.sockets[0].onopen();
    h.frame({
      type: 'output',
      chunks: ['before\r\n', '12345678901234567890配', '\x1b[2;1H\x1b[2Kafter'],
      resizes: [{ index: 1, rows: 24, cols: 24 }],
    });
    h.frame({ type: 'ready' });
    await h.flush();
    assert.equal(h.terminals[0].cols, 24);
    assert.equal(h.terminals[0].buffer.active.getLine(1).translateToString(true), 'after');
    assert.equal(h.terminals[0].buffer.active.getLine(2).translateToString(true), '');
  } finally {
    h.dispose();
  }
});
