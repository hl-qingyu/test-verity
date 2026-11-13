const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||'outputs/prototype-pending/verity-prototype.html','utf8');
for(const match of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(match[1]);
const code=fs.readFileSync('docs/prototypes/analysis-record-deletion.js','utf8');
assert.ok(html.replaceAll('\r\n', '\n').includes(code.replaceAll('\r\n', '\n').trim()));
assert.ok((html.match(/class="analysis-record-row"/g)||[]).length >= 4);
assert.ok(html.includes('style id="analysis-record-sidebar-delete"'));
for (const module of ['code', 'changes', 'generate', 'coverage']) {
  const call = "${typeof adDeleteControl==='function'?adDeleteControl('" + module + "',";
  assert.ok(html.includes('</button>' + call));
}
const ctx=vm.createContext({assert,console});
vm.runInContext(`
let p,modal='',saved=0,closed=0;const P=()=>p,S={role:'成员'},admin=()=>S.role==='管理员',esc=String;
const btn=(text,action,id)=>text+':'+action+':'+id,icon=name=>'<svg data-icon="'+name+'"/>';
const openModal=(title,body,footer)=>{modal=body+footer;},closeModal=()=>closed++,save=()=>saved++,render=()=>{};
const document={getElementById:()=>null};let modalContext=null,ovScope=null,riskView={},riskSourceFilter='',riskCurrentPage=1,codeSelectedRecord='',changeSelected='',changePage=1,changeChatOpen=false,cgSelected='',cgPage=1,cgSelection=new Set(),cgChatOpen=false,crSelected='',crPage=1;
${code}
for(const [module,key] of Object.entries({requirements:'riskReports',code:'tasks',changes:'changeAnalyses',generate:'generationRecords',coverage:'caseReviews'})){
 const r={id:'synthetic',module:'code',title:'合成结果',owner:'成员',status:'COMPLETED',report:{fixed:'unchanged'},handling:{applied:1}};
 p={[key]:[r],cases:[{id:'already-applied'}]};
 assert.match(adDeleteControl(module,r),/删除记录/);
 if(module!=='requirements'){assert.match(adDeleteControl(module,r),/data-icon="trash"/);assert.match(adDeleteControl(module,r),/aria-label="删除分析记录：合成结果"/);}
 adDeleteAction('ad-delete',module+':synthetic');assert.match(modal,/原始输入/);assert.equal(p[key].length,1);
 adDeleteAction('ad-delete-confirm',module+':synthetic');assert.equal(p[key].length,0);
 assert.deepEqual(p.deletedAnalysisRecords[0].record.report,{fixed:'unchanged'});assert.equal(p.cases.length,1);
 assert.equal(p.deletedAnalysisRecords[0].record.handling.applied,1);
}
p={tasks:[{id:'active',module:'code',title:'执行中',owner:'成员',status:'COMPLETED',chat:[{status:'RUNNING'}]}]};
adDeleteAction('ad-delete','code:active');assert.match(modal,/先取消/);adDeleteAction('ad-delete-confirm','code:active');assert.equal(p.tasks.length,1);
S.role='其他成员';assert.equal(adDeleteControl('code',p.tasks[0]),'');
assert.equal(saved,5);assert.equal(closed,5);
`,ctx);
console.log('PASS five deletion entries, confirmation, permission/activity guards, retained reports/cases and archived synthetic records');
