const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

test('Markdown renders labels and formatting without navigation, remote images or executable HTML', async () => {
  const dependencies = {
    'react/jsx-runtime': require('react/jsx-runtime'),
    'react-markdown': await import('react-markdown'),
    'remark-gfm': await import('remark-gfm'),
  };
  const source = fs.readFileSync(path.join(__dirname, '../src/MarkdownPreview.tsx'), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const component = {};
  new Function('exports', 'require', compiled)(component, (name) => dependencies[name]);
  const render = (text) =>
    renderToStaticMarkup(React.createElement(component.MarkdownPreview, { text }));
  const text =
    '# 项目说明\n\n## 开发入口\n\n1. **先读文档**\n2. 再看代码\n\n[CustomPage使用说明.md](doc/%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E/common%E6%A8%A1%E5%9D%97%E7%9A%84%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E/CustomPage%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E.md)\n\n| 字段 | 说明 |\n| --- | --- |\n| id | 编号 |\n\n```txt\n%E4%BD%BF 应在代码块里原样保留\n```';
  const html = render(text);
  assert.match(html, /<h1>项目说明<\/h1>/);
  assert.match(html, /<h2>开发入口<\/h2>/);
  assert.match(html, /<ol>/);
  assert.match(html, /<strong>先读文档<\/strong>/);
  assert.match(html, /<table>/);
  assert.match(html, /<span[^>]+>CustomPage使用说明.md<\/span>/);
  assert.doesNotMatch(html, /common%E6/);
  assert.match(html, /%E4%BD%BF 应在代码块里原样保留/);
  const unsafe = render(
    '[本地](file:///C:/private.txt) [恶意](javascript:alert(1)) https://example.com\n\n![远程截图](https://example.com/tracker.png)\n\n<script>alert(1)</script>\n\n<iframe src="https://example.com"></iframe>',
  );
  assert.doesNotMatch(unsafe, /<(?:a|img|script|iframe|link)\b/);
  assert.match(unsafe, /图片：远程截图，暂不加载/);
  const captured = [];
  const interactive = renderToStaticMarkup(
    React.createElement(component.MarkdownPreview, {
      text: '[本地](file:///C:/资料.md) [名称变更](doc/%E4%BD%BF.md)',
      renderLink: (href, children) => {
        captured.push(href);
        return React.createElement('button', {}, children);
      },
    }),
  );
  assert.equal(decodeURIComponent(captured[0]), 'file:///C:/资料.md');
  assert.equal(captured[1], 'doc/%E4%BD%BF.md');
  assert.doesNotMatch(interactive, /\bhref=|\bsrc=/);
});
