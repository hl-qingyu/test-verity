// Run: node docs/prototypes/check-skill-management.cjs [total-prototype.html]
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const path = require("node:path");
const crypto = require("node:crypto");
const {
  characterEntities,
} = require("../../frontend/node_modules/character-entities/index.js");
const channels = [];
class MessageChannel extends require("node:worker_threads").MessageChannel {
  constructor() {
    super();
    channels.push(this);
  }
}
process.on("exit", () =>
  channels.forEach((c) => {
    c.port1.close();
    c.port2.close();
  }),
);
const target =
  process.argv[2] || require('node:path').resolve(__dirname, '../../verity-prototype.html');
const html = fs.readFileSync(target, "utf8");
for (const match of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))
  new vm.Script(match[1]);
const start = html.indexOf("// Skill management content snapshot.");
const end = html.indexOf("// End Skill management prototype.", start);
assert.ok(start > 0 && end > start);
const block = html.slice(start, end);
const behavior = block.slice(block.indexOf("// Skill management prototype:"));
assert.ok(!/\b(fetch|XMLHttpRequest|alert|confirm|prompt)\s*\(/.test(behavior));
for (const action of [
  "import-skill",
  "try-skill",
  "publish-skill",
  "rollback-skill",
  "copy-skill",
  "save-import-skill",
])
  assert.ok(!html.includes("case'" + action + "'"));
assert.ok(html.includes("if(!skCloseGuard())return;"));
assert.ok(html.includes('style id="skill-management-layout"'));
assert.ok(html.includes("@media(max-width:650px)"));
assert.match(html, /\.sk-file\s*\{[^}]*justify-content:\s*flex-start/);
assert.match(html, /\.sk-file > span:last-child\s*\{[^}]*text-align:\s*left/);
const context = vm.createContext({
  assert,
  console,
  TextEncoder,
  TextDecoder,
  MessageChannel,
  ReadableStream,
  characterEntities,
  fs,
  path,
  crypto,
});
vm.runInContext(
  `
const S={role:'平台管理员'}, listeners={}, timers=[];let modalContext=null,markup='',footer='',lastError='',renderCount=0,closed=0;
const esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const admin=()=>S.role==='平台管理员',icon=x=>'<svg></svg>',tag=t=>'<span>'+esc(t)+'</span>',btn=(t,a,id='',kind='')=>'<button data-action="'+a+'" data-id="'+esc(id)+'">'+t+'</button>',header=(t,d)=>'<h1>'+t+'</h1>'+d,note=t=>'<aside>'+esc(t)+'</aside>',empty=(t,d)=>t+d;
const save=()=>{},render=()=>renderCount++,toast=t=>lastError=t,error=t=>lastError=t,navigate=()=>{},closeModal=()=>{if(!skCloseGuard())return;closed++;modalContext=null;},openModal=(t,b,f)=>{markup=t+b+f;footer=f;};
const element={focus:()=>{},scrollTo:()=>{},scrollIntoView:()=>{},disabled:false,classList:{add:()=>{},toggle:()=>{}}};
const document={createElement:()=>({innerHTML:'',get textContent(){return this.innerHTML.replace(/&([^;]+);/g,(all,key)=>characterEntities[key]??all);}}),addEventListener:(t,f)=>(listeners[t]??=[]).push(f),getElementById:()=>element,querySelector:()=>element,querySelectorAll:()=>[]};
const window={addEventListener:()=>{}},setTimeout=f=>timers.push(f);
`,
  context,
);
const renderer = html.match(
  /<script data-verity-markdown>([\s\S]*?)<\/script>/,
);
assert.ok(renderer);
vm.runInContext(renderer[1], context);
vm.runInContext(block, context);
vm.runInContext(
  `
assert.deepEqual(SKILL_CONTENT.map(s=>s.key),['requirement-analysis','case-generation','case-analysis','code-review','change-impact']);
for(const record of SKILL_CONTENT){const folder=path.resolve('skill',record.key);const expected=fs.readdirSync(folder,{recursive:true,withFileTypes:true}).filter(f=>f.isFile()).map(f=>path.relative(folder,path.join(f.parentPath,f.name)).split(path.sep).join('/')).filter(f=>!f.includes('__pycache__')&&!f.endsWith('.pyc')).sort();assert.equal(JSON.stringify(record.files.map(f=>f.path).sort()),JSON.stringify(expected));for(const file of record.files){const original=fs.readFileSync(path.resolve('skill',record.key,file.path),'utf8');assert.equal(file.text,original);assert.equal(file.sha256,crypto.createHash('sha256').update(original).digest('hex'));assert.ok(!file.path.includes('__pycache__'));}}
let output=viewSkills();assert.match(output,/文件目录/);assert.match(output,/sk-edit/);assert.doesNotMatch(output,/导入 Markdown|编辑与试跑|复制到当前项目/);
skSelected='case-generation';skPath='SKILL.md';output=viewSkills();assert.match(output,/legacy-contract.md/);assert.match(output,/compact-report.json/);assert.equal(skUsage(skFile()),'参与当前AI调用');
assert.equal(skRecord().version,'2.1.2');skPath='segmented-output-draft.md';assert.equal(skUsage(skFile()),'参考文件');skPath='references/preparation.md';assert.equal(skUsage(skFile()),'参与当前AI调用');assert.match(viewSkills(),/references/);skPath='legacy-contract.md';assert.equal(skUsage(skFile()),'历史约定');assert.doesNotMatch(viewSkills(),/data-action="sk-edit"/);
skSelected='code-review';skPath='scripts/check_examples.py';assert.match(skContent(),/import/);assert.equal(skUsage(skFile()),'参考文件');assert.doesNotMatch(viewSkills(),/data-action="sk-edit"/);
skPath='examples/input.json';skMode='read';assert.equal(skContent(),'<pre class="sk-code">'+esc(JSON.stringify(JSON.parse(skText()),null,2))+'</pre>');skMode='raw';assert.equal(skContent(),'<pre class="sk-code">'+esc(skText())+'</pre>');
assert.equal(skResolveLink('SKILL.md','contract.md'),'contract.md');assert.equal(skResolveLink('examples/input.json','../SKILL.md'),'SKILL.md');
for(const href of ['../../SKILL.md','%2e%2e/contract.md','https://example.com','javascript:alert(1)','/contract.md','missing.md','%zz'])assert.equal(skResolveLink('SKILL.md',href),null);
const safe=skMarkdown('# 标题\\n\\n<script>alert(1)</script>\\n\\n[约定](contract.md)');assert.doesNotMatch(safe,/<script>/);assert.match(safe,/data-action="sk-link"/);assert.doesNotMatch(safe,/href=/);
skPath='SKILL.md';skMode='read';for(const role of ['项目成员','项目负责人']){S.role=role;assert.doesNotMatch(viewSkills(),/data-action="sk-edit"/);skEditOpen();assert.equal(skDraft,null);}
S.role='平台管理员';skEditOpen();assert.equal(skDraft.revision,0);assert.equal(skDraft.prefix,skParts(skText()).prefix);assert.equal(skDirty(),false);skDraft.body+='\\n\\n新增原型验证要求';assert.equal(skDirty(),true);assert.equal(skCloseGuard(),false);assert.equal(modalContext.state,'discard');assert.match(markup,/继续编辑/);skAction('sk-edit-back','');assert.equal(modalContext.state,'editor');
const draft=skDraft, originalSnapshot=SKILL_CONTENT.find(s=>s.key===draft.key).files.find(f=>f.path==='SKILL.md').text;
skAction('sk-save-confirm','');assert.equal(modalContext.state,'save');assert.match(markup,/所有项目/);skAction('sk-save','');assert.equal(draft.busy,true);assert.equal(skCloseGuard(),false);skAction('sk-save','');assert.equal(timers.length,1);timers.shift()();assert.equal(skDraft,null);assert.equal(skRevision().revision,1);assert.equal(skText(),draft.prefix+draft.body);assert.equal(skRevision().history[0].text,originalSnapshot);assert.equal(SKILL_CONTENT.find(s=>s.key===draft.key).files.find(f=>f.path==='SKILL.md').text,originalSnapshot);
skEditOpen();skDraft.body+='changed';const conflict={...skDraft};S.skillManagement[skSelected].revision++;assert.match(skApplyRevision(conflict),/内容已被修改/);assert.equal(skDraft.body,conflict.body);
S.role='项目负责人';assert.match(skApplyRevision(conflict),/权限已变化/);S.role='平台管理员';conflict.revision=skRevision().revision;assert.match(skApplyRevision({...conflict,body:'   '}),/不能为空/);assert.match(skApplyRevision({...conflict,body:'x'.repeat(200001)}),/200000/);
skAction('sk-discard','');assert.equal(skDraft,null);assert.equal(modalContext,null);
skSelected='case-analysis';skPath='SKILL.md';assert.doesNotMatch(skParts(skText()).prefix,/metadata:/);assert.match(skParts(skText()).body,/用例分析 1.0.1/);assert.equal(skRecord().files.length,2);assert.doesNotMatch(skTree(),/examples/);

skSelected='case-generation';skPath='SKILL.md';S.role='平台管理员';skEditOpen();assert.equal(skDraft.assistant,false);assert.match(markup,/AI辅助修改/);skAIAction('sk-ai-toggle','');assert.equal(skDraft.assistant,true);assert.match(markup,/发送（演示）/);assert.match(markup,/查看发送范围与参考文件/);assert.match(markup,/不联网/);
const aiDraft=skDraft, unmodified=aiDraft.body, unmodifiedContract=skRecord().files.find(f=>f.path==='contract.md').text;
aiDraft.references=['evaluation.md'];aiDraft.question='<script>仅验证转义</script>';skAIAction('sk-ai-send','');assert.equal(aiDraft.aiBusy,true);assert.equal(skChat().length,1);assert.equal(skChat()[0].context.length,13);assert.equal(skChat()[0].context[0].text,aiDraft.prefix+unmodified);assert.equal(skChat()[0].context.find(f=>f.path==='contract.md').text,unmodifiedContract);assert.equal(aiDraft.body,unmodified);assert.equal(skCloseGuard(),false);skAIAction('sk-ai-send','');assert.equal(timers.length,1);skAction('sk-save-confirm','');assert.equal(modalContext.state,'editor');assert.match(skChatView(aiDraft),/&lt;script&gt;/);assert.doesNotMatch(skChatView(aiDraft),/<script>/);
timers.shift()();assert.equal(skChat()[0].status,'completed');assert.equal(aiDraft.aiBusy,false);assert.equal(aiDraft.body,unmodified);assert.equal(skRevision().revision,0);assert.match(markup,/修改前 · 变化部分/);assert.match(markup,/查看完整建议正文/);assert.match(markup,/应用到草稿/);
skAIAction('sk-ai-apply','');assert.equal(aiDraft.body,aiDraft.candidate.after);assert.equal(aiDraft.candidate.applied,true);assert.equal(skRevision().revision,0);assert.equal(skRecord().files.find(f=>f.path==='contract.md').text,unmodifiedContract);const once=aiDraft.body;skAIAction('sk-ai-apply','');assert.equal(aiDraft.body,once);
aiDraft.question='继续调整';skAISend(aiDraft);timers.shift()();assert.equal(skChat().length,2);assert.equal(skChat()[1].context[0].text,aiDraft.prefix+once);aiDraft.body+='手工编辑';const edited=aiDraft.body;skAIAction('sk-ai-apply','');assert.equal(aiDraft.body,edited);assert.match(lastError,/不能覆盖/);skAIAction('sk-ai-dismiss','');assert.equal(aiDraft.candidate.dismissed,true);
aiDraft.question='取消这轮';skAISend(aiDraft);assert.equal(aiDraft.aiBusy,true);skAIAction('sk-ai-cancel','');assert.equal(aiDraft.aiBusy,false);assert.equal(aiDraft.question,'取消这轮');assert.equal(skChat().at(-1).status,'cancelled');const candidateBefore=aiDraft.candidate;timers.shift()();assert.equal(aiDraft.candidate,candidateBefore);
aiDraft.question='权限变化检查';skAISend(aiDraft);S.role='项目成员';timers.shift()();assert.equal(skChat().at(-1).status,'failed');assert.match(skChat().at(-1).error,/权限/);assert.equal(aiDraft.body,edited);S.role='平台管理员';
const savedTurns=skChat().length;skAction('sk-discard','');skSelected='case-analysis';skEditOpen();assert.equal(skChat().length,0);skAction('sk-discard','');skSelected='case-generation';skEditOpen();assert.equal(skChat().length,savedTurns);assert.equal(skDraft.body,unmodified);skAIAction('sk-ai-review','0');assert.equal(skDraft.candidate.before,unmodified);assert.equal(skDraft.body,unmodified);skAIAction('sk-ai-apply','');assert.notEqual(skDraft.body,unmodified);assert.equal(skRevision().revision,0);
skAction('sk-save-confirm','');skAction('sk-save','');timers.shift()();assert.equal(skRevision('case-generation').revision,1);assert.equal(skDraft,null);assert.equal(skRecord().files.find(f=>f.path==='contract.md').text,unmodifiedContract);
assert.deepEqual(skChanged('abc','abc\\ndef'),{removed:'',added:'\\ndef'});assert.deepEqual(skChanged('abc','adc'),{removed:'b',added:'d'});
`,
  context,
);
console.log(
  "PASS: exact Skill files, left alignment, admin editing, synthetic chat scopes/isolation, cancellation, comparison, manual apply/save, stale drafts, role loss and unchanged source snapshots.",
);
channels.forEach((c) => {
  c.port1.close();
  c.port2.close();
});
