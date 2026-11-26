const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const compiled = new Map();
function compileModule(source, options = {}) {
  const key = JSON.stringify([source, options]);
  if (!compiled.has(key)) compiled.set(key, ts.transpileModule(source, options));
  return compiled.get(key);
}

function evaluateModule(source, resolve, exports = {}) {
  new Function('require', 'exports', source)(resolve, exports);
  return exports;
}

function load(file, overrides = {}, modules = new Map()) {
  if (modules.has(file)) return modules.get(file);
  const exports = {};
  modules.set(file, exports);
  const { outputText } = compileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  });
  evaluateModule(
    outputText,
    (name) => {
      if (Object.hasOwn(overrides, name)) return overrides[name];
      if (name.endsWith('.css')) return {};
      if (!name.startsWith('.')) return require(name);
      const target = path.resolve(path.dirname(file), name);
      for (const extension of ['.ts', '.tsx']) {
        const candidate = target + extension;
        if (fs.existsSync(candidate)) return load(candidate, overrides, modules);
      }
      return require(target);
    },
    exports,
  );
  return exports;
}

module.exports = { compileModule, evaluateModule, load };
