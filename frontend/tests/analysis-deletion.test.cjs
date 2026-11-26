const { compileModule, load: loadModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test'),
  assert = require('node:assert/strict'),
  fs = require('node:fs'),
  path = require('node:path'),
  ts = require('typescript');

function harness(request) {
  const hooks = [],
    effects = [],
    cache = new Map();
  let cursor = 0,
    deleted = 0,
    ended = 0,
    tree;
  const react = {
    useState(initial) {
      const i = cursor++;
      hooks[i] ||= { value: typeof initial === 'function' ? initial() : initial };
      return [
        hooks[i].value,
        (v) => (hooks[i].value = typeof v === 'function' ? v(hooks[i].value) : v),
      ];
    },
    useRef(initial) {
      return (hooks[cursor++] ||= { current: initial });
    },
    useEffect(fn, deps) {
      const i = cursor++,
        old = hooks[i];
      if (!old || deps.some((v, n) => !Object.is(v, old.deps[n]))) {
        old?.cleanup?.();
        hooks[i] = { deps };
        effects.push(() => (hooks[i].cleanup = fn()));
      }
    },
  };
  function load(file) {
    if (cache.has(file)) return cache.get(file);
    const exported = {};
    cache.set(file, exported);
    const code = compileModule(fs.readFileSync(file, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    evaluateModule(
      code,
      (name) => {
        if (name === 'react') return react;
        if (name === './api/http') return { apiRequest: request };
        if (name === './CaseDialog') return { CaseDialog: 'dialog' };
        if (name === './Icon') return { Icon: 'svg' };
        if (name.startsWith('.')) return load(path.resolve(path.dirname(file), name + '.ts'));
        return require(name);
      },
      exported,
    );
    return exported;
  }
  const { AnalysisRecordDelete } = load(path.resolve(__dirname, '../src/AnalysisRecordDelete.tsx'));
  const props = {
    base: '/api/projects/4/code-analysis',
    id: 7,
    projectId: 4,
    refreshKey: 1,
    onDeleted() {
      deleted++;
    },
    onSessionEnd() {
      ended++;
    },
  };
  function render() {
    cursor = 0;
    tree = AnalysisRecordDelete(props);
    while (effects.length) effects.shift()();
    return tree;
  }
  function nodes(node = tree) {
    return !node || typeof node !== 'object'
      ? []
      : [
          node,
          ...[node.props?.children]
            .flat(Infinity)
            .filter((n) => n !== undefined)
            .flatMap((n) => nodes(n)),
        ];
  }
  function button(label) {
    return nodes().find((n) => n.type === 'button' && n.props.children === label);
  }
  async function settle() {
    for (let n = 0; n < 4; n++) {
      await new Promise(setImmediate);
      render();
    }
  }
  return {
    render,
    settle,
    button,
    nodes,
    props,
    get deleted() {
      return deleted;
    },
    get ended() {
      return ended;
    },
    close() {
      hooks.forEach((h) => h?.cleanup?.());
    },
  };
}
const info = {
  id: 7,
  project_id: 4,
  title: '合成分析',
  revision: 3,
  can_delete: true,
  active: false,
};

test('deletion preview rejects wrong record/project identity and malformed permission/version fields', () => {
  const { parseDeletion } = loadModule(path.resolve(__dirname, '../src/analysisDeletionApi.ts'));
  assert.deepEqual(parseDeletion(info, 7, 4), info);
  for (const invalid of [
    null,
    { ...info, id: 8 },
    { ...info, project_id: 5 },
    { ...info, active: 'false' },
    { ...info, can_delete: 1 },
    { ...info, revision: 0 },
  ])
    assert.throws(() => parseDeletion(invalid, 7, 4), /analysis_delete_response_invalid/);
});

test('deletion requires explicit confirmation, blocks duplicates and verifies identity', async () => {
  const calls = [];
  let release;
  const h = harness(async (url, options) => {
    calls.push({ url, options });
    return options.method === 'POST' ? new Promise((r) => (release = r)) : info;
  });
  const raf = global.requestAnimationFrame;
  global.requestAnimationFrame = () => 0;
  try {
    h.render();
    await h.settle();
    assert.equal(calls.length, 1);
    assert.equal(h.deleted, 0);
    h.button('删除记录').props.onClick();
    h.render();
    await h.settle();
    const confirm = h.button('确认删除');
    assert.equal(confirm.props.disabled, false);
    confirm.props.onClick();
    confirm.props.onClick();
    await new Promise(setImmediate);
    assert.equal(calls.filter((c) => c.options.method === 'POST').length, 1);
    assert.deepEqual(JSON.parse(calls.at(-1).options.body), { confirmed: true, revision: 3 });
    // Polling changes cannot abort an in-flight deletion while the modal is open.
    h.props.refreshKey = 2;
    h.render();
    assert.equal(calls.at(-1).options.signal.aborted, false);
    release({ id: 7, project_id: 4, deleted: true });
    await h.settle();
    assert.equal(h.deleted, 1);
  } finally {
    h.close();
    global.requestAnimationFrame = raf;
  }
});
test('no permission hides the control, active tasks disable confirmation, cancel never writes', async () => {
  let calls = 0,
    current = { ...info, can_delete: false };
  const h = harness(async () => {
    calls++;
    return current;
  });
  try {
    h.render();
    await h.settle();
    assert.equal(h.button('删除记录'), undefined);
    current = { ...info, active: true };
    h.props.refreshKey = 2;
    h.render();
    await h.settle();
    h.button('删除记录').props.onClick();
    h.render();
    await h.settle();
    assert.equal(h.button('确认删除').props.disabled, true);
    h.button('取消').props.onClick();
    h.render();
    assert.equal(
      h.nodes().some((n) => n.type === 'dialog'),
      false,
    );
    assert.equal(h.deleted, 0);
    assert.ok(calls >= 2);
  } finally {
    h.close();
  }
});

test('record tables reuse listed permissions and only fetch impact when their button is opened', async () => {
  let reads = 0;
  const h = harness(async () => {
    reads++;
    return info;
  });
  try {
    h.props.canDelete = false;
    h.render();
    await h.settle();
    assert.equal(reads, 0);
    assert.equal(h.button('删除记录'), undefined);
    h.props.canDelete = true;
    h.render();
    await h.settle();
    assert.equal(reads, 0);
    assert.equal(h.button('删除记录').props.disabled, false);
    h.button('删除记录').props.onClick();
    h.render();
    await h.settle();
    assert.equal(reads, 1);
    assert.equal(h.button('确认删除').props.disabled, false);
  } finally {
    h.close();
  }
});

test('sidebar trash targets its own record without selecting the row or loading every preview', async () => {
  const calls = [];
  const h = harness(async (url) => {
    calls.push(url);
    return { ...info, id: 19, title: '另一条分析' };
  });
  try {
    Object.assign(h.props, { id: 19, iconOnly: true, canDelete: true, recordTitle: '另一条分析' });
    h.render();
    await h.settle();
    assert.equal(calls.length, 0);
    const trigger = h.nodes().find((n) => n.props?.['aria-label'] === '删除分析记录：另一条分析');
    assert.equal(trigger.props.children.type, 'svg');
    assert.equal(trigger.props.children.props.name, 'trash');
    assert.equal(trigger.props.type, 'button');
    trigger.props.onClick();
    h.render();
    await h.settle();
    assert.deepEqual(calls, ['/api/projects/4/code-analysis/19/deletion']);
    assert.equal(h.button('确认删除').props.disabled, false);
  } finally {
    h.close();
  }
});
test('conflict keeps the record, requires recheck; unmount aborts late success', async () => {
  let fail = true,
    release;
  const h = harness(async (url, options) => {
    if (options.method !== 'POST') return info;
    if (fail) throw Error('analysis_delete_changed');
    return new Promise((r) => (release = r));
  });
  try {
    h.render();
    await h.settle();
    h.button('删除记录').props.onClick();
    h.render();
    await h.settle();
    h.button('确认删除').props.onClick();
    await h.settle();
    assert.equal(h.deleted, 0);
    assert.equal(h.button('确认删除').props.disabled, true);
    assert.ok(h.button('重新核对'));
    h.button('重新核对').props.onClick();
    h.render();
    await h.settle();
    fail = false;
    h.button('确认删除').props.onClick();
    await new Promise(setImmediate);
    h.close();
    release({ id: 7, project_id: 4, deleted: true });
    await new Promise(setImmediate);
    assert.equal(h.deleted, 0);
  } finally {
    h.close();
  }
});
