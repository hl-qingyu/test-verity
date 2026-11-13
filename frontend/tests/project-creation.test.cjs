const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function harness(role, project = null) {
  const source = fs.readFileSync(path.resolve(__dirname, '../src/Projects.tsx'), 'utf8');
  const code = ts.transpileModule(
    source.slice(
      source.indexOf('function ProjectForm('),
      source.indexOf('export function CreateProjectDialog('),
    ) + '\nexports.ProjectForm = ProjectForm;',
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } },
  ).outputText;
  const states = [],
    requests = [];
  let cursor = 0,
    saved;
  const useState = (initial) => {
    const i = cursor++;
    if (!(i in states)) states[i] = initial;
    return [states[i], (value) => (states[i] = value)];
  };
  const exported = {};
  new Function(
    'exports',
    'require',
    'useState',
    'Form',
    'PersonPicker',
    'apiRequest',
    'requestError',
    code,
  )(
    exported,
    require,
    useState,
    'form',
    'person-picker',
    (url, options) =>
      new Promise((resolve, reject) => requests.push({ url, options, resolve, reject })),
    (e) => e.message,
  );
  const user = { id: 8, display_name: '创建人', platform_role: role };
  function render() {
    cursor = 0;
    return exported.ProjectForm({ project, user, onSessionEnd() {}, onSaved: (p) => (saved = p) });
  }
  function nodes(node) {
    return node && typeof node === 'object'
      ? [node, ...[node.props?.children].flat(Infinity).flatMap(nodes)]
      : [];
  }
  const all = () => nodes(render());
  const button = () => all().find((node) => node.type === 'button');
  return { render, all, button, requests, saved: () => saved };
}

test('all ordinary roles can submit a project owned by themselves and recover from failure', async () => {
  for (const role of ['USER', 'TEST', 'DEV', 'PRODUCT', 'MANAGER']) {
    const h = harness(role);
    assert.equal(h.button().props.disabled, false);
    assert.ok(!h.all().some((node) => node.type === 'person-picker'));
    const input = h.all().filter((node) => node.type === 'input');
    assert.ok(input.every((node) => !node.props.disabled));
    input[0].props.onChange({ target: { value: '本人项目' } });
    const pending = h.render().props.onSubmit({ preventDefault() {} });
    void h.render().props.onSubmit({ preventDefault() {} });
    assert.equal(h.requests.length, 1);
    assert.equal(h.requests[0].url, '/api/projects');
    assert.equal(h.requests[0].options.method, 'POST');
    assert.deepEqual(JSON.parse(h.requests[0].options.body), {
      name: '本人项目',
      description: '',
      owner_id: 8,
      version: 0,
    });
    assert.equal(h.button().props.disabled, true);
    h.requests[0].reject(Error('项目标识已存在'));
    await pending;
    assert.ok(h.all().some((node) => node.props.role === 'alert'));
    assert.equal(h.saved(), undefined);
    assert.equal(h.button().props.disabled, false);
    const retry = h.render().props.onSubmit({ preventDefault() {} });
    const result = { id: 7, owner_id: 8, can_manage: true };
    h.requests[1].resolve(result);
    await retry;
    assert.deepEqual(h.saved(), result);
  }
});

test('administrator still selects an owner and existing members cannot edit projects', async () => {
  const admin = harness('ADMIN');
  assert.equal(admin.button().props.disabled, true);
  admin
    .all()
    .find((node) => node.type === 'person-picker')
    .props.onChange(9);
  assert.equal(admin.button().props.disabled, false);
  const pending = admin.render().props.onSubmit({ preventDefault() {} });
  assert.equal(JSON.parse(admin.requests[0].options.body).owner_id, 9);
  admin.requests[0].resolve({ id: 7 });
  await pending;

  const member = harness('USER', { id: 7, owner_id: 9, owner_name: '负责人', can_manage: false });
  assert.equal(member.button(), undefined);
  await member.render().props.onSubmit({ preventDefault() {} });
  assert.equal(member.requests.length, 0);
});
