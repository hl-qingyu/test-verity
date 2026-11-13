const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const path = require('node:path');

function harness(manager = true) {
  const source = fs.readFileSync(path.resolve(__dirname, '../src/Projects.tsx'), 'utf8');
  const code = ts.transpileModule(
    source.slice(
      source.indexOf('export function ProjectSettings('),
      source.indexOf('\nfunction ProjectMembers('),
    ),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } },
  ).outputText;
  const state = [],
    refs = [],
    requests = [];
  let cursor = 0,
    refCursor = 0,
    refreshed = 0;
  const exports = {};
  const useState = (initial) => {
    const i = cursor++;
    if (!(i in state)) state[i] = initial;
    return [state[i], (v) => (state[i] = typeof v === 'function' ? v(state[i]) : v)];
  };
  const useRef = (initial) => (refs[refCursor++] ||= { current: initial });
  const apiRequest = (url, options) =>
    new Promise((resolve, reject) => requests.push({ url, options, resolve, reject }));
  new Function(
    'exports',
    'require',
    'useState',
    'useRef',
    'ProjectForm',
    'ProjectRepositories',
    'ProjectMembers',
    'LocalCode',
    'CaseDialog',
    'apiRequest',
    'requestError',
    code,
  )(
    exports,
    require,
    useState,
    useRef,
    'project-form',
    'repositories',
    'members',
    'local-code',
    'dialog',
    apiRequest,
    (e) => e.message,
  );
  const props = {
    project: { id: 7, name: '测试项目', version: 3, can_manage: manager },
    user: { platform_role: manager ? 'ADMIN' : 'USER' },
    onChanged: () => refreshed++,
    onSessionEnd() {},
  };
  const text = (node) =>
    Array.isArray(node)
      ? node.map(text).join('')
      : node && typeof node === 'object'
        ? text(node.props.children)
        : typeof node === 'string'
          ? node
          : '';
  function render() {
    cursor = 0;
    refCursor = 0;
    const nodes = [];
    function walk(n) {
      if (Array.isArray(n)) return n.forEach(walk);
      if (!n || typeof n !== 'object') return;
      nodes.push(n);
      walk(n.props.children);
      walk(n.props.footer);
    }
    walk(exports.ProjectSettings(props));
    return nodes;
  }
  const button = (label) => render().find((n) => n.type === 'button' && text(n) === label);
  return { props, render, button, requests, refreshed: () => refreshed };
}
test('project delete is restricted to managers and basic info, and cancel never sends a request', () => {
  const member = harness(false);
  member.button('基本信息').props.onClick();
  assert.equal(member.button('删除项目'), undefined);
  const h = harness();
  assert.equal(h.button('删除项目'), undefined);
  h.button('基本信息').props.onClick();
  h.button('删除项目').props.onClick();
  assert.ok(h.render().some((n) => n.type === 'dialog'));
  h.button('取消').props.onClick();
  assert.equal(
    h.render().some((n) => n.type === 'dialog'),
    false,
  );
  assert.equal(h.requests.length, 0);
});
test('confirmation sends project version once, keeps failures visible, and refreshes projects after success', async () => {
  const h = harness();
  h.button('基本信息').props.onClick();
  h.button('删除项目').props.onClick();
  const confirm = h.button('确认删除');
  const pending = confirm.props.onClick();
  void confirm.props.onClick();
  assert.equal(h.requests.length, 1);
  assert.equal(h.button('正在删除…').props.disabled, true);
  assert.equal(h.button('取消').props.disabled, true);
  assert.equal(h.requests[0].url, '/api/projects/7');
  assert.equal(h.requests[0].options.method, 'DELETE');
  assert.deepEqual(JSON.parse(h.requests[0].options.body), { version: 3, confirmed: true });
  h.requests[0].reject(Error('项目仍有运行任务'));
  await pending;
  assert.ok(h.render().some((n) => n.props.role === 'alert'));
  assert.equal(h.refreshed(), 0);
  const retry = h.button('确认删除').props.onClick();
  h.requests[1].resolve({ id: 7, deleted: true });
  await retry;
  assert.equal(h.refreshed(), 1);
  assert.equal(
    h.render().some((n) => n.type === 'dialog'),
    false,
  );
});
