const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||'C:/Users/geekonup/Documents/Codex/2026-08-17/new-chat/outputs/verity-prototype.html','utf8');
const script=html.match(/<script>\s*('use strict';[\s\S]*?)<\/script>/)[1];
new vm.Script(script);
const logic=script.slice(script.indexOf('function materialDeleteAction('),script.indexOf('function viewDocuments(){'));
vm.runInNewContext(`
const p={docs:[{id:'v1',documentId:'d1',name:'旧版',archived:true},{id:'v2',documentId:'d1',name:'新版'},{id:'p1',name:'原型',materialKind:'prototype'}],rules:[{sources:[{id:'v1'}]}]};
const P=()=>p,docRoot=d=>d.documentId||d.id,esc=String,btn=()=>'',save=()=>{},closeModal=()=>{},render=()=>{},toast=()=>{},error=()=>{};
let shown='',selectedDoc='v2',selectedPrototype='';const docSelection=new Set(['v2']);
const openModal=(title,body)=>shown=body;
${logic}
materialDeleteAction('material-delete','v2');assert.ok(shown.includes('1 条验收点'));assert.ok(!p.docs[1].deletedAt);
materialDeleteAction('material-delete-confirm','v2');assert.ok(p.docs[0].deletedAt);assert.ok(p.docs[1].deletedAt);assert.ok(!p.docs[2].deletedAt);assert.equal(p.docs.length,3);assert.equal(p.rules[0].sources[0].id,'v1');assert.equal(selectedDoc,'');
materialDeleteAction('material-delete-confirm','p1');assert.ok(p.docs[2].deletedAt);
`,{assert});
console.log('PASS: single material confirmation, all versions retained, evidence unchanged, other materials untouched');
