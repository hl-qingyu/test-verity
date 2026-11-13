const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const React = require('react');

test('single-material delete loads impact and only writes after explicit confirmation', async () => {
  const states = [],
    refs = [],
    effects = [],
    requests = [];
  let index = 0,
    refIndex = 0,
    closed = 0,
    deleted = 0;
  const info = {
    id: 7,
    revision: 12,
    name: '需求说明',
    kind: 'FILE',
    versions: 2,
    requirement_references: 1,
    link_references: 3,
  };
  function load(file) {
    const exports = {};
    const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    new Function('exports', 'require', code)(exports, (name) => {
      if (name === 'react')
        return {
          useState(initial) {
            const n = index++;
            if (!(n in states)) states[n] = initial;
            return [states[n], (v) => (states[n] = typeof v === 'function' ? v(states[n]) : v)];
          },
          useRef(initial) {
            return (refs[refIndex++] ||= { current: initial });
          },
          useEffect(effect) {
            if (!effects.length) effects.push(effect);
          },
        };
      if (name === './CaseDialog') return { CaseDialog: 'dialog' };
      if (name === './api/http')
        return {
          apiRequest: async (url, options) => {
            requests.push({ url, options });
            return options.method === 'POST' ? { id: 7, revision: 13 } : info;
          },
        };
      if (name.startsWith('.')) return load(path.resolve(path.dirname(file), name + '.ts'));
      return require(name);
    });
    return exports;
  }
  const { MaterialDeleteDialog } = load(path.resolve(__dirname, '../src/MaterialDeleteDialog.tsx'));
  function render() {
    index = 0;
    refIndex = 0;
    return MaterialDeleteDialog({
      base: '/api/projects/4/documents',
      id: 7,
      onClose: () => closed++,
      onDeleted: () => deleted++,
      onSessionEnd() {},
    });
  }
  const actions = (tree) =>
    React.Children.toArray(tree.props.children).find((n) => n.props?.className === 'row').props
      .children;
  let tree = render();
  assert.equal(actions(tree).at(-1).props.disabled, true);
  effects[0]();
  await new Promise((r) => setImmediate(r));
  tree = render();
  actions(tree)[0].props.onClick();
  assert.equal(closed, 1);
  assert.equal(requests.length, 1);
  assert.equal(deleted, 0);
  actions(tree).at(-1).props.onClick();
  await new Promise((r) => setImmediate(r));
  assert.equal(requests.length, 2);
  assert.equal(requests[1].url, '/api/projects/4/documents/7/delete');
  assert.deepEqual(JSON.parse(requests[1].options.body), { revision: 12, confirmed: true });
  assert.equal(deleted, 1);
});
