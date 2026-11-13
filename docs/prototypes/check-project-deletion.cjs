const fs = require("node:fs"),
  vm = require("node:vm"),
  assert = require("node:assert/strict");
const file =
  process.argv[2] || "outputs/prototype-pending/verity-prototype.html";
const html = fs.readFileSync(file, "utf8");
for (const m of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))
  new vm.Script(m[1]);
const source = html.slice(
  html.indexOf("function visibleProjects()"),
  html.indexOf("const manage=", html.indexOf("function visibleProjects()")),
);
assert.ok(source.includes("confirmProjectDeletion"));
vm.runInNewContext(
  `
const S={role:'项目负责人',active:'p1',projects:[{id:'p1',name:'甲',cases:[{title:'保留用例'}],tasks:[]},{id:'p2',name:'乙',tasks:[]}]};
const P=()=>visibleProjects().find(p=>p.id===S.active)||visibleProjects()[0];
let modalContext=null,errorText='',rendered=0;const manage=()=>S.role!=='项目成员',admin=()=>S.role==='平台管理员',esc=String,btn=()=>'',openModal=()=>{},save=()=>{},closeModal=()=>{modalContext=null},render=()=>rendered++,toast=()=>{},error=t=>errorText=t,history={replaceState(){}};let page='project';
${source}
openProjectDeletion();S.projects[0].tasks=[{status:'COMPLETED',chat:[{status:'QUEUED'}]}];confirmProjectDeletion('p1');assert.ok(errorText);assert.equal(visibleProjects().length,2);
S.projects[0].tasks[0].chat[0].status='COMPLETED';S.role='项目成员';confirmProjectDeletion('p1');assert.equal(visibleProjects().length,2);
S.role='项目负责人';confirmProjectDeletion('p1');assert.equal(visibleProjects().length,1);assert.equal(P().id,'p2');assert.equal(S.projects[0].cases[0].title,'保留用例');assert.ok(S.projects[0].deletedAt);assert.equal(S.projects[0].deletedBy,'项目负责人');
openProjectDeletion();confirmProjectDeletion('p1');assert.equal(visibleProjects().length,1);confirmProjectDeletion('p2');assert.equal(visibleProjects().length,0);assert.equal(S.projects.length,2);assert.equal(P(),undefined);
`,
  { assert },
);
console.log(
  "PASS project deletion: syntax, owner/member, active child, stale dialog, retained data and empty project list:",
  file,
);
