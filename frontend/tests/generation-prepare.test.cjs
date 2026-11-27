const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test'),
  assert = require('node:assert/strict'),
  fs = require('node:fs'),
  path = require('node:path'),
  ts = require('typescript');
const text = (node) =>
  Array.isArray(node)
    ? node.map(text).join('')
    : node && typeof node === 'object'
      ? text(node.props?.children)
      : typeof node === 'string' || typeof node === 'number'
        ? String(node)
        : '';
function harness() {
  const state = [],
    refs = [],
    requests = [],
    cache = new Map();
  let cursor = 0,
    refCursor = 0;
  const react = {
    useState(initial) {
      const i = cursor++;
      if (!(i in state)) state[i] = typeof initial === 'function' ? initial() : initial;
      return [
        state[i],
        (v) => {
          state[i] = typeof v === 'function' ? v(state[i]) : v;
        },
      ];
    },
    useRef(initial) {
      return (refs[refCursor++] ||= { current: initial });
    },
    useId: () => 'prepare-form',
    useEffect() {},
  };
  function load(file) {
    if (cache.has(file)) return cache.get(file);
    const exports = {};
    cache.set(file, exports);
    const js = compileModule(fs.readFileSync(file, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    evaluateModule(
      js,
      (dep) => {
        if (dep === 'react') return react;
        const stubs = {
          './CaseDialog': { CaseDialog: 'dialog' },
          './Form': { Form: 'form' },
          './FormSelect': { FormSelect: 'select' },
          './CodeAnalysisNew': { CodeFileTree: 'file-tree' },
          './PrototypeLinkPages': { PrototypeLinkPages: 'pages' },
          './GitVersionPicker': { GitVersionPicker: 'versions' },
          './generationApi': { generationError: (e) => e.message },
          './codeAnalysisApi': { codeError: (e) => e.message },
          './prototypeApi': {},
          './api/http': {},
        };
        if (stubs[dep]) return stubs[dep];
        if (!dep.startsWith('.')) return require(dep);
        const base = path.resolve(path.dirname(file), dep);
        return load(base + (fs.existsSync(base + '.ts') ? '.ts' : '.tsx'));
      },
      exports,
    );
    return exports;
  }
  const New = load(path.resolve(__dirname, '../src/CaseGenerationNew.tsx')).CaseGenerationNew,
    props = {
      projectId: 7,
      user: { id: 3 },
      options: {
        materials: [
          {
            id: 8,
            name: '合成需求',
            purpose: 'REQUIREMENT',
            kind: 'FILE',
            versions: [{ id: 9, number: 1, filename: '合成需求.txt' }],
          },
        ],
      },
      prototypes: [],
      snapshot: { items: [], categories: [], revision: 2 },
      records: [],
      busy: false,
      serverError: '',
      onClose() {},
      onSessionEnd() {},
      onCreate: (draft) =>
        new Promise((resolve, reject) => requests.push({ draft, resolve, reject })),
    };
  function render() {
    cursor = 0;
    refCursor = 0;
    const nodes = [];
    function walk(n) {
      if (Array.isArray(n)) return n.forEach(walk);
      if (!n || typeof n !== 'object') return;
      nodes.push(n);
      walk(n.props?.children);
      walk(n.props?.footer);
    }
    walk(New(props));
    return nodes;
  }
  function field(label, type) {
    const nodes = render(),
      row = nodes.find((n) => n.type === 'label' && text(n).includes(label));
    return nodes.find((n) => n.type === type && row?.props.children?.includes?.(n));
  }
  function fill() {
    field('名称', 'input').props.onChange({ target: { value: '新生成范围' } });
    render()
      .find((n) => n.type === 'input' && n.props.type === 'checkbox')
      .props.onChange({ target: { checked: true } });
  }
  const button = (label) => render().find((n) => n.type === 'button' && text(n) === label),
    submit = () =>
      render()
        .find((n) => n.type === 'form')
        .props.onSubmit({ preventDefault() {} });
  return { props, render, field, fill, button, submit, requests };
}

test('prepare locks immediately against double submission and exposes busy feedback and frozen fields', async () => {
  const h = harness();
  h.fill();
  const first = h.submit(),
    second = h.submit();
  assert.equal(h.requests.length, 1);
  assert.equal(h.button('正在准备并启动…').props.disabled, true);
  assert.equal(h.button('取消').props.disabled, true);
  assert.equal(h.render().find((n) => n.type === 'dialog').props.busy, true);
  assert.equal(h.render().find((n) => n.type === 'fieldset').props.disabled, true);
  assert.equal(h.render().find((n) => n.type === 'form').props['aria-busy'], true);
  assert.ok(
    h
      .render()
      .some((n) => n.props?.role === 'status' && text(n).includes('正在准备并启动生成任务')),
  );
  h.requests[0].resolve(true);
  await Promise.all([first, second]);
});

test('prepare failure restores controls, displays server error inside modal and retries the same fixed input id', async () => {
  const h = harness();
  h.fill();
  let pending = h.submit();
  h.props.serverError = '资料读取失败，请重试';
  h.requests[0].resolve(false);
  await pending;
  assert.equal(h.button('开始用例生成').props.disabled, false);
  assert.equal(h.button('取消').props.disabled, false);
  assert.equal(h.render().find((n) => n.type === 'fieldset').props.disabled, false);
  assert.ok(
    h.render().some((n) => n.props?.role === 'alert' && text(n) === '资料读取失败，请重试'),
  );
  const id = h.requests[0].draft.id;
  pending = h.submit();
  assert.equal(h.requests[1].draft.id, id);
  h.requests[1].resolve(false);
  await pending;
  h.field('名称', 'input').props.onChange({ target: { value: '修改后的范围' } });
  pending = h.submit();
  assert.notEqual(h.requests[2].draft.id, id);
  h.requests[2].resolve(false);
  await pending;
});

test('parent busy state prevents new work and rejection leaves editable input intact', async () => {
  const h = harness();
  h.fill();
  h.props.busy = true;
  await h.submit();
  assert.equal(h.requests.length, 0);
  assert.equal(h.button('正在准备并启动…').props.disabled, true);
  h.props.busy = false;
  const pending = h.submit();
  h.requests[0].reject(Error('连接中断'));
  await pending;
  assert.equal(h.field('名称', 'input').props.value, '新生成范围');
  assert.ok(h.render().some((n) => n.props?.role === 'alert' && text(n) === '连接中断'));
  assert.equal(h.button('开始用例生成').props.disabled, false);
});
