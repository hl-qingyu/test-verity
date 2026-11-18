const { test } = require('node:test'),
  assert = require('node:assert/strict'),
  fs = require('node:fs'),
  path = require('node:path'),
  ts = require('typescript'),
  React = require('react'),
  { renderToStaticMarkup } = require('react-dom/server');
function load(file, overrides = {}, cache = new Map()) {
  const name = path.resolve(__dirname, '../src', file);
  if (cache.has(name)) return cache.get(name);
  const exports = {};
  cache.set(name, exports);
  const code = ts.transpileModule(fs.readFileSync(name, 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  new Function('exports', 'require', code)(exports, (dep) => {
    if (Object.hasOwn(overrides, dep)) return overrides[dep];
    if (dep.endsWith('.css')) return {};
    if (!dep.startsWith('.')) return require(dep);
    const base = path.resolve(path.dirname(name), dep);
    return load(
      path.relative(path.resolve(__dirname, '../src'), base) +
        (fs.existsSync(base + '.ts') ? '.ts' : '.tsx'),
      overrides,
      cache,
    );
  });
  return exports;
}
const api = load('acceptanceApi.ts');
function fixture(n = 12) {
  const metrics = Object.fromEntries(api.metricKeys.map((k) => [k, 0]));
  Object.assign(metrics, { records: 1, total: n, unreviewed: n });
  return {
    project_id: 7,
    module: 'code',
    record_id: 9,
    title: '固定分析记录',
    source_token: 'a'.repeat(64),
    revision: 0,
    stale: false,
    state: { items: {}, criteria: [], scope_reviewed: false, conclusion: 'UNREVIEWED', note: '' },
    items: Array.from({ length: n }, (_, i) => ({
      key: 'findings:C' + i,
      source_key: 'C' + i,
      group: 'findings',
      kind: null,
      title: '原始结论' + i,
      description: '原始说明 <script>不可执行</script>',
      suggestion: '核对原文',
      repair: true,
    })),
    metrics,
    history: [],
  };
}
test('acceptance API checks identities, metric arithmetic, canonical items and preserved cancellation', async () => {
  let response = fixture(),
    seen;
  const transport = load('acceptanceApi.ts', {
    './api/http': {
      apiRequest: async (url, options) => {
        seen = { url, options };
        return response;
      },
    },
  });
  const controller = new AbortController();
  assert.equal((await transport.readAcceptance(7, 'code', 9, controller.signal)).items.length, 12);
  assert.equal(seen.options.signal, controller.signal);
  assert.equal(seen.url, '/api/projects/7/analysis-acceptance/code/9');
  for (const patch of [
    { project_id: 8 },
    { module: 'changes' },
    { record_id: 10 },
    { metrics: { ...response.metrics, valid: 2 } },
    { items: [response.items[0], response.items[0]] },
    { state: { ...response.state, items: { foreign: { verdict: 'VALID' } } } },
  ])
    assert.throws(() => api.parseAcceptance({ ...response, ...patch }, 7, 'code', 9));
  const changed = structuredClone(response.state);
  changed.items['findings:C0'] = {
    verdict: 'INVALID',
    reason: 'FALSE_POSITIVE',
    evidence: 'INSUFFICIENT',
    usable: null,
    note: '原调用链证明误报',
  };
  await transport.saveAcceptance(response, changed, controller.signal);
  const body = JSON.parse(seen.options.body);
  assert.equal(seen.options.method, 'POST');
  assert.equal(body.revision, 0);
  assert.equal(body.source_token, response.source_token);
  assert.equal(body.state.items['findings:C0'].verdict, 'INVALID');
  assert.ok(!seen.options.body.includes('原始说明'));
  assert.equal(response.state.items['findings:C0'], undefined);
  response = {
    project_id: 7,
    modules: ['requirements', 'generate', 'coverage', 'code', 'changes'].map((module) => ({
      module,
      available: true,
      metrics: fixture().metrics,
    })),
  };
  assert.equal((await transport.readAcceptanceSummary(7, controller.signal)).length, 5);
  response.modules[0].available = false;
  response.modules[0].metrics = null;
  assert.equal((await transport.readAcceptanceSummary(7, controller.signal))[0].metrics, null);
  response.modules[0].metrics = {};
  await assert.rejects(transport.readAcceptanceSummary(7, controller.signal));
  response.modules[0] = { module: 'requirements', available: false, metrics: null };
  response.project_id = null;
  assert.equal((await transport.readAcceptanceSummary(null, controller.signal)).length, 5);
  assert.equal(seen.url, '/api/analysis-acceptance');
  assert.equal(seen.options.signal, controller.signal);
  await assert.rejects(transport.readAcceptanceSummary(7, controller.signal));
  response.project_id = 7;
  await assert.rejects(transport.readAcceptanceSummary(null, controller.signal));
});
test('metrics count recognition and dismissal separately from false positives', () => {
  const m = { ...fixture(10).metrics, valid: 2, invalid: 8, unreviewed: 0 };
  assert.equal(api.acceptanceValues(m, 'code').find((v) => v[0] === '人工认可率')[1], '20.0%');
  assert.equal(
    api.acceptanceValues(fixture().metrics, 'code').find((v) => v[0] === '已认可问题数')[1],
    '—',
  );
  const dismissed = { ...m, valid: 1, invalid: 0, dismissed: 2, unreviewed: 7 };
  assert.equal(
    api.acceptanceValues(dismissed, 'generate').find((v) => v[0] === '人工认可率')[1],
    '33.3%',
  );
  assert.equal(
    api.acceptanceValues(dismissed, 'generate').find((v) => v[0] === '人工处理进度')[1],
    '30.0%',
  );
  assert.equal(
    api
      .acceptanceValues({ ...fixture(1).metrics, unreviewed: 0, dismissed: 1 }, 'coverage')
      .find((v) => v[0] === '已认可问题数')[1],
    '0',
  );
  assert.equal(api.percent(0, 0), '—');
  assert.equal(api.percent(0, 3), '0.0%');
  assert.ok(api.acceptanceValues(m, 'generate').some((v) => v[0] === '用例采纳率'));
  assert.ok(!api.acceptanceValues(m, 'code').some((v) => v[0] === '用例采纳率'));
  assert.ok(api.acceptanceValues(m, 'changes').some((v) => v[0] === '回归建议可用率'));
});
function harness() {
  const hooks = [],
    effects = [],
    saved = [];
  let cursor = 0,
    request,
    closed = 0;
  const fake = {
    ...React,
    useState(initial) {
      const i = cursor++;
      if (!(i in hooks)) hooks[i] = { value: typeof initial === 'function' ? initial() : initial };
      return [
        hooks[i].value,
        (v) => (hooks[i].value = typeof v === 'function' ? v(hooks[i].value) : v),
      ];
    },
    useRef(initial) {
      return (hooks[cursor++] ||= { current: initial });
    },
    useId() {
      cursor++;
      return 'acceptance-form';
    },
    useEffect(fn) {
      cursor++;
      effects.push(fn);
    },
  };
  const { AcceptanceEditor } = load('AnalysisAcceptance.tsx', {
    react: fake,
    './CaseDialog': { CaseDialog: 'acceptance-dialog' },
    './Form': { Form: 'acceptance-form' },
    './FormSelect': { FormSelect: 'themed-select' },
    './PageJump': { PageJump: 'page-jump' },
    './acceptanceApi': {
      ...api,
      saveAcceptance: (d, value, signal) =>
        new Promise((resolve, reject) => {
          request = { d, value, signal, resolve, reject };
        }),
      acceptanceError: (e) => e.message,
    },
  });
  const data = fixture(),
    props = {
      data,
      onClose: () => closed++,
      onSaved: (d) => saved.push(d),
      onSessionEnd() {},
    };
  return {
    data,
    props,
    saved,
    get request() {
      return request;
    },
    get closed() {
      return closed;
    },
    render() {
      cursor = 0;
      const nodes = [];
      function walk(n) {
        if (Array.isArray(n)) return n.forEach(walk);
        if (!n || typeof n !== 'object') return;
        nodes.push(n);
        walk(n.props?.children);
        walk(n.props?.footer);
      }
      walk(AcceptanceEditor(props));
      return nodes;
    },
    async tick() {
      await Promise.resolve();
      await Promise.resolve();
    },
  };
}
test('optional checklist keeps scope drafts and failure protection without any second judgment form', async () => {
  const h = harness();
  let nodes = h.render();
  assert.ok(!nodes.some((n) => n.props?.label === '有效性结论'));
  assert.ok(!nodes.some((n) => n.type === 'button' && n.props.children === '逐条验收'));
  nodes.find((n) => n.type === 'button' && n.props.children === '添加遗漏或基准项').props.onClick();
  nodes = h.render();
  nodes
    .find((n) => n.type === 'input' && n.props.maxLength === 500)
    .props.onChange({ target: { value: '原范围遗漏' } });
  nodes = h.render();
  nodes
    .find((n) => n.type === 'textarea' && n.props.rows === 2)
    .props.onChange({ target: { value: '固定资料第2节' } });
  nodes = h.render();
  nodes.find((n) => n.type === 'acceptance-form').props.onSubmit({ preventDefault() {} });
  assert.equal(h.request.value.criteria[0].title, '原范围遗漏');
  assert.deepEqual(h.request.value.items, h.data.state.items);
  h.request.reject(Error('acceptance_use_detail'));
  await h.tick();
  nodes = h.render();
  assert.ok(
    nodes.some((n) => n.props?.role === 'alert' && n.props.children === 'acceptance_use_detail'),
  );
  nodes.find((n) => n.type === 'acceptance-dialog').props.onClose();
  nodes = h.render();
  assert.ok(nodes.some((n) => n.props?.title === '放弃未保存的清单修改？'));
  assert.equal(h.closed, 0);
  nodes.find((n) => n.type === 'button' && n.props.children === '继续编辑').props.onClick();
  nodes = h.render();
  nodes.find((n) => n.type === 'acceptance-form').props.onSubmit({ preventDefault() {} });
  h.request.resolve({ ...h.data, revision: 1, state: h.request.value });
  await h.tick();
  assert.equal(h.saved.length, 1);
});

test('project acceptance occupies its own panel and renders five distinct module summaries', () => {
  const groups = ['requirements', 'generate', 'coverage', 'code', 'changes'].map((module) => ({
    module,
    available: true,
    metrics: fixture(0).metrics,
  }));
  let index = 0;
  const { AcceptanceSummary } = load('AnalysisAcceptance.tsx', {
    react: {
      ...React,
      useState: (initial) => [
        index++ === 0 ? groups : typeof initial === 'function' ? initial() : initial,
        () => {},
      ],
    },
  });
  const html = renderToStaticMarkup(
    React.createElement(
      require('react-router-dom').MemoryRouter,
      null,
      React.createElement(AcceptanceSummary, { projectId: 7, onSessionEnd() {} }),
    ),
  );
  assert.match(html, /结果总览/);
  assert.equal((html.match(/class="panel aa-module"/g) || []).length, 5);
  assert.ok(!html.includes('NaN'));
  assert.match(html, /模块专属指标/);
  assert.ok(!html.includes('<details class="aa-special"'));
  for (const label of [
    '用例采纳率',
    '修订建议采纳率',
    '回归建议可用率',
    '重复建议数',
    '明确误报数',
  ])
    assert.ok(html.includes(label));
  assert.match(html, /指标定义与计算口径/);
  assert.ok(!html.includes('逐条验收'));
  for (const group of groups) {
    group.available = false;
    group.metrics = null;
  }
  index = 0;
  const unavailable = renderToStaticMarkup(
    React.createElement(AcceptanceSummary, {
      projectId: null,
      onSessionEnd() {},
    }),
  );
  assert.match(unavailable, /0\/5/);
  assert.ok(!unavailable.includes('<dd>0</dd>'));
});

test('scope list controls do not submit and zero-finding reports still require explicit scope review', () => {
  const h = harness();
  let nodes = h.render();
  const add = nodes.find((n) => n.type === 'button' && n.props.children === '添加遗漏或基准项');
  assert.equal(add.props.type, 'button');
  add.props.onClick();
  nodes = h.render();
  const remove = nodes.find((n) => n.type === 'button' && n.props.children === '移除此项');
  assert.equal(remove.props.type, 'button');
  assert.equal(h.request, undefined);
  remove.props.onClick();
  nodes = h.render();
  assert.equal(
    nodes.filter((n) => n.type === 'button' && n.props.children === '移除此项').length,
    0,
  );
  assert.ok(
    nodes.some(
      (n) => n.type === 'input' && n.props.type === 'checkbox' && n.props.checked === false,
    ),
  );
});

test('administrator page denies members and defaults to all projects including an empty platform', () => {
  const scopes = [];
  const { AIResultsAcceptance } = load('AIResultsAcceptance.tsx', {
    './AnalysisAcceptance': {
      AcceptanceSummary: ({ projectId }) => {
        scopes.push(projectId);
        return React.createElement('div', null, '受保护汇总');
      },
    },
  });
  const render = (role, projects) =>
    renderToStaticMarkup(
      React.createElement(AIResultsAcceptance, {
        user: { id: 1, platform_role: role },
        projects,
        projectsLoading: false,
        onSelectProject() {},
        onSessionEnd() {},
      }),
    );
  const denied = render('USER', [{ id: 7, name: '项目' }]);
  assert.match(denied, /无权访问/);
  assert.ok(!denied.includes('受保护汇总'));
  assert.equal(scopes.length, 0);
  assert.match(render('ADMIN', []), /全部项目汇总/);
  const allowed = render('ADMIN', [{ id: 7, name: '项目' }]);
  assert.match(allowed, /AI结果验收/);
  assert.match(allowed, /汇总范围/);
  assert.match(allowed, /受保护汇总/);
  assert.deepEqual(scopes, [null, null]);
});

test('page range selects a project without changing the global project until entering analysis', () => {
  let chosen;
  const effects = [];
  const { AIResultsAcceptance } = load('AIResultsAcceptance.tsx', {
    react: {
      ...React,
      useEffect: (effect) => effects.push(effect),
      useState(initial) {
        if (chosen === undefined) chosen = initial();
        return [
          chosen,
          (v) => {
            chosen = v;
          },
        ];
      },
    },
  });
  const props = {
    pageCache: new Map(),
    user: { id: 1, platform_role: 'ADMIN' },
    projects: [
      { id: 7, name: '项目甲' },
      { id: 8, name: '项目乙' },
    ],
    projectsLoading: false,
    onSelectProject() {
      throw Error('range must not change global selection');
    },
    onSessionEnd() {},
  };
  const tree = AIResultsAcceptance(props);
  const range = tree.props.children[1].props.children[0];
  assert.deepEqual(
    range.props.options.map((o) => o.value),
    ['all', '7', '8'],
  );
  range.props.onChange('8');
  const selected = AIResultsAcceptance(props);
  assert.equal(selected.props.children[2].props.projectId, 8);
  assert.equal(selected.props.children[2].props.onSelectProject, props.onSelectProject);
  effects.splice(0).forEach((effect) => effect());
  chosen = undefined;
  assert.equal(AIResultsAcceptance(props).props.children[2].props.projectId, 8);
  chosen = undefined;
  assert.equal(
    AIResultsAcceptance({ ...props, pageCache: new Map() }).props.children[2].props.projectId,
    null,
  );
  range.props.onChange('all');
  assert.equal(AIResultsAcceptance(props).props.children[2].props.projectId, null);
});

test('application navigation exposes the new menu only to administrators', () => {
  for (const role of ['USER', 'ADMIN']) {
    const project = { id: 7, name: '项目', identifier: 'QA' };
    const overrides = {
      './Auth': {
        useAuth: () => ({
          user: { id: 1, platform_role: role, display_name: '账号' },
          loading: false,
          updateUser() {},
        }),
      },
      './Projects': {
        useProjects: () => ({
          current: project,
          projects: [project],
          selected: 7,
          loading: false,
          error: '',
          setSelected() {},
          reload() {},
        }),
      },
      './Icon': { Icon: () => null },
    };
    for (const [file, name] of [
      ['Platform', 'Platform'],
      ['Documents', 'Documents'],
      ['Prototypes', 'Prototypes'],
      ['Cases', 'Cases'],
      ['RiskReports', 'RiskReports'],
      ['CodeAnalysis', 'CodeAnalysis'],
      ['ChangeAnalysis', 'ChangeAnalysis'],
      ['CaseGeneration', 'CaseGeneration'],
      ['CaseAnalysis', 'CaseAnalysis'],
      ['Skills', 'Skills'],
      ['ProjectOverview', 'ProjectOverview'],
      ['OverviewEntry', 'OverviewEntry'],
      ['RequirementChat', 'RequirementChat'],
      ['AIResultsAcceptance', 'AIResultsAcceptance'],
    ])
      overrides['./' + file] = { [name]: () => null };
    const { App } = load('App.tsx', overrides);
    const html = renderToStaticMarkup(
      React.createElement(
        require('react-router-dom').MemoryRouter,
        { initialEntries: ['/'] },
        React.createElement(App),
      ),
    );
    assert.equal(html.includes('aria-label="AI结果验收"'), role === 'ADMIN');
    assert.match(html, /aria-label="项目概览"/);
  }
});

test('summary removes already loaded metrics when administrator permission is revoked', async () => {
  const hooks = [],
    requests = [],
    effects = [];
  let cursor = 0;
  const fake = {
    ...React,
    useState(initial) {
      const i = cursor++;
      hooks[i] ??= { value: typeof initial === 'function' ? initial() : initial };
      return [
        hooks[i].value,
        (v) => (hooks[i].value = typeof v === 'function' ? v(hooks[i].value) : v),
      ];
    },
    useEffect(fn, deps) {
      const i = cursor++,
        old = hooks[i];
      if (!old || deps.some((d, n) => !Object.is(d, old.deps[n]))) {
        old?.cleanup?.();
        hooks[i] = { deps };
        effects.push(() => (hooks[i].cleanup = fn()));
      }
    },
  };
  const originalWindow = global.window;
  global.window = { addEventListener() {}, removeEventListener() {} };
  try {
    const { AcceptanceSummary } = load('AnalysisAcceptance.tsx', {
        react: fake,
        './acceptanceApi': {
          ...api,
          acceptanceError: (e) => e.message,
          readAcceptanceSummary: () =>
            new Promise((resolve, reject) => requests.push({ resolve, reject })),
        },
      }),
      end = () => {};
    const render = () => {
      cursor = 0;
      const tree = React.createElement(
        require('react-router-dom').MemoryRouter,
        null,
        AcceptanceSummary({ projectId: 7, onSessionEnd: end }),
      );
      while (effects.length) effects.shift()();
      return renderToStaticMarkup(tree);
    };
    render();
    requests[0].resolve(
      ['requirements', 'generate', 'coverage', 'code', 'changes'].map((module) => ({
        module,
        available: true,
        metrics: fixture().metrics,
      })),
    );
    await new Promise((resolve) => setImmediate(resolve));
    const loaded = render();
    assert.equal((loaded.match(/class="panel aa-module"/g) || []).length, 5);
    hooks[2].value++;
    render();
    requests.at(-1).reject(Error('admin_required'));
    await new Promise((resolve) => setImmediate(resolve));
    const denied = render();
    assert.match(denied, /admin_required/);
    assert.ok(!denied.includes('class="panel aa-module"'));
  } finally {
    hooks.forEach((h) => h?.cleanup?.());
    global.window = originalWindow;
  }
});
