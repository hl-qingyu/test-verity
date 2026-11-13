// Run: node docs/prototypes/check-documents.cjs [total-prototype.html]
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2] || 'C:/Users/geekonup/Documents/Codex/2026-08-17/new-chat/outputs/verity-prototype.html', 'utf8');
const script = html.match(/<script>\s*('use strict';[\s\S]*?)<\/script>/)[1];
new vm.Script(script);
const helpers = script.slice(script.indexOf('const docSelection='), script.indexOf('function docPreview('));
const startTask = script.slice(script.indexOf('function startTask()'), script.indexOf('async function handle('));
const requirementHelpers = script.slice(script.indexOf("let requirementTab="), script.indexOf('function viewRequirements()'));
const upload = script.slice(script.indexOf("case'save-upload':"), script.indexOf("case'save-upload':") + script.slice(script.indexOf("case'save-upload':")).indexOf('break;}') + 7);
const context = vm.createContext({assert, window:{}, crypto: require('node:crypto').webcrypto});
vm.runInContext(`
const project={id:'p1',docs:[{id:'a',name:'old.md',version:'v1.0',type:'MD',text:'original',group:'流程截图',order:0},{id:'b',name:'other.md',version:'v1.0',order:1,group:'流程截图'}],rules:[{status:'已确认'}],tasks:[{snapshot:{docs:['old.md @ v1.0']}},{snapshot:{docs:['other.md @ v1.0']}}]};
const P=()=>project, save=()=>{},render=()=>{},closeModal=()=>{},navigate=()=>{},toast=()=>{};
let lastError='',selectedDoc='',modalContext={kind:'documents',versionId:'a'};
const error=msg=>lastError=msg;
const urls=new Map(),URL={createObjectURL:()=> 'blob:fixture'};
let files=[{name:'new.md',size:4,text:async()=> 'new content'}];
const document={getElementById:id=>id==='uploadInput'?{files}:null};
${helpers}
async function uploadFiles(){const pendingUploadFiles=files;const el={disabled:false};switch('save-upload'){${upload}}}
`, context);
(async()=>{
  await vm.runInContext(`(async()=>{
    documentAction('docs-down','a');
    assert.equal(currentDocs()[0].id,'b');
    await uploadFiles();
    assert.equal(project.docs.length,3);
    const newest=project.docs[2];
    assert.equal(newest.documentId,'a');
    assert.equal(newest.group,'流程截图');
    assert.equal(newest.order,1);
    assert.equal(newest.version,'v1.1');
    assert.equal(project.docs[0].text,'original');
    assert.equal(project.docs[0].archived,true);
    assert.equal(project.rules[0].status,'已确认');
    assert.equal(project.tasks[0].stale,true);
    assert.equal(project.tasks[1].stale,undefined);
    assert.equal(project.tasks[0].snapshot.docs[0],'old.md @ v1.0');
    assert.equal(currentDocs().length,2);
    files=[...files,...files];
    await uploadFiles();
    assert.match(lastError,/只能选择一个/);
    assert.equal(project.docs.length,3);
    files=[{name:'unsafe.html',size:5}];
    await uploadFiles();
    assert.match(lastError,/文件格式/);
    files=[{name:'empty.md',size:0}];
    await uploadFiles();
    assert.match(lastError,/空文件/);
  })()`,context);
  vm.runInContext(`
    const S={ai:{}},DEFAULT_RULES=[],taskTimers=new Map();
    const personalAI=()=>({model:"fixture"});
    const clone=x=>JSON.parse(JSON.stringify(x));
    const binding=()=>({skill:{name:'fixture',version:1},template:{name:'fixture',version:1}});
    let submitted={module:'requirements',title:'fixture',focus:'截图按顺序阅读'};
    const formData=()=>submitted;
    const taskDetail=()=>{},setInterval=()=>0;
    const form={querySelectorAll:q=>q==='[name=sourceDoc]:checked'?[{value:project.docs[2].id}]:[]};
    document.getElementById=()=>form;
    project.cases=[];project.issues=[];project.repos=[];
    ${requirementHelpers}
    ${startTask}
    startTask();
    const snapshot=project.tasks[0].snapshot;
    assert.equal(snapshot.documentSources.length,1);
    assert.equal(snapshot.documentSources[0].id,project.docs[2].id);
    assert.equal(snapshot.documentSources[0].version,'v1.1');
    assert.equal(snapshot.documentSources[0].role,'需求文档');
    submitted={group:' 新截图组 '};
    documentAction('docs-save-new-group');
    assert.ok(docGroups().includes('新截图组'));
    assert.equal(project.docs.some(d=>d.group==='新截图组'),false);
    assert.equal(moveDocumentGroup(project.docs[2].id,'新截图组'),true);
    assert.equal(project.docs[0].group,'新截图组');
    assert.equal(project.docs[2].group,'新截图组');
    assert.equal(snapshot.documentSources[0].group,'流程截图');
    assert.equal(moveDocumentGroup(project.docs[2].id,'不存在的分组'),false);
    assert.equal(moveDocumentGroup('其他项目文件','新截图组'),false);
    assert.equal(moveDocumentGroup(project.docs[2].id,''),true);
    assert.equal(project.docs[2].group,'');
    documentAction('docs-save-new-group');
    assert.match(lastError,/已存在/);
    submitted={group:'   '};
    documentAction('docs-save-new-group');
    assert.match(lastError,/分组名称/);
    assert.equal(snapshot.documentSources[0].scope,'全文 / 整张截图');
    assert.equal(snapshot.focus,'截图按顺序阅读');
    assert.equal(project.tasks[0].inputMode,'uploaded');
    assert.equal(snapshot.rules.length,0);
    project.docs[2].version='v2.0';
    assert.equal(snapshot.documentSources[0].version,'v1.1');
  `,context);
  console.log('PASS: syntax, group ordering, immutable versions and task scopes, scoped stale markers, upload limits');
})().catch(err=>{console.error(err);process.exitCode=1;});
