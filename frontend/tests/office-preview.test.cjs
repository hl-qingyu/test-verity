const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

function load(file) {
  const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const exported = {};
  new Function('exports', 'require', compiled)(exported, (name) =>
    name.startsWith('.')
      ? load(
          path.resolve(
            path.dirname(file),
            name + (fs.existsSync(path.resolve(path.dirname(file), name + '.ts')) ? '.ts' : '.tsx'),
          ),
        )
      : require(name),
  );
  return exported;
}

test('Office previews render named sheets, merged cells and escaped document content', () => {
  const { OfficePreview, excelColumn } = load(path.resolve(__dirname, '../src/OfficePreview.tsx'));
  const { parsePreview } = load(path.resolve(__dirname, '../src/documentApi.ts'));
  const workbook = {
    kind: 'workbook',
    text: '',
    truncated: false,
    sheets: [
      {
        name: '需求清单',
        rows: [
          ['合并标题', ''],
          ['<script>alert(1)</script>', '25%'],
        ],
        merges: [[0, 0, 1, 2]],
        total_rows: 2,
        total_columns: 2,
        truncated: false,
      },
      {
        name: '第二工作表',
        rows: [],
        merges: [],
        total_rows: 0,
        total_columns: 0,
        truncated: false,
      },
    ],
  };
  const html = renderToStaticMarkup(
    React.createElement(OfficePreview, { preview: parsePreview(workbook) }),
  );
  assert.match(html, /需求清单/);
  assert.match(html, /第二工作表/);
  assert.match(html, /colSpan="2"|colspan="2"/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
  assert.equal(excelColumn(25), 'Z');
  assert.equal(excelColumn(26), 'AA');
  assert.equal(excelColumn(49), 'AX');
  assert.throws(
    () =>
      parsePreview({ ...workbook, sheets: [{ ...workbook.sheets[0], merges: [[0, 0, 1, 999]] }] }),
    /document_response_invalid/,
  );
  const word = {
    kind: 'word',
    text: '',
    blocks: [
      { kind: 'heading', level: 1, text: '需求标题' },
      { kind: 'paragraph', level: 0, text: '正文内容' },
      { kind: 'table', rows: [[{ text: '表格内容', colspan: 1, rowspan: 1 }]] },
    ],
    truncated: false,
  };
  const rendered = renderToStaticMarkup(
    React.createElement(OfficePreview, { preview: parsePreview(word) }),
  );
  assert.match(rendered, /<h2/);
  assert.match(rendered, /<table/);
  assert.match(rendered, /正文内容/);
});
