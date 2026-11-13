// Run: node docs/prototypes/check-project-overview.cjs [total-prototype.html]
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const target =
  process.argv[2] || require('node:path').resolve(__dirname, '../../verity-prototype.html');
const html = fs.readFileSync(target, "utf8");
for (const match of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))
  new vm.Script(match[1]);
const start = html.indexOf("// Project overview prototype:"),
  end = html.indexOf("// End project overview prototype.", start);
assert.ok(start > 0 && end > start);
const block = html.slice(start, end);
const adoption = html.slice(
  html.indexOf("function cgAdoption("),
  html.indexOf("function viewGenerate("),
);
assert.ok(adoption.includes("function cgAdoption("));
assert.ok(!/\b(fetch|XMLHttpRequest|alert|confirm|prompt)\s*\(/.test(block));
assert.ok(html.includes('style id="project-overview-layout"'));
assert.ok(
  html.includes("ovRestoreTarget();save();render();enterPrototypePage();"),
);
assert.ok(html.includes("ovAllowed('code',selected,i)"));
assert.ok(html.includes("ovAllowed('generate',r,s)"));
assert.ok(!/viewTasks|navItem\('tasks'\)/.test(html));
const context = vm.createContext({ assert, console, URLSearchParams });
vm.runInContext(
  String.raw`
const clone=x=>JSON.parse(JSON.stringify(x));
const esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const modules=[['requirements','需求分析'],['generate','用例生成'],['coverage','用例分析'],['code','代码分析'],['changes','变更分析']];
const routes=Object.fromEntries(modules.map(([k,v])=>[k,[v,'spark']]));
const icon=()=>'',tag=x=>'<span>'+esc(x)+'</span>',header=(t,d,a='')=>'<h1>'+t+'</h1>'+d+a;
const btn=(t,a,id='',kind='')=>'<button data-action="'+a+'" data-id="'+esc(id)+'">'+t+'</button>';
let p={id:'p1',name:'<项目>',sample:false,docs:[],cases:[],tasks:[]},page='overview',lastError='',modal='',rendered=0,seeded=0;
const P=()=>p,render=()=>rendered++,error=t=>lastError=t,openModal=(t,b)=>modal=t+b,closeModal=()=>modal='',taskDetail=()=>{};
const cgRecords=()=>{seeded++;return p.generationRecords||[]},crRecords=()=>{seeded++;return p.caseReviews||[]},changeRecords=()=>{seeded++;return p.changeAnalyses||[]},riskDemo=()=>{seeded++;return {id:'demo',risks:[],state:'已完成'}};
const document={getElementById:()=>({focus(){},scrollIntoView(){}}),querySelector:()=>({focus(){}}),addEventListener(){}};
const callbacks=[],setTimeout=fn=>callbacks.push(fn),location={hash:'#overview'},history={pushState:(s,t,url)=>location.hash=url,replaceState:(s,t,url)=>location.hash=url};
const navigate=(module,fromOverview=false)=>{page=module;if(!fromOverview){ovScope=null;ovEntryError='';ovState.request++;}location.hash='#'+module;render();};
let riskCumulativeProject='',riskSourceFilter='',riskFeatureFilter='',riskListQuery='',riskCurrentPage=1,riskView={status:'全部'},localSessionOpen=false;
const riskChoose=id=>riskView.report=id,riskSelected=()=>p.riskReports?.find(r=>r.id===riskView.report);
let cgSelected='',cgTab='',cgPage=1,cgQuery='',cgChatOpen=false,cgSelection=new Set(),cgFilters={},cgCaseState='',caseCategoryFilter='*',casePage=1,caseSearchApplied=[],caseSelection=new Set();
const cgActive=()=>p.generationRecords?.find(r=>r.id===cgSelected);
let crSelected='',crTab='',crPage=1,crFilters={};const crActive=()=>p.caseReviews?.find(r=>r.id===crSelected);
let codeSelectedRecord='',codeTargetFilter='',codePage=1,codeChatOpen=false;const codeSelectedTask=()=>p.tasks.find(r=>r.id===codeSelectedRecord);
let changeSelected='',changeTab='',changePage=1,changeChatOpen=false,changeRecordQuery='',changeFilters={};const changeActive=()=>p.changeAnalyses?.find(r=>r.id===changeSelected);
${adoption}
${block}
// Empty real-browser project: no demo seeding, zero is genuine, no coverage or old workflow.
let data=ovData();assert.equal(seeded,0);assert.equal(data.records.length,0);assert.equal(data.cases,0);
let markup=viewOverview();assert.match(markup,/还没有分析记录/);assert.match(markup,/&lt;项目&gt;/);assert.doesNotMatch(markup,/验收点|覆盖率|hero-content|验证路径/);
assert.equal((markup.match(/class="panel ov-stat"/g)||[]).length,4);
assert.doesNotMatch(markup,/用例采纳率|AI结果验收/);
p.docs=[{id:'d1',documentId:'r1'},{id:'d2',documentId:'r1'},{id:'proto',materialKind:'prototype',selectedPaths:['a','b']},{id:'deleted',deletedAt:'now'},{id:'archived',archived:true}];
p.cases=[{id:'active',lifecycle:'ACTIVE'},{id:'old-active'},{id:'retired',lifecycle:'RETIRED'},{id:'deleted',deleted_at:'now'}];
p.riskReports=[{id:'rr',title:'需求<原文>',time:'2026-10-01',state:'已完成',risks:[{id:'a'},{id:'b'},{id:'c'}],manualRisks:[{id:'m'}],handling:{b:{status:'已确认待补充'},c:{status:'已解决'}}}];
p.generationRecords=[{id:'g1',title:'历史部分结果',status:'失败',outcome:'PARTIAL',time:'2026-10-04',suggestions:[{key:'s1',status:'待审阅'},{key:'s2',status:'已应用'},{key:'s3',status:'已复用'},{key:'s4',status:'已忽略'},{key:'s5',status:'应用失败'}],questions:[{key:'q1'},{key:'q2',handling:{conclusion:'已确认'}}],applications:[]},{id:'g2',status:'已完成',time:'2026-10-03',suggestions:[{key:'s6',status:'已复用'}],questions:[]}];
p.caseReviews=[{id:'cr',title:'用例检查',status:'已完成',time:'2026-10-05',findings:[{key:'a',state:'待确认',draft:{applied:{case_id:1}}},{key:'b',state:'已确认待处理'},{key:'c',state:'已解决'}],notes:[{key:'n',state:'待确认'}]}];
p.changeAnalyses=[{id:'ch',title:'变更',status:'已完成',time:'2026-10-06',targets:[{state:'部分完成（演示）'}],impacts:[{key:'i1',handling:{status:'待处理'}},{key:'i2',handling:{status:'需补充证据'}}],changes:[{key:'change'}],regressions:[{key:'r1',handling:{status:'待审阅'}},{key:'r2',handling:{status:'暂缓'}},{key:'r3',handling:{status:'采纳'}}]}];
p.tasks=[{id:'qt',module:'requirements',report_id:'rr',status:'已完成',time:'2026-10-01'},...Array.from({length:11},(_,i)=>({id:'code'+i,module:'code',title:'代码 '+i,time:'2026-10-'+String(10+i).padStart(2,'0'),status:i===0?'RUNNING':i===1?'QUEUED':'已完成',snapshot:{issues:[{id:'i1',status:'待处理'},{id:'i2',status:'已处理'}]}}))];
const frozen=JSON.stringify(p);data=ovData();assert.equal(JSON.stringify(p),frozen);
assert.equal(data.requirement,1);assert.equal(data.prototype,1);assert.equal(data.cases,2);assert.equal(data.running,1);assert.equal(data.queued,1);
assert.equal(data.records.filter(r=>r.module==='requirements').length,1);assert.equal(ovRecent(data.records).length,8);
assert.equal(ovRecent(data.records,'running').length,2);assert.ok(ovRecent(data.records,'running').some(r=>r.id==='code0'));
assert.equal(ovRecent(data.records,'completed').length,8);assert.ok(ovRecent(data.records,'completed').every(r=>r.status==='已完成'));
assert.equal(ovRecent([{status:'已完成',outcome:'PARTIAL'}],'completed').length,1);
ovAction('ov-filter','completed');assert.equal(ovState.filter,'completed');assert.match(viewOverview(),/id="ov-tab-completed"[^>]*aria-selected="true"/);
assert.match(viewOverview(),/class="ov-record-list"/);assert.match(viewOverview(),/查看记录/);
assert.equal(data.attention[0].parts[0].count,2);assert.equal(data.attention[0].parts[1].count,1);
assert.equal(data.attention[1].parts[0].count,1);assert.equal(data.attention[1].parts[1].count,1);
assert.equal(data.attention[2].parts[0].count,2);assert.equal(data.attention[2].parts[1].count,1);
assert.equal(data.attention[3].parts[0].count,9);assert.equal(data.attention[4].parts.at(-1).count,1);
assert.equal(data.records.find(r=>r.id==='ch').outcome,'PARTIAL');
const reused={suggestions:[{key:'x',status:'已复用'}],applications:[{failures:[{key:'x'}]}]};assert.equal(ovApplicationFailed(reused),false);
reused.suggestions[0].status='应用失败';assert.equal(ovApplicationFailed(reused),true);
assert.equal(ovApplicationFailed({applications:[{items:[{key:'x',status:'FAILED'}]},{items:[{key:'x',status:'SUCCESS'}]}]}),false);
ovState.filter='failed';assert.match(viewOverview(),/历史失败记录/);
// Attention navigation picks exactly one record and filter. Applying a draft did not close the issue.
ovAction('ov-attention','0:0');assert.equal(page,'requirements');assert.equal(riskSourceFilter,'rr');assert.equal(riskView.status,'待确认');
page='overview';ovAction('ov-attention','2:1');assert.equal(crSelected,'cr');assert.equal(crFilters.state,'已确认待处理');
page='overview';ovAction('ov-attention','3:0');assert.match(modal,/选择需要查看的记录/);assert.equal(ovChoices.length,9);
ovAction('ov-choice','0');assert.equal(page,'code');assert.equal(ovAllowed('code',codeSelectedTask(),{status:'已处理'}),false);assert.equal(ovAllowed('code',codeSelectedTask(),{status:'待处理'}),true);
const selectedCode=codeSelectedRecord,savedHash=location.hash;ovScope=null;codeSelectedRecord='';location.hash=savedHash;ovRestoreTarget();assert.equal(codeSelectedRecord,selectedCode);assert.equal(ovEntryError,'');
page='overview';ovAction('ov-attention','1:0');assert.equal(cgSelected,'g1');assert.equal(ovAllowed('generate',cgActive(),{status:'已复用'}),false);
page='overview';ovAction('ov-record',ovRecord('generate',p.generationRecords[0]).key);assert.equal(ovAllowed('generate',cgActive(),{status:'已复用'}),true);
page='overview';ovAction('ov-attention','1:1');assert.equal(cgTab,'questions');
page='overview';ovAction('ov-attention','4:4');assert.equal(changeSelected,'ch');assert.equal(changeTab,'regressions');assert.equal(changeFilters.status,'暂缓');
assert.match(ovNavigationNote(),/来自项目概览/);ovAction('ov-clear','');assert.equal(changeFilters.status,'全部状态');ovRestoreTarget();assert.equal(changeFilters.status,'全部状态');
page='overview';let prevented=0;ovTabKey({target:{closest:()=>({dataset:{id:'all'}})},key:'ArrowLeft',preventDefault:()=>prevented++});assert.equal(ovState.filter,'failed');assert.equal(prevented,1);
ovTabKey({target:{closest:()=>({dataset:{id:'running'}})},key:'ArrowRight',preventDefault(){}});assert.equal(ovState.filter,'completed');
ovTabKey({target:{closest:()=>({dataset:{id:'completed'}})},key:'End',preventDefault(){}});assert.equal(ovState.filter,'failed');
page='overview';ovAction('ov-mode','partial');assert.match(viewOverview(),/暂不可用/);ovAction('ov-mode','error');assert.match(viewOverview(),/概览读取失败/);assert.doesNotMatch(viewOverview(),/class="panel ov-stat"/);
// Refresh cannot write into another project or a later request.
ovAction('ov-refresh','');const oldCallback=callbacks.at(-1);p={id:'p2',name:'空项目',sample:false,docs:[],cases:[],tasks:[]};ovReset();oldCallback();assert.equal(ovState.project,'p2');assert.equal(ovState.mode,'ready');assert.equal(ovData().records.length,0);
ovAction('ov-choice','0');assert.match(lastError,/项目已切换/);
page='code';location.hash='#code?ov='+encodeURIComponent(JSON.stringify({project:'p1',key:JSON.stringify(['code','record','code2'])}));ovRestoreTarget();assert.match(ovEntryError,/项目已切换/);assert.match(ovMissingView(),/未自动切换到其他记录/);
location.hash='#code?ov=broken';ovRestoreTarget();assert.match(ovEntryError,/入口已失效/);
console.log('PASS overview: counts, empty isolation, historical identity, filter-before-limit, attention, scoped navigation, refresh restoration, errors, application outcomes and stale refresh.');
`,
  context,
);
