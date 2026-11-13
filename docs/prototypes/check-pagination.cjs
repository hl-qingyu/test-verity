const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const filename =
  process.argv[2] || require('node:path').resolve(__dirname, '../../verity-prototype.html');
const html = fs.readFileSync(filename, "utf8");
for (const m of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))
  new vm.Script(m[1]);
const script = html.match(
  /<script id="pagination-jump-behavior">([\s\S]*?)<\/script>/,
)[1];
const input = {
  value: "4",
  disabled: false,
  invalid: false,
  focus() {},
  setAttribute() {
    this.invalid = true;
  },
  removeAttribute() {
    this.invalid = false;
  },
};
const error = { textContent: "" },
  clicks = [];
const root = {
  dataset: {
    pageAction: "risk-page",
    pageCurrent: "1",
    pageMax: "4",
    pageDelta: "false",
  },
  querySelector: (selector) => (selector === "input" ? input : error),
  append() {},
};
const document = {
  createElement: () => ({
    dataset: {},
    click() {
      clicks.push({ ...this.dataset });
    },
    remove() {},
  }),
  querySelectorAll: () => [root],
};
const scope = { document };
vm.createContext(scope);
vm.runInContext(script, scope);
const control = { closest: () => root };
for (const value of ["", "0", "5", "-1", "1.5", "1e2"]) {
  input.value = value;
  scope.prototypePageJump(control);
  assert.equal(clicks.length, 0);
  assert.equal(input.invalid, true);
  assert.match(error.textContent, /1至4/);
}
input.value = "4";
scope.prototypePageJump(control);
assert.equal(clicks[0].action, "risk-page");
assert.equal(clicks[0].id, "4");
assert.equal(error.textContent, "");
assert.equal(input.invalid, false);
root.dataset.pageDelta = "true";
root.dataset.pageAction = "ci-page";
input.value = "3";
scope.prototypePageJump(control);
assert.equal(clicks[1].id, "2");
input.value = "1";
scope.prototypePageJump(control);
assert.equal(clicks.length, 2);
input.disabled = true;
input.value = "3";
scope.prototypePageJump(control);
assert.equal(clicks.length, 2);
assert.equal((html.match(/data-page-action=/g) || []).length, 8);
console.log(
  "PASS pagination jumps: syntax, page bounds, inline errors, absolute/delta routing, current page and disabled controls:",
  filename,
);
