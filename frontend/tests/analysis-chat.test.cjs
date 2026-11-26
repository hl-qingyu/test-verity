const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { load } = require('./helpers/load.cjs');

test('both analysis conversations render the same form and preserve module-specific wording', () => {
  const props = { findingKey: 'F1', onClearFinding() {}, onSessionEnd() {} };
  const variants = [
    ['CodeAnalysisChat', '代码', { project_id: 1, report: {} }],
    ['ChangeAnalysisChat', '变更', { projectId: 1, structured: {} }],
  ];
  for (const [name, module, fields] of variants) {
    const Component = load(path.resolve(__dirname, '../src', name + '.tsx'))[name];
    const render = (status) =>
      renderToStaticMarkup(
        React.createElement(Component, {
          ...props,
          record: { ...fields, id: 7, title: '合成报告', status },
        }),
      );
    const normal = render('COMPLETED');
    assert.match(normal, /class="panel code-chat-main"/);
    assert.match(normal, /合成报告 · 对话/);
    assert.match(normal, new RegExp(`继续询问${module}问题`));
    assert.match(normal, /<textarea[^>]*maxlength="10000"/i);
    assert.doesNotMatch(normal, /<textarea[^>]*disabled/);
    const blocked = render('FAILED');
    assert.match(blocked, /<textarea[^>]*disabled/);
    assert.match(blocked, new RegExp(`需先完成或导入${module}分析报告`));
  }
});
