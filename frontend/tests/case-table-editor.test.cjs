const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function harness(caseIds) {
  const state = [],
    refs = [],
    requests = [],
    saved = [];
  let cursor = 0,
    refCursor = 0;
  const cache = new Map();
  const react = {
    useId: () => 'editor-page-jump',
    useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial;
      return [
        state[index],
        (value) => {
          state[index] = typeof value === 'function' ? value(state[index]) : value;
        },
      ];
    },
    useRef(initial) {
      const index = refCursor++;
      return (refs[index] ||= { current: initial });
    },
    useEffect() {},
  };
  function load(name) {
    if (cache.has(name)) return cache.get(name);
    const exports = {};
    cache.set(name, exports);
    const code = ts.transpileModule(fs.readFileSync(name, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    new Function('exports', 'require', code)(exports, (dep) => {
      if (dep === 'react') return react;
      if (dep === 'react-router-dom') return { useBlocker: () => ({ state: 'unblocked' }) };
      if (dep === './FormSelect')
        return {
          Select: (props) => ({
            type: 'select',
            props: { ...props, onChange: (event) => props.onChange(event.target.value) },
          }),
        };
      if (dep === './CaseDialog') return { CaseDialog: 'dialog' };
      if (dep === './api/http')
        return {
          apiRequest: async (url, options) => {
            requests.push({ url, body: JSON.parse(options.body) });
            return { revision: 5, next_number: 13, categories: [], updated: 2 };
          },
        };
      if (!dep.startsWith('.')) return require(dep);
      const file = path.resolve(path.dirname(name), dep);
      return load(fs.existsSync(file + '.ts') ? file + '.ts' : file + '.tsx');
    });
    return exports;
  }
  const api = load(path.resolve(__dirname, '../src/caseApi.ts'));
  const Editor = load(path.resolve(__dirname, '../src/CaseTableEditor.tsx')).CaseTableEditor;
  const snapshot = {
    revision: 4,
    next_number: 13,
    categories: [],
    total: 12,
    page: 1,
    page_size: 100,
    items: Array.from({ length: 12 }, (_, i) => ({
      ...api.blankDesign(),
      id: i + 1,
      number: i + 1,
      serial: i + 1,
      title: `场景${i + 1}`,
      tester: '原人员',
      result: '通过',
    })),
  };
  if (caseIds) snapshot.items = snapshot.items.filter((row) => caseIds.includes(row.id));
  function render() {
    cursor = 0;
    refCursor = 0;
    const tree = Editor({
      base: '/api/projects/7/cases',
      snapshot,
      search: {
        conditions: [],
        page: 1,
        page_size: 100,
        category_id: null,
        ...(caseIds ? { case_ids: caseIds } : {}),
      },
      singleId: null,
      scopeLabel: '整个项目',
      onClose() {},
      onSaved: (value) => saved.push(value),
      onSessionEnd() {},
    });
    const nodes = [];
    function walk(node) {
      if (Array.isArray(node)) return node.forEach(walk);
      if (!node || typeof node !== 'object') return;
      if (typeof node.type === 'function') return walk(node.type(node.props));
      nodes.push(node);
      walk(node.props?.children);
    }
    walk(tree);
    return nodes;
  }
  const label = (node) =>
    Array.isArray(node)
      ? node.map(label).join('')
      : typeof node === 'string' || typeof node === 'number'
        ? String(node)
        : '';
  const button = (text) => {
    const found = render().find(
      (n) => n.type === 'button' && label(n.props.children).includes(text),
    );
    assert.ok(found, text);
    assert.ok(!found.props.disabled, text);
    return found;
  };
  const field = (text) => {
    const found = render().find((n) => n.props?.['aria-label'] === text);
    assert.ok(found, text);
    return found;
  };
  return { render, button, field, requests, saved, snapshot };
}

test('row edits survive page changes and only submit after application confirmation', async () => {
  const h = harness();
  h.field('用例 1 验证用例子项').props.onChange({ target: { value: '修改场景' } });
  h.field('跳转页码').props.onChange({ target: { value: '2' } });
  h.button('确定').props.onClick();
  h.field('用例 12 测试人员').props.onChange({ target: { value: '' } });
  h.field('跳转页码').props.onChange({ target: { value: '1' } });
  h.button('确定').props.onClick();
  assert.equal(h.field('用例 1 验证用例子项').props.value, '修改场景');
  h.button('保存 2 条修改').props.onClick();
  assert.equal(h.requests.length, 0);
  h.button('确认保存').props.onClick();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(h.requests[0].body.rows, [
    { id: 1, changes: { title: '修改场景' } },
    { id: 12, changes: { tester: '' } },
  ]);
  assert.equal(h.requests[0].body.revision, 4);
  assert.equal(h.requests[0].body.confirmed, true);
  assert.equal(h.snapshot.items[0].title, '场景1');
  assert.equal(h.saved.length, 1);
});

test('uniform editing submits only checked fields, including explicit blank values', async () => {
  const h = harness();
  h.button('统一修改字段').props.onClick();
  const checkbox = h.render().filter((n) => n.type === 'input' && n.props.type === 'checkbox')[10];
  checkbox.props.onChange({ target: { checked: true } });
  assert.equal(h.field('统一修改测试人员').props.value, '');
  h.button('核对并保存').props.onClick();
  assert.equal(h.requests.length, 0);
  h.button('确认保存').props.onClick();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(h.requests[0].body.changes, { tester: '' });
  assert.equal(h.requests[0].body.mode, 'uniform');
  assert.ok(!('rows' in h.requests[0].body));
});

test('selected editing keeps the frozen cross-page IDs in the save request', async () => {
  const h = harness([1, 12]);
  h.field('用例 12 测试人员').props.onChange({ target: { value: '已选' } });
  h.button('保存 1 条修改').props.onClick();
  h.button('确认保存').props.onClick();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(h.requests[0].body.search.case_ids, [1, 12]);
  assert.deepEqual(h.requests[0].body.rows, [{ id: 12, changes: { tester: '已选' } }]);
});
