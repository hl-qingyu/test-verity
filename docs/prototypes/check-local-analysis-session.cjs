// Run: node docs/prototypes/check-local-analysis-session.cjs [total-prototype.html]
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||require('node:path').resolve(__dirname, '../../verity-prototype.html'),'utf8');
for(const match of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(match[1]);
const start=html.indexOf('// Requirement risk report prototype:');
const end=html.indexOf('// End requirement risk report prototype.',start);
assert.ok(start>0&&end>start);
const context=vm.createContext({assert});
vm.runInContext(String.raw`
let project={id:'p1',name:'审查项目',sample:true},modalContext=null,page='requirements';
const S={role:'项目负责人'},P=()=>project,clone=v=>JSON.parse(JSON.stringify(v));
let formResult={},failure='',markup='',sequence=0,timers=[];
const setTimeout=callback=>timers.push(callback);
let selected={requirement:['payment','inventory','invalid'],githubFile:['index.html','assets/order.js','invalid'],linkPage:['P078','invalid']};
const configs={
 '项目负责人':{configured:true,name:'负责人的个人服务',model:'model-a',apiKey:'DO-NOT-PERSIST-OWNER-SECRET'},
 '项目成员':{configured:true,name:'成员的个人服务',model:'model-b',apiKey:'DO-NOT-PERSIST-MEMBER-SECRET'}
};
const personalAI=()=>configs[S.role]||{},save=()=>{},render=()=>{},toast=()=>{};
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const tag=(text)=>'<span>'+esc(text)+'</span>',btn=(text,action,id='')=>'<button data-action="'+action+'" data-id="'+esc(id)+'">'+text+'</button>';
const header=(title,desc,actions)=>'<h1>'+title+'</h1><p>'+desc+'</p>'+actions,icon=()=>'',note=v=>'<p>'+v+'</p>';
const inp=(name,value)=>'<input name="'+name+'" value="'+esc(value)+'">',label=(name,body)=>'<label>'+name+body+'</label>';
const requirementSelect=(title,name,options,value)=>'<label>'+title+'<input name="'+name+'" value="'+esc(value)+'"></label>';
const formData=()=>formResult,error=v=>failure=v,closeModal=()=>{modalContext=null;},navigate=v=>{page=v;};
const openModal=(title,body)=>{markup=body;},crypto={randomUUID:()=>String(++sequence).padStart(8,'0')};
const form={classList:{add(){}},querySelectorAll:selector=>{
 const name=selector.match(/name=(\w+)/)?.[1];return (selected[name]||[]).map(value=>({value}));
}};
const document={getElementById:()=>form};
`+html.slice(start,end),context);
vm.runInContext(String.raw`
// No source category is mandatory; at least one valid requirement or prototype is required.
assert.equal(localSession(),null);assert.ok(localSessionSend('检查需求'));
localSessionCreateModal();
assert.ok(!markup.includes('name="mainRequirement"'));assert.match(markup,/name="requirement"/);assert.match(markup,/name="githubFile"/);assert.match(markup,/name="prototypeFile"/);
assert.ok(!markup.includes('<h4>HTML文件</h4>'));assert.ok(!markup.includes('<h4>图片文件</h4>'));
assert.match(markup,/订单详情.html/);assert.match(markup,/订单详情.png/);
const prototypeFiles=LOCAL_SESSION_PROTOTYPE_FILES.splice(0);assert.ok(!localSessionSourceFields({}).includes('name="prototypeFile"'));LOCAL_SESSION_PROTOTYPE_FILES.push(...prototypeFiles);
assert.ok(!markup.includes('type="file"'));assert.ok(!markup.includes('data-session-row'));
assert.ok(markup.endsWith('</form>'),'Create dialog must not have trailing template characters');
const beforeCreate=project.localAnalysisSessions.length;
formResult={title:'支付检查',focus:'检查支付状态',mainRequirement:''};
const mixedSelection=selected;selected={requirement:['invalid'],githubFile:[],linkPage:[],prototypeFile:[]};
localSessionAction('local-session-create');assert.match(failure,/至少选择/);assert.equal(project.localAnalysisSessions.length,beforeCreate);
selected=mixedSelection;localSessionAction('local-session-create');
const created=localSession();assert.equal(project.localAnalysisSessions.length,beforeCreate+1);
assert.equal(created.mainRequirement,null);assert.deepEqual(created.requirements,['payment','inventory']);
assert.deepEqual(created.githubFiles,['index.html','assets/order.js']);assert.deepEqual(created.linkPages,['P078']);
assert.equal(localSessionReport(),undefined);assert.equal(localSessionChat().messages.length,0);
assert.equal(created.reports.length,0);
for(const [field,value] of [['requirement','payment'],['prototypeFile','html-order-v3'],['prototypeFile','image-order-v2'],['linkPage','P032'],['githubFile','index.html']]){
 const previousCount=project.localAnalysisSessions.length;
 selected={[field]:[value]};formResult={title:'仅选择 '+value,focus:'检查已选资料'};localSessionCreateModal();localSessionAction('local-session-create');
 assert.equal(project.localAnalysisSessions.length,previousCount+1);
 const current=localSession(),scope=localSessionScope();assert.equal(current.mainRequirement,null);
 if(field!=='requirement'){assert.deepEqual(current.requirements,[]);assert.ok(!localSessionScopeSummary(scope).includes('订单需求.md'));}
 if(field==='prototypeFile'){assert.deepEqual(scope.prototypeFiles,[value]);assert.match(localSessionScopeSummary(scope),/原型HTML/);}
}
selected=mixedSelection;

// Existing reports attach once, and their own evidence remains the fixed source.
const report=riskSelected(),beforeAttach=project.localAnalysisSessions.length;
const review=localSessionAttachReport(report);
assert.equal(localSessionReport(),report);assert.equal(project.localAnalysisSessions.length,beforeAttach+1);
assert.equal(review.mainRequirement,null,'Imported report material must not be relabelled as the order demo requirement');
assert.equal(localSessionAttachReport(report),review);assert.equal(project.localAnalysisSessions.length,beforeAttach+1);
assert.equal(created.reportId,undefined,'Choosing a sample must not claim it analyzed the new record');
const featureA=report.features[0],featureB=report.features.find(f=>f!==featureA);
assert.ok(featureA&&featureB);
const riskA=report.risks.find(r=>r.feature===featureA);assert.ok(riskA);
assert.deepEqual(localSessionScope().materials,report.materials);
assert.notEqual(localSessionScope().materials,report.materials);

// The total discussion and two functional discussions retain separate drafts and attachments.
localSessionOpenChat();const totalChat=localSessionChat();totalChat.draft='整体遗漏草稿';
localSessionPick({files:[{name:'整体补充.txt',size:100}],value:'file'});
localSessionOpenChat(featureA);const chatA=localSessionChat();assert.equal(chatA.draft,'');
assert.equal(chatA.attachments.length,0);chatA.draft='功能甲草稿';
localSessionPick({files:[{name:'功能甲.txt',size:110},{name:'功能甲.txt',size:110}],value:'file'});
assert.deepEqual(chatA.attachments,[{name:'功能甲.txt',size:110}]);
localSessionOpenChat(featureB);const chatB=localSessionChat();assert.equal(chatB.draft,'');
localSessionPick({files:[{name:'功能乙.txt',size:120}],value:'file'});chatB.draft='功能乙草稿';
assert.equal(localSessionSend('只检查功能乙'),'');assert.ok(chatB.messages.some(m=>m.text==='只检查功能乙'));
assert.equal(chatA.messages.length,0);assert.equal(totalChat.messages.length,0);
localSessionOpenChat(featureA);assert.equal(localSessionChat(),chatA);assert.equal(chatA.draft,'功能甲草稿');
assert.deepEqual(chatA.attachments,[{name:'功能甲.txt',size:110}]);
localSessionOpenChat();assert.equal(localSessionChat(),totalChat);assert.equal(totalChat.draft,'整体遗漏草稿');
assert.deepEqual(totalChat.attachments,[{name:'整体补充.txt',size:100}]);
assert.equal(localSessionSend('检查整个需求'),'');assert.equal(totalChat.draft,'');assert.equal(totalChat.attachments.length,0);
assert.ok(!totalChat.messages.some(m=>m.text==='只检查功能乙'));

// Following up a risk references its functional chat; cancellation and chatting never handle risks.
riskChoose(report.id);const handlingBefore=JSON.stringify(report.handling);
localSessionAction('local-session-risk-chat',riskA.id);assert.equal(localSessionChat(),chatA);
assert.equal(chatA.reference.riskId,riskA.id);
localSessionAction('local-session-unreference');assert.equal(chatA.reference,null);
assert.equal(JSON.stringify(report.handling),handlingBefore);
localSessionAction('local-session-risk-chat',riskA.id);
S.role='没有配置的用户';const beforeBlocked=JSON.stringify(chatA);
assert.match(localSessionSend('不能借用别人的配置'),/自己的AI服务/);assert.equal(JSON.stringify(chatA),beforeBlocked);
S.role='项目成员';
assert.equal(riskSaveHandling({project:project.id,report:report.id,id:riskA.id,revision:0},{status:'已确认待补充',note:'产品最新确认：补充条件和异常流程'}),'');
const handled=JSON.stringify(report.handling);
assert.equal(localSessionSend('结合产品最新确认继续检查'),'');
const sent=chatA.messages.find(m=>m.role==='user'&&m.text==='结合产品最新确认继续检查');
assert.equal(sent.reference.riskId,riskA.id);assert.equal(sent.shared.handling[riskA.id].note,'产品最新确认：补充条件和异常流程');
assert.ok(sent.shared.risks.every(r=>r.feature===featureA));
assert.deepEqual(sent.ai,{name:'成员的个人服务',model:'model-b'});
assert.deepEqual(sent.attachments,[{name:'功能甲.txt',size:110}]);
assert.equal(chatA.reference,null);assert.equal(chatA.draft,'');assert.equal(chatA.attachments.length,0);
assert.equal(JSON.stringify(report.handling),handled);
assert.ok(!JSON.stringify(project).includes('DO-NOT-PERSIST'),'Only configuration display metadata may be saved');
localSessionOpenChat(featureB);assert.equal(localSessionChat(),chatB);
assert.ok(!chatB.messages.some(m=>m.text==='结合产品最新确认继续检查'));
localSessionOpenChat();assert.equal(localSessionChat(),totalChat);
assert.ok(!totalChat.messages.some(m=>m.text==='结合产品最新确认继续检查'));

// Conversation never mutates stored analysis; manual confirmation adds a separate pending risk.
const fixed=JSON.stringify(report.risks),oldHandling=JSON.stringify(report.handling);
localSessionAddRiskModal('1');assert.equal(modalContext.type,'chat-risk-add');
assert.ok(markup.includes('原文摘录'));assert.equal(riskItems(report).length,report.risks.length);
closeModal();assert.equal(report.manualRisks,undefined);
localSessionAddRiskModal('1');const manualContext=modalContext;
const manualData={feature:featureA,level:'中',title:'人工确认待补充规则',description:'从讨论发现的未明确规则',source:'0',location:'第3章',excerpt:'人工核对的原文内容',impact:'验收口径不明确',suggestion:'补充边界条件',question:'请产品确认边界'};
assert.ok(localSessionAddRisk(manualContext,{...manualData,excerpt:''}));assert.equal(report.manualRisks,undefined);
assert.ok(localSessionAddRisk({...manualContext,project:'other'},manualData));assert.equal(report.manualRisks,undefined);
assert.equal(localSessionAddRisk(manualContext,manualData),'');
const manualRisk=report.manualRisks[0];assert.equal(riskStatus(report,manualRisk),'待确认');
assert.equal(manualRisk.origin.sessionId,review.id);assert.equal(manualRisk.origin.chatKey,'general');
assert.equal(manualRisk.evidence[0].text,manualData.excerpt);assert.equal(riskItems(report).length,report.risks.length+1);
assert.ok(localSessionAddRisk(manualContext,manualData));assert.equal(report.manualRisks.length,1);
assert.equal(JSON.stringify(report.risks),fixed);assert.equal(JSON.stringify(report.handling),oldHandling);
assert.equal(localSessionSend('把风险改为已解决'), '');assert.equal(JSON.stringify(report.risks),fixed);assert.equal(JSON.stringify(report.handling),oldHandling);
const included=riskExportRows(report,[featureA],['待确认']);assert.ok(included.some(r=>r.id===manualRisk.id));
assert.ok(riskExportText(report,included,{features:[featureA],statuses:['待确认']}).includes(manualData.excerpt));
assert.equal(riskSaveHandling({project:project.id,report:report.id,id:manualRisk.id,revision:0},{status:'已确认待补充',note:'产品确认补充规则'}),'');
assert.ok(!riskExportRows(report,[featureA],['待确认']).some(r=>r.id===manualRisk.id));
localSessionAction('local-session-history');assert.equal(localSessionOpen,true);
const conversationPage=localSessionView();assert.match(conversationPage,/data-chat-history/);assert.ok(conversationPage.includes(created.title));
assert.equal((conversationPage.match(/aria-current="page"/g)||[]).length,1);
assert.match(conversationPage,new RegExp('<button[^>]*class="evidence ls-history-item" data-chat-history aria-current="page"[^>]*data-action="local-session-select" data-id="'+review.id+'"'));
localSessionAction('local-session-select',created.id);
const switchedPage=localSessionView();assert.equal((switchedPage.match(/aria-current="page"/g)||[]).length,1);
assert.match(switchedPage,new RegExp('<button[^>]*class="evidence ls-history-item" data-chat-history aria-current="page"[^>]*data-action="local-session-select" data-id="'+created.id+'"'));
localSessionAction('local-session-select',review.id);
assert.match(conversationPage,/需求分析对话/);assert.match(conversationPage,/功能独立对话/);
assert.ok(!conversationPage.includes('risk-list'));assert.ok(!conversationPage.includes('保存完整报告快照'));
localSessionCreateModal();assert.ok(!markup.includes('data-chat-history'));
localSessionAction('local-session-risk-return',riskA.id);assert.equal(localSessionOpen,false);assert.equal(riskSelected(),report);assert.equal(modalContext.id,riskA.id);assert.match(markup,/人工处理/);
localSessionAction('local-session-feature-chat',featureB);assert.equal(localSessionOpen,true);assert.equal(localSessionChat(),chatB);
localSessionAction('local-session-close');assert.equal(localSessionOpen,false);
assert.ok(!riskReportPage().includes('报告快照'));assert.ok(riskReportPage().includes('导出风险清单'));

// Project changes cannot reveal or select another project's record.
const previous=project;project={id:'p2',name:'另一个项目'};assert.equal(localSession(),null);
localSessionAction('local-session-select',review.id);assert.equal(localSession(),null);assert.equal(localSessionReport(),null);
assert.ok(riskSaveHandling({project:previous.id,report:report.id,id:riskA.id,revision:2},{status:'已解决',note:'跨项目操作'}));
project=previous;assert.equal(localSession(),review);assert.equal(JSON.stringify(report.risks),fixed);

// Old single-chat records keep their messages but never acquire an unrelated report.
const oldMessages=[{role:'user',text:'历史问题'},{role:'assistant',text:'历史回复'}];
project={id:'legacy',name:'历史项目',sample:true,localAnalysisDemo:{messages:clone(oldMessages),draft:'旧草稿',attachments:[{name:'旧附件.txt',size:9}],reports:[{version:1,discussion:clone(oldMessages)}]}};
const legacy=localSession();assert.deepEqual(localSessionChat().messages,oldMessages);
assert.equal(localSessionChat().draft,'旧草稿');assert.equal(legacy.reportId,undefined);
assert.equal(localSessionReport(),undefined);riskSelected();assert.equal(localSessionReport(),undefined);
assert.deepEqual(legacy.reports[0].discussion,oldMessages);
localSessionAttachReport(riskSelected());assert.notEqual(localSession(),legacy);
localSessionAction('local-session-select',legacy.id);assert.deepEqual(localSessionChat().messages,oldMessages);
assert.equal(legacy.reportId,undefined);

// The composer owns the sole attachment button; the shared UI adapter must skip its custom input.
localSessionOpenChat();const composer=localSessionChatPanel(legacy,null);
assert.match(composer,/id="localSessionChatFiles" data-theme-file="custom" hidden/);
assert.equal((composer.match(/>添加文件<\/button>/g)||[]).length,1);
assert.ok(!composer.includes('选择文件'));

// Rendering after a project switch must use the attached report, even when report IDs coincide.
const firstReport=clone(report);firstReport.id='unrelated-first';firstReport.title='不应显示的第一份报告';
firstReport.risks.forEach(r=>r.title='第一份报告风险 '+r.id);
const attachedReport=clone(report);attachedReport.id='RR-DEMO';attachedReport.title='当前审查的第二份报告';
attachedReport.risks.forEach(r=>r.title='当前关联报告风险 '+r.id);
riskChoose('previous-project-report');
project={id:'switch-one',name:'切换项目一',riskReports:[firstReport,attachedReport]};
localSessionAttachReport(attachedReport);
let renderedReview=localSessionView();
assert.equal(riskSelected(),attachedReport);assert.ok(renderedReview.includes(attachedReport.risks[0].title));
assert.ok(!renderedReview.includes(firstReport.risks[0].title));
const sameIdReport=clone(attachedReport),otherFirst=clone(firstReport);
project={id:'switch-two',name:'切换项目二',riskReports:[otherFirst,sameIdReport]};
localSessionAttachReport(sameIdReport);
renderedReview=localSessionView();
assert.equal(riskSelected(),sameIdReport,'An equal report ID in another project must not retain the previous project filter');
assert.ok(renderedReview.includes(sameIdReport.risks[0].title));assert.ok(!renderedReview.includes(otherFirst.risks[0].title));

// Reading or failing to read a link must preserve selection; only an explicitly empty ready tree clears it.
let treeVisible=true,checkedLinks=['P078'];
const linkResult={innerHTML:''},linkButtons=[{disabled:false}];
const linkBox={dataset:{selected:'["P078"]'},isConnected:true,
 querySelector:selector=>selector==='.ls-link-result'?linkResult:treeVisible?{}:null,
 querySelectorAll:selector=>selector==='button'?linkButtons:checkedLinks.map(value=>({value}))};
const linkForm={querySelector:()=>linkBox,querySelectorAll:()=>checkedLinks.map(value=>({value}))};
const readButton={closest:()=>linkBox};
localSessionReadLink(readButton,true);treeVisible=false;checkedLinks=[];
assert.equal(linkBox.dataset.readState,'loading');assert.deepEqual(localSessionCaptureLinks(linkForm),['P078']);
timers.shift()();assert.equal(linkBox.dataset.readState,'failed');assert.deepEqual(localSessionCaptureLinks(linkForm),['P078']);
assert.match(linkResult.innerHTML,/失败/);
localSessionReadLink(readButton);assert.deepEqual(localSessionCaptureLinks(linkForm),['P078']);
timers.shift()();treeVisible=true;checkedLinks=['P078'];
assert.equal(linkBox.dataset.readState,'ready');assert.deepEqual(localSessionCaptureLinks(linkForm),['P078']);
checkedLinks=[];assert.deepEqual(localSessionCaptureLinks(linkForm),[]);
`,context);
const adapter=html.split('\n').find(line=>line.includes("document.querySelectorAll('input[type=file]').forEach"));
assert.ok(adapter);
vm.runInNewContext(adapter,{document:{querySelectorAll:()=>[{dataset:{themeFile:'custom'}}],createElement:()=>{throw Error('Duplicate file button');}}});
console.log('PASS: independent chats, manual risk confirmation/cancel/idempotency, immutable initial results, filtered checklist export, history preservation and project isolation');
