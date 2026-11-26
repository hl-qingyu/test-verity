// Offline checks: specific modal routing, annotation isolation and main prototype synchronization.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, 'catalog.json'), 'utf8'));
const runtime = fs.readFileSync(path.join(__dirname, 'runtime.js'), 'utf8');
const start = runtime.indexOf('function score(');
const end = runtime.indexOf('function render()', start);
const score = vm.runInNewContext(`(${runtime.slice(start, end).trim()})`);
const scenarios = [
  ['code', '新建代码分析', 'taskForm|task', 'code-new'],
  ['requirements', '新建需求分析', 'riskNewForm|risk-new', 'risk-new'],
  ['generate', '新建用例生成', 'cgNewForm|cg-new', 'generation-new'],
  ['coverage', '关联复核 · 新建分析', 'crNewForm|cr-new', 'coverage-new'],
  ['changes', '新建变更分析', 'changeNewForm|change-new', 'change-new'],
  ['documents', '文件版本 · 一份很长的需求名称', '', 'versions'],
  ['prototypes', '原型版本 · 订单目录', '', 'versions'],
  ['cases', '历史只读', '', 'case-history'],
  ['cases', '迁移用例并删除分类', 'case-category-delete', 'case-category'],
  ['generate', '确认批量入库', 'cg-review', 'generation-apply'],
  ['generate', '固定输入准备完成', 'cg-preview', 'generation-start'],
  ['generate', '建议详情 · 新增 / C001', 'cg-detail', 'generation-review'],
  ['generate', '应用失败清单 · 人工确认', 'cg-failures', 'generation-export'],
  ['generate', '导入生成结果', 'cg-import', 'analysis-import'],
  ['coverage', '导入分析结果', 'cr-import', 'analysis-import'],
  ['code', '候选与待处理问题', 'taskForm|task', 'candidate'],
  ['requirements', '候选与待处理问题', 'riskNewForm|risk-new', 'candidate'],
  ['platform', '切换调用方式', '', 'ai-config'],
  ['platform', '删除 GitHub 连接', 'gh-delete', 'github-config'],
  ['project', '删除项目仓库关联', 'remove-repo', 'project-repo'],
  ['project', '调整成员权限', 'member', 'project-members'],
  ['requirements', '确认删除分析记录', 'analysis-delete', 'analysis-delete'],
];
for (const [page, title, context, expected] of scenarios) {
  const ranked = catalog[page].entries.map(entry => [entry.id, score(entry, context, title)]);
  const best = Math.max(...ranked.map(([, value]) => value));
  assert.ok(best > 0, title);
  assert.deepEqual(ranked.filter(([, value]) => value === best).map(([id]) => id), [expected], title);
}
const root = path.resolve(__dirname, '../../..');
const text = fs.readFileSync(path.join(root, 'verity-prototype.html'), 'utf8');
assert.equal((text.match(/id="business-rules-script"/g) || []).length, 1);
assert.equal((text.match(/id="business-rules-style"/g) || []).length, 1);
assert.ok(!text.includes('实现入口'));
const script = text.match(/<script id="business-rules-script">([\s\S]*?)<\/script>/)[1];
const normalize = value => value.replace(/\r\n/g, '\n');
const compiled = runtime.replace('__VERITY_BUSINESS_RULES__', JSON.stringify(catalog).replace(/</g, '\\u003c'));
new vm.Script(script);
assert.ok(normalize(script) === normalize(compiled), 'main prototype annotations match their sources');
assert.ok(!/\bfetch\s*\(|localStorage|data-action=|openModal\s*\(/.test(runtime), 'annotations cannot invoke business writes');
for (const [key, page] of Object.entries(catalog)) {
  assert.equal(new Set(page.entries.map(entry => entry.id)).size, page.entries.length, key);
  for (const entry of page.entries) {
    assert.ok(entry.groups.length && entry.sources.length, entry.id);
    for (const source of entry.sources) assert.ok(fs.existsSync(path.join(root, source)), source);
  }
}
console.log(`${scenarios.length} modal routing scenarios passed; 13 page catalogs and the main prototype verified.`);
