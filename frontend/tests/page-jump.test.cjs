const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function harness(props = {}) {
  let state = [],
    cursor = 0,
    key;
  const changes = [],
    exports = {};
  const code = compileModule(
    fs.readFileSync(path.resolve(__dirname, '../src/PageJump.tsx'), 'utf8'),
    {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    },
  ).outputText;
  evaluateModule(
    code,
    (name) =>
      name === 'react'
        ? {
            useId: () => 'jump-test',
            useState(initial) {
              const i = cursor++;
              if (!(i in state)) state[i] = initial;
              return [
                state[i],
                (v) => {
                  state[i] = v;
                },
              ];
            },
          }
        : require(name),
    exports,
  );
  const options = { page: 1, pages: 9, onChange: (page) => changes.push(page), ...props };
  function render() {
    const wrapper = exports.PageJump(options);
    if (key !== wrapper.key) {
      state = [];
      key = wrapper.key;
    }
    cursor = 0;
    const nodes = [];
    function walk(node) {
      if (Array.isArray(node)) return node.forEach(walk);
      if (!node || typeof node !== 'object') return;
      nodes.push(node);
      walk(node.props.children);
    }
    walk(wrapper.type(wrapper.props));
    return nodes;
  }
  const input = () => render().find((n) => n.type === 'input');
  const fill = (value) => input().props.onChange({ target: { value } });
  const click = () =>
    render()
      .find((n) => n.type === 'button')
      .props.onClick();
  return { options, changes, render, input, fill, click };
}

test('page jumps reject empty, fractional, exponent, negative and out-of-range values with inline feedback', () => {
  const h = harness();
  for (const value of ['', '0', '-1', '1.5', '1e2', '10', 'abc', '9007199254740992']) {
    h.fill(value);
    h.click();
    assert.equal(h.changes.length, 0);
    assert.equal(h.input().props['aria-invalid'], true);
    assert.ok(h.render().some((n) => n.props.role === 'alert'));
  }
  h.fill('9');
  h.click();
  assert.deepEqual(h.changes, [9]);
  assert.equal(h.input().props['aria-invalid'], false);
});

test('Enter jumps without submitting a surrounding business form; current page does not trigger a request', () => {
  const h = harness();
  let prevented = 0,
    stopped = 0;
  h.fill('3');
  h.input().props.onKeyDown({
    key: 'Enter',
    preventDefault: () => prevented++,
    stopPropagation: () => stopped++,
  });
  assert.deepEqual(h.changes, [3]);
  assert.equal(prevented, 1);
  assert.equal(stopped, 1);
  h.options.page = 3;
  assert.equal(h.input().props.value, '3');
  h.click();
  assert.deepEqual(h.changes, [3]);
  h.fill('8');
  h.options.pages = 2;
  h.options.page = 1;
  assert.equal(h.input().props.value, '1');
  h.fill('2');
  h.options.page = 2;
  assert.equal(h.input().props.value, '2');
  h.options.page = 1;
  assert.equal(h.input().props.value, '1');
});

test('loading, empty and single-page lists cannot jump; history without a total accepts a positive page', () => {
  for (const options of [{ disabled: true }, { pages: 1 }, { pages: 0 }]) {
    const h = harness(options);
    assert.equal(h.input().props.disabled, true);
    h.fill('2');
    h.click();
    assert.deepEqual(h.changes, []);
  }
  const h = harness({ pages: undefined });
  h.fill('12');
  h.click();
  assert.deepEqual(h.changes, [12]);
  assert.equal(h.render().find((n) => n.type === 'button').props.type, 'button');
  assert.equal(h.input().props.inputMode, 'numeric');
  assert.equal(h.render().find((n) => n.type === 'label').props.htmlFor, h.input().props.id);
});

test('every previous/next pagination surface also exposes the shared jump control', () => {
  const root = path.resolve(__dirname, '../src');
  for (const name of fs.readdirSync(root).filter((name) => name.endsWith('.tsx'))) {
    const source = fs.readFileSync(path.join(root, name), 'utf8');
    if (!source.includes('上一页')) continue;
    assert.ok(source.includes("import { PageJump } from './PageJump'"), name);
    assert.equal(
      (source.match(/<PageJump\b/g) || []).length,
      (source.match(/下一页/g) || []).length,
      name,
    );
  }
});
