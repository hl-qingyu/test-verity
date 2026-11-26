const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { load } = require('./helpers/load.cjs');

async function scenario(active) {
  const old = { window: global.window, document: global.document };
  const windowEvents = new EventTarget();
  const page = new EventTarget();
  page.visibilityState = 'visible';
  const timers = new Map();
  windowEvents.setInterval = (fn) => (timers.set(1, fn), 1);
  windowEvents.clearInterval = (id) => timers.delete(id);
  global.window = windowEvents;
  global.document = page;
  const cleanups = [];
  const calls = [];
  try {
    const { usePolling } = load(path.resolve(__dirname, '../src/usePolling.ts'), {
      react: {
        useRef: (current) => ({ current }),
        useEffect: (setup) => cleanups.push(setup()),
      },
    });
    usePolling({
      active,
      interval: 2500,
      refreshKey: 'record',
      load: async (signal) => {
        calls.push(signal);
      },
    });
    await Promise.resolve();
    assert.equal(calls.length, 1);
    assert.equal(timers.size, Number(active));
    for (const fn of timers.values()) fn();
    await Promise.resolve();
    assert.equal(calls.length, active ? 2 : 1);
    const before = calls.length;
    page.visibilityState = 'hidden';
    page.dispatchEvent(new Event('visibilitychange'));
    for (const fn of timers.values()) fn();
    windowEvents.dispatchEvent(new Event('focus'));
    assert.equal(calls.length, before);
    page.visibilityState = 'visible';
    page.dispatchEvent(new Event('visibilitychange'));
    assert.equal(calls.length, before + 1);
    cleanups.reverse().forEach((cleanup) => cleanup?.());
    assert.equal(timers.size, 0);
    assert.equal(calls.at(-1).aborted, true);
    windowEvents.dispatchEvent(new Event('focus'));
    assert.equal(calls.length, before + 1);
  } finally {
    Object.assign(global, old);
  }
}

test('visible active work polls and hidden work pauses until visibility resumes', () =>
  scenario(true));
test('idle screens refresh at entry and on return without scheduling intervals', () =>
  scenario(false));
