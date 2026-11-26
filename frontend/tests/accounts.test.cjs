const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

test('account role choices preserve legacy accounts and submit the selected role', async () => {
  const originalFetch = globalThis.fetch;
  const originalFormData = globalThis.FormData;
  const user = { id: 1, login_name: 'admin_demo', display_name: '管理员', platform_role: 'ADMIN' };
  const account = {
    id: 2,
    login_name: 'member_demo',
    display_name: '成员',
    platform_role: 'USER',
    status: 'ACTIVE',
    created_at: '2026-10-16T00:00:00Z',
    updated_at: '2026-10-16T00:00:00Z',
  };
  let states = [],
    cursor = 0,
    effects = [],
    seen,
    values;
  const react = {
    ...require('react'),
    useState(initial) {
      const i = cursor++;
      if (!(i in states)) states[i] = initial;
      return [states[i], (value) => (states[i] = value)];
    },
    useEffect(fn) {
      effects.push(fn);
    },
    useRef: () => ({ current: { showModal() {} } }),
  };
  const Form = () => null;
  const Select = () => null;
  function load(name) {
    const exported = {};
    const code = compileModule(fs.readFileSync(path.resolve(__dirname, '../src', name), 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    evaluateModule(
      code,
      (id) => {
        if (id === 'react') return react;
        if (id === './Form') return { Form };
        if (id === './FormSelect') return { Select };
        if (id === './PageJump') return { PageJump: () => null };
        if (id === './passwordTransport')
          return {
            postEncrypted: async (url, payload) => {
              seen = { url, payload, encrypted: true };
              return Response.json({ ...account, ...payload }, { status: 201 });
            },
          };
        if (id === './accountRoles') return load('accountRoles.ts');
        return require(id);
      },
      exported,
    );
    return exported;
  }
  function nodes(node) {
    return node && typeof node === 'object'
      ? [node, ...[node.props?.children].flat(Infinity).flatMap(nodes)]
      : [];
  }
  function render(component, props) {
    cursor = 0;
    effects = [];
    return component(props);
  }
  try {
    globalThis.fetch = async (url, options) => {
      if (options?.method === 'PATCH') {
        seen = { url, options, payload: JSON.parse(options.body) };
        return Response.json({ ...account, ...seen.payload });
      }
      return Response.json({ items: [account], total: 1 });
    };
    globalThis.FormData = class {
      get(name) {
        return values[name];
      }
    };
    const { Accounts } = load('Accounts.tsx');
    const props = { user, onSessionEnd() {}, onUserChange() {} };
    render(Accounts, props);
    await effects[0]();
    await new Promise((resolve) => setImmediate(resolve));
    let tree = render(Accounts, props);
    const edit = nodes(tree).find(
      (node) => node.type === 'button' && node.props.children === '修改',
    );
    edit.props.onClick();
    tree = render(Accounts, props);
    const dialog = nodes(tree).find((node) => node.props?.action?.kind === 'edit');
    states = [];
    const editTree = render(dialog.type, dialog.props);
    const legacy = nodes(editTree).find(
      (node) => node.type === Select && node.props.name === 'platform_role',
    );
    assert.equal(legacy.props.defaultValue, 'USER');
    assert.deepEqual(
      nodes(legacy)
        .filter((node) => node.type === 'option')
        .map((node) => node.props.value),
      ['USER', 'ADMIN', 'TEST', 'DEV', 'PRODUCT', 'MANAGER'],
    );
    values = { ...account, platform_role: 'MANAGER' };
    await nodes(editTree)
      .find((node) => node.type === Form)
      .props.onSubmit({ preventDefault() {}, currentTarget: {} });
    assert.equal(seen.options.method, 'PATCH');
    assert.equal(seen.payload.platform_role, 'MANAGER');
    assert.equal(seen.payload.updated_at, account.updated_at);

    states = [];
    const createProps = { ...dialog.props, action: { kind: 'create' } };
    const createTree = render(dialog.type, createProps);
    const select = nodes(createTree).find(
      (node) => node.type === Select && node.props.name === 'platform_role',
    );
    assert.equal(select.props.defaultValue, 'TEST');
    assert.deepEqual(
      nodes(select)
        .filter((node) => node.type === 'option')
        .map((node) => node.props.children),
      ['管理员', '测试', '开发', '产品', '经理'],
    );
    values = {
      ...account,
      platform_role: 'PRODUCT',
      password: 'synthetic-password',
      confirm_password: 'synthetic-password',
    };
    await nodes(createTree)
      .find((node) => node.type === Form)
      .props.onSubmit({ preventDefault() {}, currentTarget: {} });
    assert.equal(seen.url, '/api/users');
    assert.equal(seen.encrypted, true);
    assert.equal(seen.payload.platform_role, 'PRODUCT');
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.FormData = originalFormData;
  }
});
