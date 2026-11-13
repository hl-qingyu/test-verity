const fs = require("node:fs"),
  vm = require("node:vm"),
  assert = require("node:assert/strict");
const target =
    process.argv[2] || require('node:path').resolve(__dirname, '../../verity-prototype.html'),
  html = fs.readFileSync(target, "utf8");
for (const m of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))
  new vm.Script(m[1]);
const block = html.match(
  /<script id="ai-acceptance-prototype">([\s\S]*?)<\/script>/,
)[1];
assert.ok(html.includes("'ai-acceptance':['AI结果验收','chart']"));
assert.ok(
  html.includes(
    "['skills','ai-acceptance','project','platform'].filter(k=>k!=='ai-acceptance'||admin()).map(navItem)",
  ),
);
assert.ok(html.includes("'ai-acceptance':viewAIAcceptance"));
assert.ok(!/\b(fetch|XMLHttpRequest|alert|confirm|prompt)\s*\(/.test(block));
assert.ok(html.includes("aaRender(page,views[page]())"));
vm.runInNewContext(
  String.raw`
let project={id:'p1',sample:false},projectList=null,errors=[],saved=0,rendered=0,modal='',modalContext=null;
const visibleProjects=()=>S.projects.filter(p=>!p.deletedAt);
const P=()=>project,S={role:'平台管理员',get projects(){return projectList || [project]}},admin=()=>S.role==='平台管理员',header=(t,d)=>'<h1>'+t+'</h1>'+d,clone=x=>JSON.parse(JSON.stringify(x)),esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const btn=(t,a,id='',k='')=>'<button data-action="'+a+'" data-id="'+esc(id)+'">'+t+'</button>',label=(t,c)=>'<label>'+t+c+'</label>',select=()=>'';
const save=()=>saved++,render=()=>rendered++,error=t=>errors.push(t),openModal=(t,b,f)=>modal=t+b+f,closeModal=()=>modal='',document={addEventListener(){},getElementById:()=>null};
const input={requirements:[],generate:[],coverage:[],code:[],changes:[]},ovSources=(p=P())=>p.data || input,ovStatus=r=>r.status;
const riskSelected=()=>input.requirements[0],cgActive=()=>input.generate[0],crActive=()=>input.coverage[0],codeSelectedTask=()=>input.code[0],changeActive=()=>input.changes[0],crypto={randomUUID:()=>String(Math.random())};
${block}
S.role='测试人员';assert.match(aaOverview(),/无权访问/);S.role='平台管理员';assert.match(viewAIAcceptance(),/用例采纳率/);assert.equal(aaRender('overview','原概览'),'原概览');assert.match(aaOverview(),/结果总览/);assert.equal((aaOverview().match(/class="panel aa-module"/g)||[]).length,5);assert.ok(!aaOverview().includes('<details class="aa-special"'));assert.match(viewAIAcceptance(),/全部项目/);
for(const [n,size] of [2,8].entries())input.code.push({id:'r'+n,status:'已完成',title:'固定代码结果',snapshot:{issues:Array.from({length:size},(_,i)=>({key:'C'+i,title:'结论'+i,description:'依据固定版本'}))}});
const original=JSON.stringify(input);
for(const r of input.code)for(const [i,item]of r.snapshot.issues.entries())item.status=i?'误报':'已确认';
const processed=JSON.stringify(input);assert.match(aaOverview(),/20\.0%/);assert.match(aaOverview(),/2\/10/);assert.ok(!aaOverview().includes('逐条验收'));
assert.ok(!aaRecordPanel('code',input.code[0]).includes('逐条验收'));assert.match(aaRecordPanel('code',input.code[0]),/遗漏与基准/);
assert.equal(project.aiAcceptance,undefined);
aaOpen('code','r0');aaDraft.state.criteria.push({id:'C1',title:'缺少异常恢复',basis:'原固定范围第2节',critical:true,baseline:true,result:'MISSING',matched_key:'',scope_confirmed:true});aaDraft.state.scope_reviewed=true;aaDraft.state.note='已核对固定范围';aaAction('aa-save','');
const result=aaMetrics('code',input.code[0]);assert.equal(result.missing,1);assert.equal(result.baseline_total,1);assert.equal(result.baseline_covered,0);assert.equal(saved,1);
input.generate=[{id:'g1',status:'已完成',suggestions:[{key:'g0',kind:'NEW',status:'已忽略'},{key:'g1',kind:'NEW',status:'已应用'}]}];
let generation=aaMetrics('generate',input.generate[0]);assert.equal(generation.valid,1);assert.equal(generation.dismissed,1);assert.equal(generation.invalid,0);assert.equal(generation.adopted,1);
aaOpen('code','r0');aaDraft.state.criteria[0].title='尚未保存修改';aaLeave();assert.match(modal,/放弃未保存的清单/);aaAction('aa-continue','');assert.match(modal,/遗漏与基准/);aaAction('aa-discard','');assert.equal(aaDraft,null);
assert.equal(JSON.stringify(input.code),JSON.stringify(JSON.parse(processed).code));
project={id:'p2'};assert.equal(aaMetrics('code',input.code[0]).valid,1);assert.equal(aaMetrics('code',input.code[0]).missing,0);
projectList=[{id:'p1',name:'项目一',data:{...input,code:[input.code[0]]}},{id:'p2',name:'项目二',data:{...input,code:[input.code[1]]}}];
aaProjectId='all';assert.match(aaOverview(),/2\/10/);assert.ok(!aaOverview().includes('data-action="aa-nav"'));
aaProjectId='p1';assert.match(aaOverview(),/1\/2/);assert.ok(!aaOverview().includes('2/10'));assert.match(aaOverview(),/data-action="aa-nav"/);
aaProjectId='p2';assert.match(aaOverview(),/1\/8/);assert.equal(project.id,'p2');aaProjectId='all';
`,
  { assert, console },
);
console.log(
  "PASS AI acceptance: five modules, weighted counts, detail-based counts without duplicate confirmation, baseline/missing, history, validation, dirty cancel and project isolation: " +
    target,
);
