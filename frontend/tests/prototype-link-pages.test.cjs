const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const file = path.resolve(__dirname, '../src/PrototypeLinkPages.tsx');
const code = compileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function nodes(node) {
  if (Array.isArray(node)) return node.flatMap(nodes);
  return node?.props ? [node, ...nodes(node.props.children)] : [];
}

for (const [filename, root] of [
  ['page-1.html', 'https://prototype.geekuat.com/p/Test123'],
  ['order-detail.html', 'https://prototype.geekuat.com/p/Test123'],
  ['admin/settings-store-edit.html', 'http://127.0.0.1:4173'],
  ['admin/docs/rules.html', 'http://127.0.0.1:4173'],
]) {
  test(`link picker reads and selects a project-owned ${filename} catalog`, async () => {
    const state = [];
    let position = 0;
    const react = {
      useState(initial) {
        const index = position++;
        if (!(index in state)) state[index] = initial;
        return [
          state[index],
          (value) => {
            state[index] = value;
          },
        ];
      },
      useRef(initial) {
        return { current: initial };
      },
      useEffect() {},
    };
    const calls = [],
      changes = [];
    const exports = {};
    evaluateModule(
      code,
      (name) => {
        if (name === 'react') return react;
        if (name.endsWith('.css')) return {};
        if (name === './api/http')
          return {
            apiRequest: async (url, options) => {
              calls.push({ url, signal: options.signal });
              return {
                snapshot: 'a'.repeat(64),
                pages: [
                  {
                    file: filename,
                    path: '订单 / 详情',
                    url: `${root}/pages/${filename}`,
                  },
                  {
                    file: 'page-2.html',
                    path: '钱包 / 首页',
                    url: 'https://prototype.geekuat.com/p/Test123/pages/page-2.html',
                  },
                ],
              };
            },
          };
        return require(name);
      },
      exports,
    );
    let value = { paths: [], snapshot: '' };
    const props = {
      projectId: 3,
      documentId: 7,
      onSessionEnd() {},
      onChange: (next) => {
        value = next;
        changes.push(next);
      },
    };
    const render = () => {
      position = 0;
      return nodes(exports.PrototypeLinkPages({ ...props, value }));
    };
    await render()
      .find((n) => n.type === 'button' && n.props.children === '读取页面')
      .props.onClick();
    await new Promise(setImmediate);
    assert.equal(calls[0].url, '/api/projects/3/prototypes/7/pages');
    assert.equal(changes[0].snapshot, 'a'.repeat(64));
    const page = render().find((n) => n.type === 'input' && n.props.type === 'checkbox');
    page.props.onChange({ target: { checked: true } });
    assert.deepEqual(value.paths, [filename]);
    render()
      .find((n) => n.type === 'button' && n.props.children === '选择此组')
      .props.onClick();
    assert.deepEqual(value.paths, [filename]);
  });
}

test('catalog boundary rejects paths and preview URLs outside the static page scope', () => {
  const exports = {};
  evaluateModule(
    code + '\nexports.parseCatalog = parseCatalog;',
    (name) => (name.endsWith('.css') ? {} : name === './api/http' ? {} : require(name)),
    exports,
  );
  for (const [file, url] of [
    ['../order.html', 'https://prototype.geekuat.com/p/Test123/pages/../order.html'],
    ['order.html', 'https://example.com/p/Test123/pages/order.html'],
    ['order.html', 'https://prototype.geekuat.com/p/Test123/pages/different.html'],
    ['order.html', 'https://prototype.geekuat.com/p/Test123/pages/order.html?next=x'],
    ['admin/order.html', 'http://127.0.0.1:8000/pages/admin/order.html'],
    ['admin/order.html', 'http://localhost:4173/pages/admin/order.html'],
    ['admin/order.html', 'http://127.0.0.1:4173/pages/admin/order.html#x'],
    ['admin/../order.html', 'http://127.0.0.1:4173/pages/admin/../order.html'],
  ]) {
    assert.throws(
      () =>
        exports.parseCatalog({ snapshot: 'a'.repeat(64), pages: [{ file, path: '订单', url }] }),
      /prototype_link_unsupported/,
    );
  }
});
