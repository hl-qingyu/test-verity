const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test'),
  assert = require('node:assert/strict'),
  fs = require('node:fs'),
  path = require('node:path'),
  ts = require('typescript'),
  React = require('react');
function load(file, overrides = {}) {
  const code = compileModule(fs.readFileSync(file, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText,
    exports = {};
  evaluateModule(
    code,
    (name) => {
      if (overrides[name]) return overrides[name];
      if (name.endsWith('.css')) return {};
      if (!name.startsWith('.')) return require(name);
      const base = path.resolve(path.dirname(file), name);
      return load(base + (fs.existsSync(base + '.ts') ? '.ts' : '.tsx'), overrides);
    },
    exports,
  );
  return exports;
}
const source = path.resolve(__dirname, '../src/GitVersionPicker.tsx'),
  api = load(source),
  sha = 'a'.repeat(40),
  row = { name: sha.slice(0, 12), sha, message: '修正核销校验', date: '2026-10-08T00:00:00Z' };
test('version metadata is scoped to the requested project, repository, kind, page and fixed SHA', () => {
  const response = {
    project_id: 1,
    association_id: 4,
    kind: 'commits',
    page: 1,
    ref: 'main',
    items: [row],
    has_more: false,
  };
  const parse = (v) => api.parseGitVersions(v, 1, 4, 'commits', 1, 'main');
  assert.equal(parse(response).items[0].message, '修正核销校验');
  for (const patch of [
    { project_id: 2 },
    { association_id: 9 },
    { kind: 'tags' },
    { page: 2 },
    { ref: 'other' },
    { items: [{ ...row, sha: 'short' }] },
    { items: [{ ...row, date: 'bad' }] },
  ])
    assert.throws(() => parse({ ...response, ...patch }), /invalid/);
});
test('version picker reads history, paginates, searches and selects full SHA without manual entry', async () => {
  const state = new Map();
  let hook = 0,
    selected = '',
    pendingResolve;
  const calls = [];
  const hooks = {
    ...React,
    useEffect: () => {},
    useState: (initial) => {
      const key = hook++;
      if (!state.has(key)) state.set(key, typeof initial === 'function' ? initial() : initial);
      return [
        state.get(key),
        (next) => state.set(key, typeof next === 'function' ? next(state.get(key)) : next),
      ];
    },
    useRef: (initial) => {
      const key = hook++;
      if (!state.has(key)) state.set(key, { current: initial });
      return state.get(key);
    },
  };
  const request = async (url, options) => {
    calls.push({ url, options });
    const params = new URL(url, 'http://localhost').searchParams,
      kind = params.get('kind'),
      page = Number(params.get('page')),
      ref = params.get('ref');
    const result = {
      project_id: 1,
      association_id: 4,
      kind,
      page,
      ref,
      items:
        page === 1
          ? [row]
          : [{ ...row, sha: 'b'.repeat(40), name: 'bbbbbbbbbbbb', message: '新增手动核销' }],
      has_more: page === 1,
    };
    if (pendingResolve === 'wait')
      return new Promise((resolve) => (pendingResolve = () => resolve(result)));
    return result;
  };
  const { GitVersionPicker } = load(source, {
    react: hooks,
    './api/http': { apiRequest: request },
  });
  const props = {
    label: '旧基准',
    projectId: 1,
    repositoryId: 4,
    connectionId: 3,
    defaultBranch: 'main',
    value: '',
    onChange: (sha) => {
      selected = sha;
      props.value = sha;
    },
    onSessionEnd: () => {},
  };
  function render() {
    hook = 0;
    return GitVersionPicker(props);
  }
  function nodes(node) {
    if (!node || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(nodes);
    return [node, ...nodes(node.props?.children)];
  }
  const flush = () => new Promise(setImmediate);
  let tree = render();
  nodes(tree)
    .find((n) => n.type === 'button' && n.props.children === '读取版本列表')
    .props.onClick();
  await flush();
  tree = render();
  assert.match(calls[0].url, /repositories\/4\/versions/);
  assert.match(calls[0].url, /kind=commits/);
  assert.match(calls[0].url, /ref=main/);
  assert.ok(calls[0].options.signal);
  assert.ok(!calls[0].options.method);
  nodes(tree)
    .find((n) => n.props?.className?.startsWith('git-version-option'))
    .props.onClick();
  assert.equal(selected, sha);
  nodes(render())
    .find((n) => n.type === 'button' && n.props.children === '加载更多')
    .props.onClick();
  await flush();
  tree = render();
  assert.match(calls[1].url, /page=2/);
  assert.equal(
    nodes(tree).filter((n) => n.props?.className?.startsWith('git-version-option')).length,
    2,
  );
  nodes(tree)
    .find((n) => n.type === 'input' && n.props.type === 'search')
    .props.onChange({ target: { value: '手动' } });
  tree = render();
  assert.equal(
    nodes(tree).filter((n) => n.props?.className?.startsWith('git-version-option')).length,
    1,
  );
  nodes(tree)
    .find((n) => n.type === 'button' && n.props.children === 'Tag')
    .props.onClick();
  assert.equal(selected, '');
  tree = render();
  nodes(tree)
    .find((n) => n.type === 'button' && n.props.children === '读取版本列表')
    .props.onClick();
  await flush();
  assert.match(calls.at(-1).url, /kind=tags/);
  assert.match(calls.at(-1).url, /ref=$/);
  pendingResolve = 'wait';
  tree = render();
  nodes(tree)
    .find((n) => n.type === 'button' && n.props.children === '刷新版本列表')
    .props.onClick();
  const resolve = pendingResolve;
  const controller = [...state.values()].find((v) => v?.current instanceof AbortController);
  controller.current.abort();
  resolve();
  await flush();
  assert.equal(
    nodes(render()).filter((n) => n.props?.className?.startsWith('git-version-option')).length,
    1,
  );
});
