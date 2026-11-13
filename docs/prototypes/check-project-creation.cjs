const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
const file = process.argv[2] || require('node:path').resolve(__dirname, '../../verity-prototype.html');
const html = fs.readFileSync(file, "utf8");
for (const script of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(script[1]);
const start = html.indexOf("case'new-project':"), end = html.indexOf("case'", html.indexOf("case'create-project':", start) + 5);
assert.ok(start > 0 && end > start);
const actions = html.slice(start, end);
const permissions = html.match(/const manage=\(\)=>[^;]+;const admin=\(\)=>[^;]+;/)[0];
vm.runInNewContext(`
let S={role:'测试',projects:[],active:null},markup='',data;
const P=()=>S.projects.find(p=>p.id===S.active);
${permissions}
const label=(a,b)=>a+b,inp=()=>'',esc=String,select=()=>'<select>选负责人</select>',btn=()=>'';
const openModal=(title,body)=>{markup=body},formData=()=>data,newProject=name=>({id:'p'+S.projects.length,name}),save=()=>{},closeModal=()=>{},navigate=()=>{},toast=()=>{},error=message=>{throw Error(message)};
function act(action){switch(action){${actions}}}
for(const role of ['测试','开发','产品','经理','项目成员']){
  S.role=role;act('new-project');assert.ok(markup.includes('readonly'));assert.ok(!markup.includes('选负责人'));
  data={name:'本人项目',identifier:'own_'+role,owner:'篡改负责人',description:''};act('create-project');
  assert.equal(P().details.owner,role);assert.ok(manage());
  S.role='其他成员';assert.ok(!manage());
}
S.role='平台管理员';act('new-project');assert.ok(markup.includes('选负责人'));
data={name:'管理员创建',identifier:'admin_own',owner:'周宁',description:''};act('create-project');assert.equal(P().details.owner,'周宁');
`,{assert});
console.log("PASS project creation: all ordinary roles, self owner, tampered owner ignored and administrator selection:",file);
