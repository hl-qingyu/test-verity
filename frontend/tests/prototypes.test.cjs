const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
function load(file, react = React, overrides = {}) {
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const exports = {};
  new Function('exports', 'require', code)(exports, (name) =>
    overrides[name]
      ? overrides[name]
      : name === 'react'
        ? react
        : name.startsWith('.')
          ? load(
              path.resolve(
                path.dirname(file),
                name +
                  (fs.existsSync(path.resolve(path.dirname(file), name + '.ts')) ? '.ts' : '.tsx'),
              ),
              react,
              overrides,
            )
          : require(name),
  );
  return exports;
}
const api = load(path.resolve(__dirname, '../src/prototypeApi.ts'));

test('reading files defaults to all selected, including more than 1000 files', async () => {
  const files = Array.from({ length: 1001 }, (_, i) => ({
    path: `page-${i}.html`,
    sha: 'a'.repeat(40),
    size: 10,
  }));
  const updates = [];
  const { PrototypeEditor } = load(
    path.resolve(__dirname, '../src/PrototypeEditor.tsx'),
    {
      ...React,
      useState: (initial) => [initial, (value) => updates.push(value)],
      useRef: (value) => ({ current: value }),
      useEffect: () => {},
    },
    {
      './api/http': {
        apiRequest: async () => ({ commit: 'b'.repeat(40), full_name: 'team/prototype', files }),
      },
    },
  );
  const tree = PrototypeEditor({
    base: '/api/projects/1/prototypes',
    kind: 'GITHUB',
    source: {
      name: '原型',
      repository_id: 4,
      branch: 'main',
      path: '',
      selected_paths: ['page-0.html'],
    },
    connections: [
      {
        id: 1,
        name: '本人连接',
        repositories: [{ id: 4, name: 'team/prototype', branch: 'main' }],
      },
    ],
    library: { revision: 0, groups: [], sources: [] },
    onSaved() {},
    onClose() {},
    onSessionEnd() {},
  });
  function find(node) {
    if (Array.isArray(node)) return node.map(find).find(Boolean);
    if (!node || !node.props) return null;
    return node.type === 'button' && node.props.children === '读取文件清单'
      ? node
      : find(node.props.children);
  }
  find(tree).props.onClick();
  await new Promise(setImmediate);
  assert.deepEqual(
    updates.find((value) => Array.isArray(value) && value.length === 1001),
    files.map((f) => f.path),
  );
  assert.equal(
    api.parsePrototypeScope({ commit: 'b'.repeat(40), full_name: 'team/prototype', files }).files
      .length,
    1001,
  );
});
const link = {
  id: 1,
  kind: 'LINK',
  name: '原型',
  description: '',
  group_id: null,
  position: 0,
  url: 'https://example.com/prototype',
  repository_id: null,
  repository_name: null,
  github_id: null,
  branch: null,
  path: null,
  selected_paths: [],
  latest_commit: null,
  checked_at: null,
  files: [],
  current: null,
};
test('live source responses validate identity, scope and commit metadata without manual versions', () => {
  assert.equal(
    api.parsePrototypeLibrary({ revision: 2, groups: [], sources: [link] }).sources[0].current,
    null,
  );
  for (const url of [
    'javascript:alert(1)',
    'file:///private',
    'data:text/html,hello',
    'https://user:secret@example.com',
    'https://example.com\\x',
  ])
    assert.equal(api.prototypeUrl(url), '');
  assert.throws(() => api.parsePrototype({ ...link, url: 'javascript:alert(1)' }));
  assert.throws(() =>
    api.parsePrototypeLibrary({ revision: 1, groups: [], sources: [{ ...link, group_id: 123 }] }),
  );
  const github = {
    ...link,
    kind: 'GITHUB',
    url: null,
    github_id: 3,
    repository_id: 4,
    repository_name: 'team/prototype',
    branch: 'main',
    path: 'prototype',
    selected_paths: ['prototype/index.html'],
    latest_commit: 'a'.repeat(40),
    files: [{ path: 'prototype/index.html', sha: 'b'.repeat(40), size: 20 }],
  };
  assert.equal(
    api.parsePrototypeCheck({ changed: true, previous_commit: 'c'.repeat(40), source: github })
      .changed,
    true,
  );
  assert.throws(() =>
    api.parsePrototypeCheck({ changed: 'true', previous_commit: null, source: github }),
  );
  assert.equal(api.parsePrototype({ ...github, path: '' }).path, '');
  assert.throws(() => api.parsePrototype({ ...github, latest_commit: 'main' }));
  assert.throws(() =>
    api.parsePrototype({ ...github, files: [{ path: 'x', sha: 'bad', size: -1 }] }),
  );
  assert.deepEqual(
    api.parsePrototypeOptions([
      {
        id: 1,
        name: '本人连接',
        repositories: [{ id: 4, name: 'team/prototype', branch: 'main' }],
      },
    ])[0].repositories[0].id,
    4,
  );
});
test('link preview waits for click, isolates external frames and preserves the new-window fallback', () => {
  const previous = global.location;
  global.location = { origin: 'https://verity.example.com' };
  try {
    const file = path.resolve(__dirname, '../src/PrototypeLinkPreview.tsx');
    const { PrototypeLinkPreview } = load(file);
    const idle = renderToStaticMarkup(
      React.createElement(PrototypeLinkPreview, { name: '页面', url: link.url }),
    );
    assert.ok(!idle.includes('<iframe'));
    assert.match(idle, /未保存页面快照/);
    assert.match(idle, /rel="noopener noreferrer"/);
    const loaded = load(file, {
      ...React,
      useState: (initial) => [typeof initial === 'number' ? 1 : false, () => {}],
    }).PrototypeLinkPreview;
    const active = renderToStaticMarkup(loaded({ name: '<unsafe>', url: link.url }));
    assert.match(active, /sandbox="allow-scripts allow-same-origin allow-popups allow-downloads"/);
    assert.doesNotMatch(active, /allow-top-navigation|allow-popups-to-escape-sandbox/);
    assert.match(active, /referrerPolicy="no-referrer"/i);
    assert.match(active, /&lt;unsafe&gt;/);
    assert.match(active, /刷新预览/);
    const sameOrigin = renderToStaticMarkup(
      loaded({ name: '本站', url: 'https://verity.example.com/private' }),
    );
    assert.ok(!sameOrigin.includes('<iframe'));
  } finally {
    global.location = previous;
  }
});

