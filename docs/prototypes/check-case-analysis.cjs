// Run: node docs/prototypes/check-case-analysis.cjs [total-prototype.html]
const fs = require("node:fs"),
  vm = require("node:vm"),
  assert = require("node:assert/strict");
const path =
  process.argv[2] || require('node:path').resolve(__dirname, '../../verity-prototype.html');
const html = fs.readFileSync(path, "utf8");
for (const match of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))
  new vm.Script(match[1]);
const start = html.indexOf("// Case analysis prototype:"),
  end = html.indexOf("// End case analysis prototype.", start);
assert.ok(start > 0 && end > start);
const block = html.slice(start, end);
assert.ok(!/\b(fetch|XMLHttpRequest|alert|confirm|prompt)\s*\(/.test(block));
assert.ok(html.includes("function viewCoverage(){return crView();}"));
assert.ok(html.includes("if(module==='coverage'){crNewOpen();return;}"));
assert.ok(html.includes('style id="case-analysis-layout"'));
assert.ok(html.includes("@media(max-width:650px)"));
const ctx = vm.createContext({ assert, console });
vm.runInContext(
  String.raw`
const clone=x=>JSON.parse(JSON.stringify(x)),esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const CG_FIELDS=['module','structure','type','priority','description','title','pre','steps','expected','remark','data_requirements','cleanup'];
const CASE_COLUMNS=[['serial','序号'],['id','用例编号'],['module','功能模块'],['structure','功能结构'],['type','用例类型'],['priority','优先级'],['description','用例描述'],['title','验证用例子项'],['pre','前置条件'],['steps','操作步骤'],['expected','预期结果'],['result','测试结果'],['tester','测试人员'],['remark','备注']];
const cgDesign=c=>Object.fromEntries(CG_FIELDS.map(k=>[k,String(c?.[k]??'')]));
const projects=[{id:'p1',sample:true,cases:[],caseNextNumber:1,caseCategories:[{id:'cat1',name:'用户端'}]},{id:'p2',sample:false,cases:[],caseNextNumber:1,caseCategories:[]}];let current=0;
const P=()=>projects[current],S={role:'测试人员'},ensureCaseNumbers=p=>p.caseNextNumber??=1,ensureCaseCategories=p=>p.caseCategories??=[],caseDisplay=c=>c.originalId||String(c.platformNumber),caseCategoryName=id=>P().caseCategories.find(c=>c.id===id)?.name||'未分类';
let sequence=0,modalContext=null,markup='',footer='',lastError='',values={};const crypto={randomUUID:()=>String(++sequence)};
const btn=(t,a,id='',style='')=>'<button data-action="'+a+'" data-id="'+esc(id)+'">'+t+'</button>',tag=t=>'<span>'+esc(t)+'</span>',header=(t,d,a)=>'<h1>'+t+'</h1>'+d+a,label=(t,c)=>'<label>'+t+c+'</label>',select=(n,items,v)=>'<select name="'+n+'">'+items.map(x=>'<option>'+esc(x)+'</option>').join('')+'</select>';
const empty=(t,d)=>'<h2>'+t+'</h2>'+d,cgModal=(t,b,f,n='')=>{markup=t+b+f+n;footer=f;},openModal=cgModal,closeModal=()=>modalContext=null,formData=()=>values,error=t=>lastError=t;
const save=()=>{},render=()=>{},toast=t=>lastError=t,download=()=>{},personalAI=()=>({model:'示例'}),currentDocs=()=>[],caseCategorySelect=()=>'<select name="category"></select>',xlsxCases=()=>'';
const listeners={},timers=[],setTimeout=fn=>timers.push(fn),element={addEventListener:()=>{},classList:{add:()=>{}},focus:()=>{},checked:true,innerHTML:'',textContent:''},document={addEventListener:(t,fn)=>(listeners[t]??=[]).push(fn),getElementById:()=>element,querySelectorAll:()=>[]};
${block}
const rows=crRecords(),r=crActive();assert.equal(rows.length,5);assert.equal(P().cases.length,12);crRecords();assert.equal(P().cases.length,12);assert.equal(r.findings.length,12);assert.equal(r.notes.length,2);
const raw=crExportData(r,'report'),library=JSON.stringify(P().cases);
let page=crView();assert.match(page,/分析问题/);assert.match(page,/固定依据与范围/);assert.doesNotMatch(page,/覆盖矩阵|设计覆盖率|分母/);assert.match(page,/F10/);assert.doesNotMatch(page,/F12/);crPage=2;page=crView();assert.match(page,/F12/);assert.match(page,/业务待澄清/);
assert.doesNotMatch(crScope(r),/跨门店核销应拒绝/);assert.match(crEvidence(r,r.findings[0]),/需求 \/ 原型原文/);assert.match(crEvidence(r,{evidence:[{source:'CR-REQ',quote:'伪造原文'}]}),/没有可核对/);
r.findings[0].title='<img src=x onerror=alert(1)>';crPage=1;assert.ok(crView().includes('&lt;img'));assert.ok(!crView().includes('<img src=x'));r.findings[0].title='跨门店核销预期与需求相反';
crDetail('F01');assert.match(markup,/cr-detail-prev[^>]*disabled/);assert.doesNotMatch(footer,/cr-detail-prev/);values={state:'待确认',comment:''};crNavigate('F01','prev');assert.equal(modalContext.key,'F01');
crDetail('F10');values={state:'已确认待处理',comment:''};crNavigate('F10','next');assert.equal(modalContext.key,'F10');assert.match(lastError,/填写说明/);values.comment='已核对，待补设计';crNavigate('F10','next');assert.equal(modalContext.key,'F11');assert.equal(crPage,2);assert.equal(r.findings[9].state,'已确认待处理');assert.equal(crExportData(r,'report'),raw);
crDetail('F11');r.findings[10].revision++;values={state:'待确认',comment:''};crNavigate('F11','next');assert.equal(modalContext.key,'F11');assert.match(lastError,/记录已变化/);r.findings[10].revision--;
assert.equal(JSON.stringify(P().cases),library);
crReviewOpen();assert.match(markup,/统一分类/);assert.match(markup,/操作步骤/);assert.match(markup,/预期结果/);assert.doesNotMatch(markup,/恢复各条原分类|保持原分类/);assert.equal(crReview.selected.size,2);const categoryEvent=value=>({target:{name:'crReviewCategory',value,dataset:{},id:'',closest:()=>false,hasAttribute:()=>false}});listeners.change[0](categoryEvent('cat1'));assert.equal(r.findings[0].draft.categoryId,'cat1');assert.equal(r.findings[11].draft.categoryId,'cat1');const categoryDupe={...clone(r.findings[11].draft.design),id:'category-dupe',designVersion:1,lifecycle:'ACTIVE',categoryId:'cat1'};P().cases.push(categoryDupe);listeners.change[0](categoryEvent(''));assert.equal(r.findings[0].draft.categoryId,'');assert.equal(r.findings[11].draft.categoryId,'cat1');assert.equal(crReviewCanClassify(r.findings[11]),false);assert.match(crCategorySelect('test','cat1',false,'F12',true),/disabled/);P().cases.pop();assert.equal(crExportData(r,'report'),raw);
function requestFor(p,record,keys,id){return {id,project:p.id,record:record.id,items:keys.map(key=>{const f=crItems(record).find(f=>f.key===key);return {key,revision:f.draft.revision,design:clone(f.draft.design),categoryId:f.draft.categoryId};})};}
let p=clone(P()),record=clone(r),request=requestFor(p,record,['F01','F12'],'apply1'),result=crApplyData(p,record,request);
assert.equal(result.mapping.length,2);assert.equal(result.failures.length,0);assert.equal(p.cases.length,13);const changed=p.cases.find(c=>c.id==='CR-SAMPLE-1');assert.equal(changed.originalId,'Review_001');assert.equal(changed.designVersion,2);assert.equal(changed.status,'已审核');assert.equal(changed.result,'未测');assert.equal(changed.tester,'');assert.equal(changed.analysisHistory[0].result,'通过');assert.equal(changed.analysisHistory[0].tester,'演示旧人员');assert.equal(record.findings[0].state,'待确认');assert.ok(JSON.stringify(record.originalReport)===JSON.stringify(JSON.parse(raw)));
assert.equal(crApplyData(p,record,request).id,'apply1');assert.equal(p.cases.length,13);assert.match(crApplyData(p,record,{...request,items:[]}).error,/内容不同/);
p=clone(P());record=clone(r);request=requestFor(p,record,['F01','F12'],'failure-continue');request.items[0].fail=true;result=crApplyData(p,record,request);assert.equal(result.mapping.length,1);assert.equal(result.mapping[0].key,'F12');assert.equal(result.failures[0].key,'F01');assert.equal(record.findings[0].draft.applied,null);
p=clone(P());record=clone(r);request=requestFor(p,record,['F01','F12'],'stale');p.cases[0].designVersion++;result=crApplyData(p,record,request);assert.equal(result.failures.length,1);assert.equal(result.mapping.length,1);
p=clone(P());record=clone(r);record.findings[0].draft.categoryId='deleted';assert.match(crReviewProblem(p,record.findings[0]),/分类已失效/);
p=clone(P());record=clone(r);const duplicate={...clone(record.findings[11].draft.design),id:'duplicate',originalId:'Original_001',platformNumber:99,designVersion:3,lifecycle:'ACTIVE',categoryId:'cat1',result:'通过',tester:'旧人员',status:'待审核'};p.cases.push(duplicate);request=requestFor(p,record,['F12'],'reuse');request.items[0].decision={action:'reuse',id:'duplicate',version:3};result=crApplyData(p,record,request);assert.equal(result.mapping[0].kind,'REUSE');const reused=p.cases.find(c=>c.id==='duplicate');assert.equal(reused.categoryId,'cat1');assert.equal(reused.designVersion,3);assert.equal(reused.result,'通过');assert.equal(reused.tester,'旧人员');assert.equal(p.cases.length,13);
assert.equal(crValidatePair(r.originalInput,r.originalReport).id,r.id);assert.equal(r.findings[9].state,'已确认待处理');const bad=clone(r.originalReport);bad.project='p2';assert.throws(()=>crValidatePair(r.originalInput,bad),/项目不匹配/);bad.project='p1';bad.findings[0].description='changed';assert.throws(()=>crValidatePair(r.originalInput,bad),/精确配对/);assert.equal(crExportData(r,'report'),raw);assert.match(crExportData(r,'markdown'),/F12/);assert.match(crExportData(r,'audit'),/已确认待处理/);
crSelected='CR-DEMO-PARTIAL';const partial=crActive();assert.match(crChecksView(partial),/尚未检查/);assert.match(crView(),/部分完成/);crSelected='CR-DEMO-FAILED';assert.match(crView(),/分析失败/);assert.match(crView(),/用例问题/);assert.match(crView(),/—/);crSelected='CR-DEMO-QUALITY';assert.equal(crActive().materials.length,0);assert.ok(crActive().findings.every(f=>f.kind==='QUALITY'));assert.match(crScope(crActive()),/没有需求对照/);crSelected='CR-DEMO-NONE';assert.match(crView(),/本次未发现/);
crSelected=r.id;crNewOpen();crNew.range='selected';crNew.ids=['CR-SAMPLE-1','CR-SAMPLE-12'];const prepared=crPrepareData(crNew);assert.equal(prepared.cases.length,2);assert.equal(prepared.materials[1].annotations,1);assert.equal(prepared.status,'待开始');assert.equal(prepared.originalReport,null);const frozen=JSON.stringify(prepared.originalInput);P().cases[0].title='准备后人工修改';assert.equal(JSON.stringify(prepared.originalInput),frozen);P().cases[0].title=r.cases[0].title;
crNew.ids=[];assert.throws(()=>crPrepareData(crNew),/0条/);crNew.zero=true;assert.equal(crPrepareData(crNew).cases.length,0);crNew.mode='QUALITY';assert.throws(()=>crPrepareData(crNew),/至少/);crNew.mode='COMPARE';crNew.material='project';assert.throws(()=>crPrepareData(crNew),/正文采集待正式接入/);
crRecords().unshift(prepared);crSelected=prepared.id;crStart(prepared.id);assert.equal(prepared.status,'分析中');const count=timers.length;crStart(prepared.id);assert.equal(timers.length,count);crAction('cr-cancel','');assert.equal(prepared.status,'已取消');timers.shift()();assert.equal(prepared.status,'已取消');assert.equal(prepared.originalReport,null);
crSelected=r.id;values={text:'请说明这条用例的修改建议'};crReference='F01';crAction('cr-chat-send','');assert.equal(r.chat.length,2);assert.equal(r.chat[1].reference,'F01');assert.match(crChatView(r),/添加为待确认事项/);const beforeIssues=crItems(r).length;assert.equal(crExportData(r,'report'),raw);
crChatIssueOpen(1);values={title:'需要明确观察入口',kind:'QUESTION',severity:'中',description:'人工从回复提取待确认问题',suggestion:'业务确认后补齐准备',caseId:'',quote:''};crChatIssueSave();assert.equal(crItems(r).length,beforeIssues+1);assert.equal(r.notes.at(-1).state,'待确认');assert.equal(r.notes.at(-1).origin.message,1);assert.equal(crExportData(r,'report'),raw);
crRecheck();assert.equal(crNew.parent,r.id);assert.equal(crNew.range,'selected');assert.equal(crPrepareData(crNew).originalInput.parent,r.id);assert.equal(r.findings[0].state,'待确认');
current=1;assert.equal(crRecords().length,0);assert.equal(crSelected,'');assert.equal(crReview,null);assert.match(crView(),/暂无用例分析/);assert.equal(P().cases.length,0);
`,
  ctx,
);
console.log(
  "PASS: case analysis prototype syntax, scopes, evidence, pagination, handling, drafts, transactions, conflicts, replay, import/export, cancellation and project isolation.",
);
