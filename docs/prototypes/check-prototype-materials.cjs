// Run: node docs/prototypes/check-prototype-materials.cjs [total-prototype.html]
const fs = require("node:fs"),
  vm = require("node:vm"),
  assert = require("node:assert/strict");
const html = fs.readFileSync(
  process.argv[2] ||
    "C:/Users/geekonup/Documents/Codex/2026-08-17/new-chat/outputs/verity-prototype.html",
  "utf8",
);
// Validate the renderer as well as the page script; preview code must actually parse.
for (const m of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))
  new vm.Script(m[1]);
const script = html.match(/<script>\s*('use strict';[\s\S]*?)<\/script>/)[1];
const materials = script.slice(
  script.indexOf("// Prototype materials:"),
  script.indexOf("let casePage=1"),
);
assert.ok(!materials.includes("proto-bind"));
assert.ok(!materials.includes("bindPrototype"));
const requirements = script.slice(
  script.indexOf("let requirementTab="),
  script.indexOf("function viewRequirements()"),
);
const ui = script.slice(
  script.indexOf("const ICONS="),
  script.indexOf("const modules="),
);
const layout = script.slice(
  script.indexOf("function header("),
  script.indexOf("function toolbar("),
);
const sourceUI = script.slice(
  script.indexOf("function requirementAnalysisFiles("),
  script.indexOf("function prototypeLinkKey"),
);
const navigation = script
  .split("\n")
  .find((line) => line.startsWith("function navigate("));
const hashEntry = script
  .split("\n")
  .find((line) => line.startsWith("window.addEventListener('hashchange'"));
