const { test } = require('node:test'),
  assert = require('node:assert/strict'),
  fs = require('node:fs'),
  path = require('node:path'),
  ts = require('typescript'),
  React = require('react'),
  { renderToStaticMarkup } = require('react-dom/server');
const exportsFor = {};
new Function(
  'exports',
  'require',
  ts.transpileModule(
    fs.readFileSync(path.resolve(__dirname, '../src/GenerationEvidence.tsx'), 'utf8'),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    },
  ).outputText,
)(exportsFor, require);
const render = (
  materials,
  evidence,
  design = { description: '验证取消订单', expected: '订单已取消，释放本订单占用库存' },
) =>
  renderToStaticMarkup(
    React.createElement(exportsFor.GenerationEvidence, {
      record: { materials },
      suggestion: { evidence, design },
    }),
  );
test('evidence summary comes from requirements/prototype quotes, never the case description or complete source', () => {
  const quote = '待处理订单取消后释放占用库存。',
    m = {
      sourceId: 'M1',
      side: 'CURRENT',
      name: '订单固定需求',
      versionName: 'v3 · 订单.html',
      segments: [
        { id: 'P1', location: '订单 · 批注：取消规则', text: quote + '其他用例原文'.repeat(2000) },
      ],
    },
    html = render(
      [m],
      [{ source: 'M1', side: 'CURRENT', segment: 'P1', quote, verifiedQuote: true }],
      { description: '这是用例描述，不是需求证据', expected: '这是用例预期' },
    );
  assert.match(html, /需求 \/ 原型证据摘要/);
  assert.match(html, /待处理订单取消后释放占用库存/);
  assert.match(html, /订单 · 批注：取消规则/);
  assert.match(html, /v3 · 订单.html/);
  assert.ok(!html.includes('其他用例原文'));
  assert.ok(!html.includes('这是用例描述'));
  assert.ok(!html.includes('这是用例预期'));
  assert.ok(!html.includes('<pre'));
});
test('old data with only a source reference explicitly lacks a per-case requirement excerpt', () => {
  const m = {
      sourceId: 'M1',
      side: 'CURRENT',
      name: '固定需求',
      version: '7',
      segments: [{ id: 'S1', location: '第1页', text: '完整原文不自动总结' }],
    },
    html = render(
      [m],
      [
        {
          source: 'M1',
          side: 'CURRENT',
          segment: '资料级来源',
          quote: '仅资料级来源说明',
          verifiedQuote: false,
        },
      ],
    );
  assert.match(html, /未保存支持本条用例的需求 \/ 原型摘录/);
  assert.ok(!html.includes('验证取消订单'));
  assert.ok(!html.includes('完整原文不自动总结'));
  assert.ok(!html.includes('仅资料级来源说明'));
});
test('unmatched AI excerpts stay visible as unverified suggestions with escaped brief text and warning', () => {
  const quote = '<script>alert(1)</script>待数为0。' + 'AI摘录长文本'.repeat(100),
    quoteWarning = '摘录未匹配固定原文，请人工核对。<img src=x onerror=alert(1)>',
    m = {
      sourceId: 'M1',
      side: 'CURRENT',
      name: '固定需求',
      version: '7',
      segments: [{ id: 'S1', location: '第1段', text: '待发数为0。' }],
    },
    html = render(
      [m],
      [{ source: 'M1', side: 'CURRENT', segment: '', quote, verifiedQuote: false, quoteWarning }],
    );
  assert.match(html, /AI摘录（待核对）/);
  assert.match(html, /摘录未匹配固定原文，请人工核对/);
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('&lt;img'));
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('需求 / 原型证据摘要'));
  assert.ok(!html.includes('未保存支持本条用例'));
  assert.ok(!html.includes('AI摘录长文本'.repeat(100)));
  assert.ok(html.includes('…'));
  assert.ok(!html.includes('<button'));
  assert.ok(!html.includes('<input'));
  assert.ok(
    !render(
      [m],
      [{ source: 'M1', side: 'CURRENT', segment: '', quote, verifiedQuote: false }],
    ).includes('待数为0'),
  );
});
test('legacy matching quote is brief and escaped; unknown/ambiguous sources do not fabricate evidence', () => {
  const quote = '<script>alert(1)</script>' + '原文摘录'.repeat(400),
    m = {
      sourceId: 'M1',
      side: 'CURRENT',
      name: '固定原件',
      version: '7',
      segments: [{ id: 'S1', location: '第1段', text: quote }],
    },
    e = { source: 'M1', side: 'CURRENT', segment: 'S1', quote },
    html = render([m], [e]);
  assert.match(html, /需求 \/ 原型证据摘要/);
  assert.match(html, /第1段/);
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('原文摘录'.repeat(400)));
  assert.match(render([m], [{ ...e, side: 'BEFORE' }]), /没有可唯一匹配/);
  assert.match(render([m, { ...m }], [e]), /没有可唯一匹配/);
  assert.match(render([], []), /没有保存来源引用/);
});
