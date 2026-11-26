const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test'),
  assert = require('node:assert/strict'),
  fs = require('node:fs'),
  path = require('node:path'),
  ts = require('typescript');
function harness(file, component, targetType, { riskTask, candidateDownload } = {}) {
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
  const wait = (url, signal, method) =>
    new Promise((resolve, reject) => reads.push({ url, signal, method, resolve, reject }));
  const code = {
    codeList: async () => ({ items: [old], has_more: false }),
    codeRequest: (url, parser, options) =>
      url.endsWith('/options')
        ? new Promise(() => {})
        : wait(url, options?.signal, options?.method),
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
    riskCatalog: () =>
      riskTask
        ? Promise.resolve({
            overview: {
              reports: 0,
              functions: 0,
              risks: 0,
              high: 0,
              medium: 0,
              low: 0,
              pending: 0,
            },
            reports: [],
            functions: [],
            items: [],
            total: 0,
            page: 1,
            pages: 1,
          })
        : new Promise(() => {}),
    riskAnalyses: async () => (riskTask ? [riskTask] : []),
    riskDetailRequest: (url, project, options) => wait(url, options?.signal),
    riskError: (e) => e.message,
  };
  function load(name) {
    if (cache.has(name)) return cache.get(name);
    const exported = {};
    cache.set(name, exported);
    const source = compileModule(fs.readFileSync(name, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    evaluateModule(
      source,
      (dep) => {
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
        if (dep === './api/http' && candidateDownload)
          return { ...value, apiDownload: (url, options) => wait(url, options?.signal, 'GET') };
        if (dep === './api/http' && riskTask)
          return {
            ...value,
            apiRequest: (url, options) => wait(url, options?.signal, options?.method),
          };
        if (dep === './codeAnalysisApi') return { ...value, ...code };
        if (dep === './caseAnalysisApi') return { ...value, ...review };
        if (dep === './changeAnalysisApi') return { ...value, ...changes };
        if (dep === './riskApi') return { ...value, ...risks };
        return value;
      },
      exported,
    );
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
      const view = workspace(props);
      while (effects.length) effects.shift()();
      return view;
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

function findButton(node, label) {
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = findButton(child, label);
      if (found) return found;
    }
  } else if (node?.props) {
    if (node.type === 'button' && node.props.children === label) return node;
    return findButton(node.props.children, label);
  }
}

test('failed code record exposes the saved candidate and revalidates through its own endpoint', async () => {
  const h = harness('CodeAnalysis.tsx', 'CodeAnalysis', 'task', { candidateDownload: true });
  try {
    h.render();
    await h.settle();
    const record = {
      id: 44,
      project_id: 7,
      title: '固定失败候选',
      actor_id: 2,
      created_at: '2026-10-14',
      status: 'FAILED',
      origin: 'AI',
      error_code: 'code_evidence_invalid',
      revision: 1,
      can_revalidate: true,
      candidate_available: true,
      handling: {},
      targets: ['BUG'],
      evidence_corrections: [],
    };
    h.reads.find(({ url }) => url.endsWith('/44')).resolve(record);
    await h.settle();
    const tree = h.render();
    const candidate = findButton(tree, 'AI候选原文');
    assert.ok(candidate);
    const originalDocument = global.document;
    const downloaded = [];
    global.document = {
      createElement: () => ({
        click() {
          downloaded.push(this.download);
        },
      }),
    };
    try {
      candidate.props.onClick();
      const request = h.reads.find(({ url }) => url.endsWith('/44/candidate'));
      assert.equal(request.method, 'GET');
      request.resolve(new Blob(['synthetic candidate']));
      await Promise.resolve();
      await Promise.resolve();
      assert.deepEqual(downloaded, ['code-analysis-44-ai-candidate.txt']);
    } finally {
      global.document = originalDocument;
    }
    const revalidate = findButton(h.render(), '重新校验候选');
    assert.ok(revalidate);
    revalidate.props.onClick();
    const request = h.reads.find(({ url }) => url.endsWith('/44/revalidate'));
    assert.equal(request.method, 'POST');
    request.resolve({ ...record, can_revalidate: false });
    await h.settle();
    assert.equal(findButton(h.render(), '重新校验候选'), undefined);
  } finally {
    h.close();
  }
});

test('saved requirement risk candidate is available for download and free revalidation', async () => {
  const riskTask = {
    id: 44,
    title: '固定需求失败候选',
    status: 'FAILED',
    report_id: null,
    candidate_available: true,
    can_revalidate: true,
    selections: [],
    created_at: '2026-10-14T00:00:00Z',
    created_by: '合成用户',
  };
  const h = harness('RiskReports.tsx', 'RiskReports', 'task', { riskTask });
  try {
    await h.settle();
    const view = h.render();
    assert.ok(findButton(view, '下载AI候选'));
    const revalidate = findButton(view, '重新校验候选（不调用AI）');
    assert.ok(revalidate);
    revalidate.props.onClick();
    const request = h.reads.find(({ url }) => url.endsWith('/risk-analyses/44/revalidate'));
    assert.equal(request.method, 'POST');
    request.resolve({});
    await h.settle();
  } finally {
    h.close();
  }
});

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
