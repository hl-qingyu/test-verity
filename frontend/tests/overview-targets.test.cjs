const { test } = require('node:test'),
  assert = require('node:assert/strict'),
  fs = require('node:fs'),
  path = require('node:path'),
  ts = require('typescript');
function harness(file, component, targetType) {
  const hooks = [],
    effects = [],
    reads = [],
    cache = new Map();
  let cursor = 0;
  const react = {
    useState(initial) {
      const i = cursor++;
      hooks[i] ||= { value: typeof initial === 'function' ? initial() : initial };
      return [
        hooks[i].value,
        (v) => (hooks[i].value = typeof v === 'function' ? v(hooks[i].value) : v),
      ];
    },
    useRef(initial) {
      return (hooks[cursor++] ||= { current: initial });
    },
    useEffect(fn, deps) {
      const i = cursor++,
        old = hooks[i];
      if (!old || deps.some((v, n) => !Object.is(v, old.deps[n]))) {
        old?.cleanup?.();
        hooks[i] = { deps };
        effects.push(() => (hooks[i].cleanup = fn()));
      }
    },
    useCallback(fn) {
      cursor++;
      return fn;
    },
    useId() {
      return 'qa-' + cursor++;
    },
  };
  const original = {
    window: global.window,
    setInterval: global.setInterval,
    clearInterval: global.clearInterval,
  };
  global.window = { setInterval: () => 1, clearInterval() {} };
  global.setInterval = () => 1;
  global.clearInterval = () => {};
  const old = {
    id: 999,
    title: '另一条记录',
    mode: 'QUALITY',
    status: 'COMPLETED',
    project_id: 7,
    actor_id: 2,
    parent_id: null,
    revision: 1,
    error_code: '',
    created_at: '2026-10-14',
    updated_at: '2026-10-14',
  };
  const wait = (url, signal) =>
    new Promise((resolve, reject) => reads.push({ url, signal, resolve, reject }));
  const code = {
    codeList: async () => ({ items: [old], has_more: false }),
    codeRequest: (url, parser, options) =>
      url.endsWith('/options') ? new Promise(() => {}) : wait(url, options?.signal),
    codeError: (e) => e.message,
  };
  const review = {
    reviewRequest: (project, route, parser, body, signal) =>
      route.startsWith('?')
        ? Promise.resolve({ items: [old], has_more: false })
        : wait(route, signal),
    reviewError: (e) => e.message,
  };
  const changes = {
    changeListing: async () => ({
      items: [
        {
          ...old,
          id: '999',
          loaded: false,
          mode: 'CODE_CHANGE',
          pairs: [],
          scope: [],
          before: 'old',
          after: 'new',
          createdAt: old.created_at,
        },
      ],
      has_more: false,
    }),
    changeDetail: (url, project, options) => wait(url, options?.signal),
    changeError: (e) => e.message,
  };
  const risks = {
    riskListing: () => new Promise(() => {}),
    riskCatalog: () => new Promise(() => {}),
    riskAnalyses: async () => [],
    riskDetailRequest: (url, project, options) => wait(url, options?.signal),
    riskError: (e) => e.message,
  };
  function load(name) {
    if (cache.has(name)) return cache.get(name);
    const exported = {};
    cache.set(name, exported);
    const source = ts.transpileModule(fs.readFileSync(name, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    new Function('exports', 'require', source)(exported, (dep) => {
      if (dep === 'react') return react;
      if (dep === 'react-router-dom')
        return {
          ...require(dep),
          useSearchParams: () => [new URLSearchParams(), () => {}],
        };
      if (dep.endsWith('.css')) return {};
      if (!dep.startsWith('.')) return require(dep);
      const base = path.resolve(path.dirname(name), dep),
        resolved = base + (fs.existsSync(base + '.ts') ? '.ts' : '.tsx');
      const value = load(resolved);
      if (dep === './codeAnalysisApi') return { ...value, ...code };
      if (dep === './caseAnalysisApi') return { ...value, ...review };
      if (dep === './changeAnalysisApi') return { ...value, ...changes };
      if (dep === './riskApi') return { ...value, ...risks };
      return value;
    });
    return exported;
  }
  const exported = load(path.resolve(__dirname, '../src', file));
  const props = {
    project: { id: 7, name: '合成项目' },
    user: { id: 2 },
    onSessionEnd() {},
    overviewTarget: { id: 44, recordType: targetType, group: '', state: '' },
  };
  const entry = exported[component],
    workspace = entry(props).type;
  hooks.length = 0;
  cursor = 0;
  return {
    reads,
    render() {
      cursor = 0;
      workspace(props);
      while (effects.length) effects.shift()();
    },
    async settle() {
      for (let n = 0; n < 4; n++) {
        await Promise.resolve();
        this.render();
      }
    },
    close() {
      hooks.forEach((h) => h?.cleanup?.());
      Object.assign(global, original);
    },
  };
}
for (const [file, component, type] of [
  ['CodeAnalysis.tsx', 'CodeAnalysis', 'task'],
  ['CaseAnalysis.tsx', 'CaseAnalysis', 'run'],
  ['ChangeAnalysis.tsx', 'ChangeAnalysis', 'task'],
  ['RiskReports.tsx', 'RiskReports', 'report'],
]) {
  test(`${component} opens the explicit overview record even when the latest list only contains another record`, async () => {
    const h = harness(file, component, type);
    try {
      h.render();
      await h.settle();
      assert.ok(h.reads.some((r) => r.url.split('?')[0].endsWith('/44')));
      assert.ok(!h.reads.some((r) => r.url.split('?')[0].endsWith('/999')));
      h.reads[0].reject(Error('record_not_found'));
      await h.settle();
      assert.ok(!h.reads.some((r) => r.url.split('?')[0].endsWith('/999')));
    } finally {
      h.close();
    }
  });
}
