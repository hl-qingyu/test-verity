const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2] || 'C:/Users/geekonup/Documents/Codex/2026-08-17/new-chat/outputs/verity-prototype.html', 'utf8');
const script = html.match(/<script>\s*('use strict';[\s\S]*?)<\/script>/)[1];
new vm.Script(script);
const columns = script.slice(script.indexOf('const CASE_COLUMNS='), script.indexOf('\n', script.indexOf('const CASE_COLUMNS=')));
const logic = script.slice(script.indexOf('let caseInline=null'), script.indexOf('function viewCases(){'));
vm.runInNewContext(`
${columns}
const clone=x=>JSON.parse(JSON.stringify(x)),CASE_RESULTS=['未测','通过','失败'];
const p={id:'p',cases:Array.from({length:12},(_,i)=>({id:'c'+i,platformNumber:i+1,title:'场景'+i,result:'通过',tester:'旧人员',priority:'P1'})),rules:[]};
const P=()=>p,caseResults=()=>p.cases.slice(0,11),caseSelection=new Set();
let scope='filtered',casePage=1,casePageSize=10;
const document={getElementById:()=>({value:scope}),querySelectorAll:()=>[]};
const closeModal=()=>{},render=()=>{},save=()=>{},toast=()=>{},error=m=>{throw new Error(m)};
${logic}
caseInlineStart(null);assert.equal(caseInline.rows.length,11);
caseInline.rows[0].title='新标题';caseInline.rows[10].tester='';caseInline.mode='rows';
assert.equal(caseInlineChanges().length,2);assert.equal(p.cases[0].title,'场景0');
caseInlineApply();assert.equal(p.cases[0].title,'新标题');assert.equal(p.cases[0].result,'未测');assert.equal(p.cases[10].tester,'');assert.equal(p.cases[11].tester,'旧人员');
assert.equal(p.cases[0].editHistory[0].value.title,'场景0');
caseSelection.add('c0');caseSelection.add('c11');scope='selected';caseInlineStart(null);assert.equal(caseInline.rows.length,2);assert.equal(caseInline.rows[1].id,'c11');caseInline.uniform={tester:'所选'};caseInline.mode='uniform';caseInlineApply();assert.equal(p.cases[0].tester,'所选');assert.equal(p.cases[11].tester,'所选');assert.equal(p.cases[1].tester,'旧人员');
scope='project';caseInlineStart(null);assert.equal(caseInline.rows.length,12);
caseInline.uniform={tester:''};caseInline.mode='uniform';caseInlineApply();assert.equal(p.cases[11].tester,'');
caseInlineAction('ci-delete-confirm','c0');assert.equal(p.cases.length,11);assert.equal(p.deletedCases[0].platformNumber,1);assert.ok(p.deletedCases[0].editHistory.length);
`, { assert });
console.log('PASS: prototype filtered/project scope, cross-page edits, version reset, explicit clearing and preserved deletion history');
