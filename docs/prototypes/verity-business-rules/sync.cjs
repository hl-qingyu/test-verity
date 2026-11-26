const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../../..');
const file = path.join(root, 'verity-prototype.html');
const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, 'catalog.json'), 'utf8'));
const css = fs.readFileSync(path.join(__dirname, 'styles.css'), 'utf8');
const js = fs.readFileSync(path.join(__dirname, 'runtime.js'), 'utf8')
  .replace('__VERITY_BUSINESS_RULES__', JSON.stringify(catalog).replace(/</g, '\\u003c'));
new vm.Script(js);
const backup = path.join(root, 'outputs/business-rules-detailed-before-20261113');
fs.mkdirSync(backup, { recursive: true });
const source = fs.readFileSync(file, 'utf8');
const snapshot = path.join(backup, 'prototype-0.html');
if (!fs.existsSync(snapshot)) fs.writeFileSync(snapshot, source);
const style = /<style id="business-rules-style">[\s\S]*?<\/style>/;
const script = /<script id="business-rules-script">[\s\S]*?<\/script>/;
if (!style.test(source) || !script.test(source)) throw new Error('Business rules blocks are missing');
const text = source
  .replace(style, () => `<style id="business-rules-style">${css}</style>`)
  .replace(script, () => `<script id="business-rules-script">${js}</script>`);
for (const match of text.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
  if (!/type=["'](?:module|application\/json)/.test(match[1])) new vm.Script(match[2]);
}
fs.writeFileSync(file, text);
console.log(file);
const references = ['# 原型业务规则核对', '', '规则取自当前前后端校验与操作逻辑；页面右栏不展示实现路径。以下索引用于维护时追溯，不能以旧模块文档替代代码复核。', ''];
for (const page of Object.values(catalog)) {
  references.push(`## ${page.name}`, '');
  for (const entry of page.entries) {
    references.push(`### ${entry.title}`, '', ...entry.groups.flatMap(group => [`**${group.title}**`, '', ...group.rules.map(rule => `- ${rule}`), '']), `核对来源：${entry.sources.map(source => '`' + source + '`').join('、')}`, '');
  }
}
fs.writeFileSync(path.join(__dirname, 'RULES.md'), references.join('\n'));
console.log('All inline scripts parsed; main prototype annotations synced.');
