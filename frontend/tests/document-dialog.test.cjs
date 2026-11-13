const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

// Exercise the actual dialog cancel handler without adding a browser/renderer dependency.
const source = fs.readFileSync(path.join(__dirname, '../src/Documents.tsx'), 'utf8');
const compiled = ts.transpileModule(source + '\nexport { DocumentDialog };', {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;
const component = {};
new Function('exports', 'require', compiled)(component, (name) => {
  if (name === 'react')
    return { useRef: () => ({ current: { showModal() {} } }), useEffect: (effect) => effect() };
  if (name === 'react/jsx-runtime') return require(name);
  return {};
});

test('cancelling the file picker does not close the upload dialog; explicit dialog cancellation still works', () => {
  const dialogElement = {},
    fileInput = {};
  let closed = 0,
    prevented = 0;
  const render = (busy) =>
    component.DocumentDialog({
      title: '上传需求资料',
      busy,
      onClose: () => closed++,
      children: null,
    });
  const event = (target) => ({
    target,
    currentTarget: dialogElement,
    preventDefault: () => prevented++,
  });
  render(false).props.onCancel(event(fileInput));
  assert.equal(closed, 0);
  render(true).props.onCancel(event(dialogElement));
  assert.equal(closed, 0);
  render(false).props.onCancel(event(dialogElement));
  assert.equal(closed, 1);
  assert.equal(prevented, 3);
});
