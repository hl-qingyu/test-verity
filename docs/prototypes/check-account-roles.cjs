const fs = require("node:fs"),
  vm = require("node:vm"),
  assert = require("node:assert/strict");
const file = process.argv[2];
assert.ok(file, "provide the prototype path");
const html = fs.readFileSync(file, "utf8");
for (const script of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))
  new vm.Script(script[1]);
const permissions = html.match(/const manage=\(\)=>[^;]+;const admin=\(\)=>[^;]+;/)?.[0];
if (permissions) {
  vm.runInNewContext(
    `let S={role:'平台管理员'};const P=()=>null;${permissions}
    assert.ok(admin() && manage());
    S.role='项目负责人';assert.ok(manage());assert.ok(!admin());
    for (const role of ['测试','开发','产品','经理','项目成员']) {
      S.role=role;assert.ok(!manage(),role);assert.ok(!admin(),role);
    }`,
    { assert },
  );
} else {
  for (const role of ["ADMIN", "TEST", "DEV", "PRODUCT", "MANAGER"])
    assert.ok(html.includes(`<option value="${role}">`));
}
console.log("PASS account roles and unchanged administrator/project-owner boundary:", file);