const startupEntry = script.slice(
  script.lastIndexOf("save();render();"),
  script.length,
);
const sourceModal = script.slice(
  script.indexOf("function requirementSourceModal("),
  script.indexOf(
    "\nfunction ",
    script.indexOf("function requirementSourceModal(") + 20,
  ),
);
const context = vm.createContext({
  assert,
  URL,
  location: { origin: "https://verity.example.test" },
  setTimeout: (resolve) => resolve(),
  crypto: require("node:crypto").webcrypto,
});
vm.runInContext(
  `
${ui}
${layout}
let p={id:'p1',docs:[],rules:[],repos:[{name:'team/web'}],tasks:[]},role='owner';
const S={get role(){return role;}};let page='prototypes';
const P=()=>p,currentDocs=()=>p.docs.filter(d=>!d.archived).sort((a,b)=>(a.order||0)-(b.order||0)),docRoot=d=>d.documentId||d.id;
const connections=[{id:'mine',configured:true,localOwner:'owner',selected:['team/web','team/other']},{id:'foreign',configured:true,localOwner:'other',selected:['team/web']}];
const ghConnections=()=>connections.filter(c=>c.localOwner===role);
let lastPage='';const save=()=>{},render=()=>{if(page==='prototypes')lastPage=viewPrototypes();},toast=()=>{},DEFAULT_RULES=[],docSelection=new Set(),urls=new Map();
let skDraft=null,ovScope=null,ovEntryError='',ovState={request:0,mode:'ready'},modalContext=null,pendingUploadFiles=[],form={},lastError='',lastModal='',sub='',selectedTemplate='',filterText='',filterState='';
const elements={prototypeReadResult:{innerHTML:''},dialog:{classList:{add:()=>{}}}},document={body:{classList:{remove:()=>{}}},addEventListener:()=>{},getElementById:id=>elements[id],querySelectorAll:()=>[]};
const routes={prototypes:[],overview:[]},history={replaceState:()=>{}},events={},window={scrollTo:()=>{},addEventListener:(name,callback)=>events[name]=callback};const ovRestoreTarget=()=>{};
const formData=()=>form,error=m=>lastError=m,closeModal=()=>{modalContext=null},openModal=(title,body,footer)=>{lastModal=title+body+footer};
const MATERIAL_DEMO_IMAGE='<svg/>',previewed=[],docPreview=d=>{previewed.push(clone(d));return '<img alt="preview">';};
${requirements}
${materials}
${sourceUI}
${sourceModal}
${navigation}
${hashEntry}
`,
  context,
);
(async () => {
  await vm.runInContext(
    `(async()=>{
 const input={connectionId:'mine',repo:'team/web',refType:'分支',ref:'main',path:'prototypes/orders',scenario:'成功'};
 assert.equal(prototypeGitError(input),'');
 assert.equal(prototypeGitError({...input,path:''}),'');assert.equal(prototypeFiles('')[0].path,'index.html');
 assert.ok(prototypeGitError({...input,connectionId:'foreign'}));
 assert.ok(prototypeGitError({...input,repo:'team/other'}));
 for(const path of ['../x','/tmp','a//b','a/./b','a\\\\b'])assert.ok(prototypeGitError({...input,path}));
 assert.ok(prototypeGitError({...input,refType:'提交',ref:'abc'}));
 for(const url of ['javascript:alert(1)','file:///tmp/a','data:text/html,a','https://name:secret@example.com'])assert.equal(prototypeURL(url),'');
 assert.equal(prototypeURL('https://example.com/p'),'https://example.com/p');
 form={...input,name:'订单原型',description:'页面说明',group:''};
 await prototypeAction('proto-read','',{});assert.equal(prototypeRead.files.length,3);assert.match(elements.prototypeReadResult.innerHTML,/未发送 GitHub/);
 assert.match(elements.prototypeReadResult.innerHTML,/proto-files-all/);assert.match(elements.prototypeReadResult.innerHTML,/proto-files-clear/);
 elements.prototypeFileCount={textContent:''};const oldQuery=document.querySelectorAll,boxes=[{checked:true},{checked:false},{checked:false}];document.querySelectorAll=()=>boxes;
 await prototypeAction('proto-files-all','',{});assert.ok(boxes.every(b=>b.checked));assert.equal(elements.prototypeFileCount.textContent,'已选 3 / 3');
 await prototypeAction('proto-files-clear','',{});assert.ok(boxes.every(b=>!b.checked));assert.equal(elements.prototypeFileCount.textContent,'已选 0 / 3');
 const overLimit=Array.from({length:101},()=>({checked:false}));document.querySelectorAll=()=>overLimit;
 await prototypeAction('proto-files-all','',{});assert.ok(overLimit.every(b=>b.checked));document.querySelectorAll=oldQuery;
 assert.ok(!elements.prototypeReadResult.innerHTML.includes('<pre'));
 assert.ok(!elements.prototypeReadResult.innerHTML.includes('内置虚构原型源码'));
 for(const scenario of ['权限不足','版本不存在','目录为空','限流','超时']){form.scenario=scenario;await prototypeAction('proto-read','',{});assert.equal(prototypeRead,null);assert.equal(p.docs.length,0);}
 form.scenario='成功';await prototypeAction('proto-read','',{});
 const original=appendPrototype({...form,type:'GITHUB',sha:prototypeRead.sha,files:prototypeRead.files});
 assert.equal(original.version,undefined);assert.equal(original.files.length,3);
 const snapshot=requirementSourceSnapshot(original);prototypeRead.files[0].body='changed';assert.notEqual(original.files[0].body,'changed');
 const rule={id:'r1',title:'查询订单',role:'员工',pre:'',action:'点击查询',expected:'展示匹配订单',status:'已确认',version:1,sources:[{id:'req',name:'需求.md',version:'v1',role:'需求文档'}]};
 p.rules.push(rule);p.tasks.push({snapshot:{rules:[{id:'r1'}],documentSources:[snapshot]}});
 assert.equal(saveRequirement(rule,{...rule,sources:[...rule.sources,requirementSourceSnapshot(original,'原型图','index.html 第4行','查询按钮')]},'review'),'');
 assert.equal(rule.sources.length,2);assert.equal(rule.status,'待审核');assert.equal(rule.history[0].sources.length,1);assert.equal(rule.history[0].status,'已确认');
 assert.equal(saveRequirement(rule,{...rule},'review'),'');assert.equal(rule.history.length,1);
 const newer=saveLivePrototype({...original,name:'订单原型新配置',sha:'a'.repeat(40),files:[{path:'new.html',body:'new'}]},original.id);
 assert.equal(newer.id,original.id);assert.equal(newer.version,undefined);assert.equal(newer.archived,undefined);
 assert.equal(rule.sources[1].sha,snapshot.sha);assert.equal(rule.sources[1].snapshot.name,'订单原型');assert.equal(p.tasks[0].snapshot.documentSources[0].sha,snapshot.sha);
 assert.equal(appendPrototype({...original},original.id),null);
 assert.equal(prototypeDocs().length,1);assert.equal(requirementSourceRole(newer),'原型图');
 const image=appendPrototype({name:'图片',type:'PNG',group:''}),imageSnapshot=requirementSourceSnapshot(image);
 const nextImage=appendPrototype({name:'图片新版',type:'PNG',group:''},image.id);
 assert.equal(image.archived,true);assert.equal(nextImage.version,'v2');assert.equal(imageSnapshot.version,'v1');
 const beforeCheck=JSON.stringify(p);
 await prototypeAction('proto-view',newer.id,{});
 assert.equal(prototypeGitStatus(newer).status,'updated');assert.equal(JSON.stringify(p),beforeCheck);
 assert.match(prototypePreview(newer),/发现新的提交/);assert.ok(!prototypePreview(newer).includes('更新资料版本'));assert.equal(prototypeCurrent(newer).sha,prototypeGitStatus(newer).latestSha);
 previewed.length=0;requirementSourceModal('r1');assert.equal(previewed.find(d=>d.type==='GITHUB').sha,snapshot.sha);assert.equal(previewed.find(d=>d.type==='GITHUB').name,'订单原型');
 const latestEvidence=requirementSourceSnapshot(newer);assert.equal(latestEvidence.sha,prototypeGitStatus(newer).latestSha);assert.equal(rule.sources[1].sha,snapshot.sha);
 const detectedSha=prototypeGitStatus(newer).latestSha;assert.match(detectedSha,/^[a-f0-9]{40}$/);
 await checkPrototypeGit(newer.id,'current');assert.equal(prototypeGitStatus(newer).status,'current');
 await checkPrototypeGit(newer.id,'failed');assert.equal(prototypeGitStatus(newer).status,'failed');
 assert.match(prototypePreview(newer),/不能判断是否有更新/);assert.ok(!prototypePreview(newer).includes('更新资料版本'));
 const pending=checkPrototypeGit(newer.id,'updated'),latest=checkPrototypeGit(newer.id,'current');
 await Promise.all([pending,latest]);assert.equal(prototypeGitStatus(newer).status,'current');
 role='other';connections[1].selected=[];await checkPrototypeGit(newer.id);assert.equal(prototypeGitStatus(newer).status,'failed');
 role='owner';assert.equal(prototypeGitStatus(newer).status,'current');
 assert.equal(prototypeGitStatus({...original,archived:true}).status,'history');assert.equal(prototypeGitStatus({...newer,refType:'提交'}).status,'fixed');
 assert.equal(JSON.stringify(p),beforeCheck);
 assert.match(requirementSources(),/原型资料/);assert.match(requirementSources(),/GitHub 实时分支/);
 const originalFileList=JSON.stringify(original.files),chosenFile=requirementAnalysisFiles(original)[0];
 const narrowed=requirementAnalysisSnapshot(original,'原型图',{querySelectorAll:()=>[{dataset:{sourceId:original.id},value:chosenFile}]});
 assert.equal(narrowed.files.length,1);assert.equal(narrowed.snapshot.files.length,1);assert.equal(JSON.stringify(original.files),originalFileList);
 const link=appendPrototype({name:'链接',type:'LINK',url:'https://example.com',group:''});
 assert.match(prototypePreview(link),/未保存页面快照/);assert.match(prototypePreview(link),/rel="noopener noreferrer"/);
 assert.ok(!prototypePreview(link).includes('<iframe'));
 assert.match(prototypePreview(link),/加载预览/);assert.match(prototypePreview(link),/放大查看/);
 const linkFrame=prototypeLinkFrame(link);
 assert.match(linkFrame,/<iframe/);assert.match(linkFrame,/sandbox="allow-scripts allow-same-origin allow-popups allow-downloads"/);
 assert.doesNotMatch(linkFrame,/allow-top-navigation|allow-popups-to-escape-sandbox/);
 assert.match(linkFrame,/referrerpolicy="no-referrer"/);
 assert.ok(!prototypeLinkFrame({...link,url:'javascript:alert(1)'}).includes('<iframe'));
 assert.ok(!prototypeLinkFrame({...link,url:location.origin+'/private'}).includes('<iframe'));
 const frameHost={innerHTML:''},loadButton={textContent:'加载预览',closest:()=>({querySelector:()=>frameHost})};
 await prototypeAction('proto-link-load',link.id,loadButton);
 assert.match(frameHost.innerHTML,/<iframe/);assert.equal(loadButton.textContent,'重新加载');
 const savedLinkEvidence=requirementSourceSnapshot(link);assert.equal(savedLinkEvidence.snapshot.url,'https://example.com');
 const linkBefore=JSON.stringify(link);await prototypeAction('proto-link-load',link.id,loadButton);assert.equal(JSON.stringify(link),linkBefore);
 saveLivePrototype({...link,url:'https://example.com/new'},link.id);assert.equal(savedLinkEvidence.snapshot.url,'https://example.com');assert.equal(link.version,undefined);
 const countBeforeXeta=p.docs.length,xeta=addXetaPrototypeLink();addXetaPrototypeLink();
 assert.equal(p.docs.length,countBeforeXeta+1);assert.equal(xeta.sample,false);assert.equal(xeta.url,XETA_PROTOTYPE_URL);
 assert.ok(!prototypePreview(xeta).includes('<iframe'));assert.equal(xeta.version,undefined);
 const unsafe={...newer,files:[{path:'<img>',body:'<script>alert(1)</'+'script>'}]};
 assert.ok(!prototypePreview(unsafe).includes('<script>'));assert.ok(!prototypePreview(unsafe).includes('alert(1)'));assert.ok(!prototypePreview(unsafe).includes('<pre'));
 prototypeModal('GITHUB');assert.match(lastModal,/我的 GitHub 连接/);assert.ok(lastModal.includes('<legend>资料信息</legend>'));assert.ok(lastModal.includes('<legend>读取范围</legend>'));assert.ok(lastModal.includes('<legend>文件清单</legend>'));assert.match(lastModal,/目录或文件（选填）/);assert.ok(!lastModal.includes('ZIP 整包上传'));assert.ok(!lastModal.includes('name="token"'));
 const count=p.docs.length;addPrototypeDemo();addPrototypeDemo();assert.equal(p.docs.length,count+3);
 assert.match(viewPrototypes(),/原型清单/);assert.match(viewPrototypes(),/proto-workspace/);assert.match(viewPrototypes(),/proto-detail-head/);assert.ok(!viewPrototypes().includes('关联验收点'));assert.ok(!viewPrototypes().includes('proto-bind'));assert.match(viewPrototypes(),/历史版本/);selectedPrototype=newer.id;assert.ok(!viewPrototypes().includes('data-action="proto-update"'));assert.ok(!viewPrototypes().includes('data-action="proto-history"'));assert.match(viewPrototypes(),/编辑来源/);
 await prototypeAction('proto-demo','',{});
 const demo=p.docs.find(d=>d.id===selectedPrototype);assert.equal(demo.type,'GITHUB');assert.equal(prototypeGitStatus(demo).status,'updated');assert.match(lastPage,/发现新的提交/);
 const demoCount=p.docs.length;await prototypeAction('proto-update-demo','',{});assert.equal(p.docs.length,demoCount);assert.equal(selectedPrototype,demo.id);
 demo.sha='c91f5e2'.padEnd(40,'0');await prototypeAction('proto-update-demo','',{});assert.equal(prototypeGitStatus(demo).status,'updated');assert.notEqual(prototypeGitStatus(demo).latestSha,demo.sha);
 prototypeGitChecks.clear();navigate('prototypes');await Promise.resolve();assert.equal(prototypeGitStatus(demo).status,'current');assert.match(lastPage,/当前资料与所选版本一致/);
 prototypeGitChecks.clear();location.hash='#prototypes';events.hashchange();await Promise.resolve();assert.equal(prototypeGitStatus(demo).status,'current');
 prototypeGitChecks.clear();selectedPrototype='';
 ${startupEntry}
 await Promise.resolve();assert.equal(p.docs.find(d=>d.id===selectedPrototype).type,'GITHUB');assert.notEqual(prototypeGitStatus(p.docs.find(d=>d.id===selectedPrototype)).status,'idle');
 p.prototypeGroups=[...(p.prototypeGroups||[]),'拖动目标组'];const savedSources=JSON.stringify(rule.sources);assert.equal(movePrototypeGroup(original.id,'拖动目标组'),true);assert.equal(original.group,'拖动目标组');assert.equal(movePrototypeGroup(original.id,'拖动目标组'),false);assert.equal(movePrototypeGroup(original.id,'不存在'),false);assert.equal(JSON.stringify(rule.sources),savedSources);
 p={id:'p2',docs:[],rules:[],repos:[],tasks:[]};assert.equal(prototypeDocs().length,0);assert.equal(prototypeRepoOptions('mine').length,0);
 assert.match(viewPrototypes(),/添加第一份/);
 assert.match(viewPrototypes(),/上传 HTML/);
 prototypeModal('HTML');assert.match(lastModal,/HTML 文件/);assert.match(lastModal,/[.]html,[.]htm/);
 const localHtml=appendPrototype({name:'本地页面',type:'HTML',body:'<script>alert(1)</'+'script>',group:''});
 const localPreview=prototypePreview(localHtml);assert.ok(!localPreview.includes('<script>'));assert.ok(localPreview.includes('&lt;script&gt;'));
 const localNext=appendPrototype({name:'本地页面',type:'HTM',body:'新版',group:''},localHtml.id);
 assert.equal(localNext.version,'v2');assert.equal(localHtml.body,'<script>alert(1)</'+'script>');
 await prototypeAction('proto-update',localNext.id,{});assert.match(lastModal,/[.]html,[.]htm/);

 })()`,
    context,
  );
  console.log(
    "PASS: all script syntax, GitHub authorization intersection, failures, URL and code safety, fixed versions, source history, mixed sources and project isolation",
  );
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
