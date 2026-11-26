const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

test('image zoom respects pixel scale and stays within 10–400 percent', () => {
  const source = fs.readFileSync(path.join(__dirname, '../src/ImagePreview.tsx'), 'utf8');
  const compiled = compileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const component = {};
  evaluateModule(compiled, () => ({}), component);
  assert.equal(component.imageZoom(100, 1.25), 125);
  assert.equal(component.imageZoom(125, 0.8), 100);
  assert.equal(component.imageZoom(400, 1.25), 400);
  assert.equal(component.imageZoom(10, 0.8), 10);
  assert.equal(component.imageZoom(2, 1.25), 10);
});
