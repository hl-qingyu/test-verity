// Run: node docs/prototypes/check-code-findings.cjs [prototype.html]
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = process.argv[2] || require('node:path').resolve(__dirname, '../../verity-prototype.html');
const html = fs.readFileSync(path, 'utf8');
for (const match of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
const line = prefix => html.split(/\r?\n/).find(text => text.startsWith(prefix));
const examples = html.slice(html.indexOf('const ISSUES='), html.indexOf('function newProject('));
const helpers = html.slice(html.indexOf('// Code finding presentation:'), html.indexOf('// End code finding presentation.'));
const targetHelpers = html.slice(html.indexOf('// Code analysis targets and input review'), html.indexOf('// End code analysis targets.'));
assert.ok(html.includes('导入代码分析'));
assert.ok(html.includes('function codeImportOpen('));
assert.ok(html.includes('Skill v2的input.json与report.json'));
assert.ok(html.includes('导入不调用AI'));
assert.ok(html.includes('下载AI候选结果（演示）'));
assert.ok(html.includes('重新校验候选（演示）'));
assert.ok(html.includes('原始响应单独保存；结构或证据校验失败时仍可下载排查'));
const pickerCode = html.slice(html.indexOf('const DEMO_FILES='), html.indexOf('function refOptions('));
const detail = html.slice(html.indexOf('function issueDetail('), html.indexOf('\nfunction ', html.indexOf('function issueDetail(') + 1));
const saveHandler = line("case'save-issue':").slice("case'save-issue':".length).replace(/break;\}\s*$/, '}');
const setup = `
let modalContext, lastModal='', saved=0,filePicker,formValues={status:'已处理',comment:'人工说明'},lastError='';
const clone=x=>JSON.parse(JSON.stringify(x));
const esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const tag=(x,c)=>'<span>'+esc(x)+'</span>',icon=()=>'',empty=()=>'<p>无发现</p>';
const btn=(text,action,id='')=>'<button data-action="'+action+'" data-id="'+esc(id)+'">'+text+'</button>';
const header=(title,desc,actions)=>'<h1>'+title+'</h1>'+desc+actions;
const label=(name,body)=>'<label>'+name+body+'</label>',inp=(name,value)=>'<input name="'+name+'" value="'+esc(value)+'">';
const select=(name,values,value)=>'<select name="'+name+'">'+values.map(x=>'<option>'+esc(x)+'</option>').join('')+'</select>';
const tr=cells=>'<tr>'+cells.map(x=>'<td>'+x+'</td>').join('')+'</tr>',table=(heads,rows)=>'<table>'+tr(heads)+rows.join('')+'</table>';
const openModal=(title,body)=>lastModal=title+body,toast=()=>{},closeModal=()=>{},render=()=>{},save=()=>saved++;
const formData=()=>formValues,error=x=>lastError=x,navigate=()=>{},personalAI=()=>({model:'demo'}),crypto={randomUUID:()=>String(++sequence)};
let sequence=0;
const binding=()=>({skill:{name:'代码分析',version:1},template:{name:'代码分析模板',version:1}}),note=x=>'<p>'+x+'</p>';
${examples}
const p={issues:clone(ISSUES),tasks:[{id:'A',module:'code',title:'第一条记录',snapshot:{repos:['server @ A'],issues:clone(ISSUES)}},{id:'B',module:'code',title:'第二条记录',snapshot:{repos:['server @ B'],issues:clone(ISSUES)}}]};
const P=()=>p;
const currentDocs=()=>p.docs||[],requirementAnalysisFilePicker=()=>'<div>固定GitHub文件选择</div>',localSessionLinkPicker=()=>'<div class="ls-link-picker">读取页面</div>',ensureCodePrototypeDemo=()=>{};
let targetInputs=[],materialInputs=[],materialFileInputs=[];
let linkReady=false;
const materialCards=[{querySelector:q=>q==='[name=sourceDoc]'?{value:'link'}:linkReady?{checked:true}:null}];
const nodes={codePreflight:{innerHTML:''},codeMaterialHint:{textContent:''},codeCreateSubmit:{disabled:false},dialog:{classList:{add(){}}},taskForm:{querySelectorAll:q=>q==='.analysis-source-card'?materialCards:q.includes('codeTarget')?targetInputs.filter(x=>x.checked):q.includes('sourceFile')?materialFileInputs:materialInputs}};
for(const id of ['scopeRepos','scopeTree','scopeCount','scopeSelected','scopePreview'])nodes[id]={innerHTML:'',textContent:'',querySelectorAll:()=>[]};
const document={getElementById:id=>nodes[id]||null,querySelectorAll:q=>q.includes('codeTarget')?targetInputs:[]};
${pickerCode}
${line('function refOptions(')}
${line('function renderPicker(')}
${line('function renderPickerTree(')}
${line('function codeMaterialList(')}
${line('function codeMaterialTabs(')}
${line('function scopeHTML(')}
${line('let codeChatMode=')}
${line('let codeChatMessages=')}
${line('function codeRecords(')}
${line('function codeSelectedTask(')}
${line('function codeRecordScope(')}
${targetHelpers}
${helpers}
${line('function codeChatPage(')}
${line('function codeAnalysisPage(')}
${detail}
${line('function codeTaskDetail(')}
${line('function reportMarkdown(')}
function saveIssue(){${saveHandler}}
`;
vm.runInNewContext(setup + `
const highUnknown=codeFinding({...ISSUES[1],severity:'高'});
assert.equal(highUnknown.evidenceState,'证据不足');
const lowKnown=codeFinding({...ISSUES[0],severity:'低'});
assert.equal(lowKnown.evidenceState,'静态证据充分');
assert.equal(codeFinding(ISSUES[2]).severity,'待评估');
assert.equal(codeFinding({id:'F-001',code:'different code',title:'自有发现'}).evidenceState,'证据不足','Do not graft demo evidence onto unrelated code');
const snapshot=JSON.stringify(p.tasks[0].snapshot);
issueDetail('F-001');
assert.ok(!lastModal.includes('页面展示')&&!lastModal.includes('页面渲染文件未提供'));
assert.ok(!lastModal.includes('详情错误显示'));
assert.match(lastModal,/模型回退为 PENDING_VERIFY/);
assert.ok(!reportMarkdown(p.tasks[0]).includes('页面展示'));
assert.match(codeAnalysisPage(),/严重程度：高/);
assert.ok(codeAnalysisPage().includes('<strong>2</strong><small>证据不足'));
issueDetail('F-003');
for(const text of ['触发条件','判断依据','调用链与证据','缺少证据','影响范围','修复建议','验证建议','待补充证据','人工处理'])assert.ok(lastModal.includes(text),text);
assert.equal(JSON.stringify(p.tasks[0].snapshot),snapshot,'Rendering must not rewrite a saved snapshot');
codeSelectedRecord='B';issueDetail('F-003');saveIssue();
assert.equal(p.tasks[1].snapshot.issues[2].status,'已处理');
assert.equal(p.tasks[0].snapshot.issues[2].status,undefined,'Do not change another record with the same finding id');
assert.equal(codeFinding(p.tasks[1].snapshot.issues[2]).evidenceState,'证据不足','Handling must not turn missing evidence into confirmed evidence');
assert.equal(saved,1);
const item=p.tasks[1].snapshot.issues[0];
item.trigger='<img src=x onerror=bad()>';item.chain=[{stage:'<img>',location:'<script>',observation:'<img>',code:'<script>bad()</script>'}];
issueDetail('F-001');assert.ok(!lastModal.includes('<img'));assert.ok(!lastModal.includes('<script>'));assert.match(lastModal,/&lt;img/);
const markdown=reportMarkdown(p.tasks[1]);
for(const text of ['触发条件','判断依据','影响范围','验证建议','待补充证据','证据状态：证据不足'])assert.ok(markdown.includes(text),text);
p.tasks[1].snapshot.issues=Array.from({length:11},(_,i)=>({...ISSUES[0],id:'page-'+i}));codePage=2;
assert.equal((codeAnalysisPage().match(/class="code-finding-card"/g)||[]).length,1,'Pagination remains ten per page');
codeChatOpen=true;assert.match(codeAnalysisPage(),/代码分析对话/);assert.ok(!codeAnalysisPage().includes('code-finding-card'));
p.tasks[1].snapshot.issues=[];codeChatOpen=false;assert.match(codeAnalysisPage(),/无发现/);

// Independent goals, registered repository roles and source modes.
const targets=Object.keys(CODE_TARGETS),backend=[{repositoryKind:'BACKEND'}],frontend=[{repositoryKind:'WEB'}],mobile=[{repositoryKind:'FLUTTER'}];
assert.deepEqual(codePreflight(targets,backend,[]).map(g=>g.ready),[true,false,false]);
assert.deepEqual(codePreflight(targets,backend,[{}]).map(g=>g.ready),[true,true,false]);
assert.equal(codePreflight(['BUG'],mobile,[])[0].ready,true);
assert.equal(codePreflight(['FRONTEND_BACKEND_MISMATCH'],[...mobile,...backend],[])[0].ready,true);
assert.equal(codePreflight(['FRONTEND_BACKEND_MISMATCH'],[...frontend,...backend],[])[0].ready,true);
assert.equal(codePreflight(['FRONTEND_BACKEND_MISMATCH'],[{repositoryKind:'OTHER',path:'frontend.dart'},...backend],[])[0].ready,false);
assert.deepEqual(codePreflight(targets,[],[]).map(g=>g.ready),[false,false,false]);
for(const files of [[],backend,frontend,mobile,[...frontend,...mobile],[{repositoryKind:'OTHER'},...backend]]){
  const goals=codePreflight(targets,files,[{}]);
  assert.match(codeCreationError({targets,goals}),/必须同时选择/,'Missing either role blocks the entire multi-target task');
}
for(const client of [frontend,mobile])assert.equal(codeCreationError({targets,goals:codePreflight(targets,[...backend,...client],[{}])}),'');

p.sample=true;p.repos=[{name:'server',kind:'BACKEND',commit:'one'},{name:'web',kind:'WEB',commit:'two'},{name:'app',kind:'FLUTTER',commit:'three'}];p.localCode=[];
p.docs=[{id:'req',name:'规则.md',version:'v1',type:'MD'},{id:'link',name:'原型链接',type:'LINK',materialKind:'prototype'},{id:'proto',name:'原型.html',version:'v2',type:'HTML',materialKind:'prototype'},{id:'gh',name:'GitHub资料',version:'v1',type:'GITHUB'}];
const input=value=>({value,checked:true,closest:()=>({classList:{toggle(){}}})});targetInputs=targets.map(input);
configureCodeTask();
assert.ok(lastModal.indexOf('检查目标')<lastModal.indexOf('代码来源与文件范围'));
assert.ok(lastModal.indexOf('代码来源与文件范围')<lastModal.indexOf('需求与原型依据'));
assert.match(lastModal,/value="link" [^>]*onchange/);assert.doesNotMatch(lastModal,/value="link" disabled/);assert.equal(nodes.codeCreateSubmit.disabled,true);
const serverFile=pickerFiles().find(f=>f.repo==='server');filePicker.selected.add(serverFile.key);
assert.ok(pickerFiles().filter(f=>f.repo==='server').every(f=>f.kind==='backend'));
assert.ok(pickerFiles().filter(f=>f.repo==='web'||f.repo==='app').every(f=>f.kind==='frontend'));
materialInputs=[input('req')];updateCodePreflight();assert.equal(nodes.codeCreateSubmit.disabled,true);
assert.match(nodes.codePreflight.innerHTML,/缺少前端或移动端文件/);
assert.match(nodes.codePreflight.innerHTML,/role="alert"/);
const selectedBefore=[...filePicker.selected];targetInputs[1].checked=false;updateCodePreflight();
assert.deepEqual([...filePicker.selected],selectedBefore);assert.equal(codeFormSelection().selectedMaterials[0].id,'req');
assert.match(nodes.codeMaterialHint.textContent,/可选补充依据/);
targetInputs[1].checked=true;materialInputs=[input('link')];assert.equal(codeFormSelection().goals[1].ready,false);
linkReady=true;assert.equal(codeFormSelection().goals[1].ready,true);linkReady=false;
materialInputs=[input('gh')];assert.equal(codeFormSelection().goals[1].ready,false);
materialFileInputs=[{dataset:{sourceId:'gh'}}];assert.equal(codeFormSelection().goals[1].ready,true);
materialInputs=[input('proto')];assert.equal(codeFormSelection().goals[1].ready,true);
filePicker.mode='local';filePicker.selected.clear();
assert.ok(pickerFiles().every(f=>f.source==='local'));
assert.ok(pickerFiles().some(f=>f.repositoryKind==='BACKEND')&&pickerFiles().some(f=>f.repositoryKind==='FLUTTER'));
for(const kind of ['BACKEND','FLUTTER'])filePicker.selected.add(pickerFiles().find(f=>f.repositoryKind===kind).key);
assert.ok(codeFormSelection().goals.every(g=>g.ready));
updateCodePreflight();assert.equal(nodes.codeCreateSubmit.disabled,false);
filePicker.mode='github';filePicker.selected.clear();filePicker.selected.add(serverFile.key);
materialInputs=[];formValues={title:'仅后端检查',focus:'检查状态'};const oldCount=p.tasks.length;startCodeTask();
assert.equal(p.tasks.length,oldCount,'The submit guard also blocks direct/keyboard submission');assert.match(lastError,/缺少前端或移动端文件/);
targetInputs[2].checked=false;updateCodePreflight();assert.equal(nodes.codeCreateSubmit.disabled,false);
assert.equal(filePicker.selected.has(serverFile.key),true,'Unchecking consistency preserves the selected files');
startCodeTask();
assert.equal(p.tasks.length,oldCount+1);assert.equal(p.tasks[0].status,'待接入');assert.equal(p.tasks[0].snapshot.issues.length,0);
assert.deepEqual(p.tasks[0].snapshot.target_results.map(g=>g.status),['PENDING','BLOCKED']);
assert.equal(p.tasks[0].snapshot.codeVersions[0].kind,'BACKEND');
targetInputs=[input('REQUIREMENT_DEVIATION')];startCodeTask();assert.equal(p.tasks.length,oldCount+1);assert.match(lastError,/所有目标/);
targetInputs=[];startCodeTask();assert.match(lastError,/至少选择/);

// Distinct detail sections and filters; a multi-target finding appears once.
const bug=codeTargetSections(codeFinding(ISSUES[2]));assert.match(bug,/执行路径与错误原因/);assert.ok(!bug.includes('需求与实现对照')&&!bug.includes('接口与字段对照'));
const requirement=codeTargetSections(codeFinding(ISSUES[1]));assert.match(requirement,/需求与实现对照/);assert.ok(!requirement.includes('执行路径与错误原因'));
const combined=codeTargetSections(codeFinding(ISSUES[0]));assert.match(combined,/执行路径与错误原因/);assert.match(combined,/接口与字段对照/);
codeSelectedRecord='A';codeTargetFilter='REQUIREMENT_DEVIATION';codePage=1;
assert.equal((codeAnalysisPage().match(/class="code-finding-card"/g)||[]).length,1);
codeTargetFilter='BUG';assert.equal((codeAnalysisPage().match(/class="code-finding-card"/g)||[]).length,2);
codeTargetFilter='ALL';assert.equal((codeAnalysisPage().match(/class="code-finding-card"/g)||[]).length,3);
assert.match(reportMarkdown(p.tasks.find(t=>t.id==='A')),/检查目标：前后端一致性/);
assert.match(reportMarkdown(p.tasks.find(t=>t.id==='A')),/字段名称/);
`, {assert});
console.log('PASS: target-based create/detail/filter/export, independent input checks, repository/source roles, selection preservation, no fabricated results, evidence safety, handling and pagination');
