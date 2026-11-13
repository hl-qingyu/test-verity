const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { webcrypto } = require('node:crypto');

test('login distinguishes unavailable password crypto from a network failure', async () => {
  const originalCrypto = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
  const originalFetch = globalThis.fetch;
  const originalFormData = globalThis.FormData;
  let states;
  let cursor;
  let requests = 0;
  let loggedIn = false;
  const Form = () => null;
  const react = {
    ...require('react'),
    useState(initial) {
      const index = cursor++;
      states[index] ??= initial;
      return [states[index], (value) => (states[index] = value)];
    },
  };
  function load(file) {
    const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    const exported = {};
    new Function('exports', 'require', compiled)(exported, (name) => {
      if (name === 'react') return react;
      if (name === './Form') return { Form };
      if (name.startsWith('.')) return load(path.resolve(path.dirname(file), name + '.ts'));
      return require(name);
    });
    return exported;
  }
  function nodes(node) {
    return !node || typeof node !== 'object'
      ? []
      : [node, ...[node.props?.children].flat(Infinity).flatMap(nodes)];
  }
  try {
    globalThis.FormData = class {
      get(name) {
        return name === 'login_name' ? 'synthetic-login' : 'synthetic-password';
      }
    };
    globalThis.fetch = async () => {
      requests++;
      throw new TypeError('Failed to fetch');
    };
    const { Login } = load(path.resolve(__dirname, '../src/Auth.tsx'));
    async function submit() {
      states = [];
      cursor = 0;
      const tree = Login({ onLogin: () => (loggedIn = true) });
      const form = nodes(tree).find((node) => node.type === Form);
      await form.props.onSubmit({ preventDefault() {}, currentTarget: {} });
    }
    Object.defineProperty(globalThis, 'crypto', { configurable: true, value: {} });
    await submit();
    assert.match(states[2], /当前浏览器无法安全提交密码/);
    assert.match(states[2], /局域网试用设置后重启浏览器/);
    assert.equal(requests, 0, 'unavailable crypto must not send a password request');
    assert.equal(states[1], false);
    assert.equal(loggedIn, false);

    Object.defineProperty(globalThis, 'crypto', { configurable: true, value: webcrypto });
    await submit();
    assert.equal(states[2], '连接失败，请检查网络后重试。');
    assert.equal(requests, 1);
    assert.equal(states[1], false);
    assert.equal(loggedIn, false);
  } finally {
    Object.defineProperty(globalThis, 'crypto', originalCrypto);
    globalThis.fetch = originalFetch;
    globalThis.FormData = originalFormData;
  }
});