test('HTML upload sends the original file without image decoding and retains the version target', async () => {
  const file = new File(['<html><script>alert(1)</script></html>'], 'page.HTML');
  const requests = [],
    saved = [],
    states = [];
  let index = 0;
  const { PrototypeEditor } = load(
    path.resolve(__dirname, '../src/PrototypeEditor.tsx'),
    {
      ...React,
      useState: (initial) => {
        const n = index++;
        // Files is the second array state (selected paths comes first).
        if (Array.isArray(initial)) states.push(n);
        return [Array.isArray(initial) && states.length === 2 ? [file] : initial, () => {}];
      },
      useRef: (value) => ({ current: value }),
      useEffect: () => {},
    },
    {
      './prototypeApi': {
        ...api,
        prototypeRequest: async (url, options) => {
          requests.push({ url, options });
          return { revision: 8, groups: [], sources: [] };
        },
      },
    },
  );
  const tree = PrototypeEditor({
    base: '/api/projects/1/prototypes',
    kind: 'FILE',
    html: true,
    source: { id: 9, name: '页面', kind: 'FILE' },
    library: { revision: 7, groups: [], sources: [] },
    connections: [],
    onSaved: (value, done) => saved.push(done),
    onClose() {},
    onSessionEnd() {},
  });
  function find(node) {
    if (Array.isArray(node)) return node.map(find).find(Boolean);
    if (!node?.props) return null;
    return node.props.onSubmit ? node : find(node.props.children);
  }
  find(tree).props.onSubmit({ preventDefault() {} });
  await new Promise(setImmediate);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.body, file);
  assert.equal(requests[0].options.headers['Content-Type'], 'application/octet-stream');
  const url = new URL(requests[0].url, 'https://verity.example');
  assert.equal(url.searchParams.get('document_id'), '9');
  assert.equal(url.searchParams.get('revision'), '7');
  assert.equal(url.searchParams.get('filename'), 'page.HTML');
  assert.deepEqual(saved, [false, true]);
});
