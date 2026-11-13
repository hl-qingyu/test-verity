const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

function load(file, overrides = {}) {
  const name = path.resolve(__dirname, '../src', file),
    exports = {};
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
    if (dep.startsWith('.'))
      return load(
        path.relative(path.resolve(__dirname, '../src'), path.resolve(path.dirname(name), dep)) +
          '.ts',
        overrides,
      );
    return require(dep);
  });
  return exports;
}
function fixture(project = 7, filter = 'all') {
  return {
    project_id: project,
    project: { name: '真实项目摘要', identifier: 'QA', description: '' },
    as_of: '2026-10-14T10:00:00Z',
    filter,
    counts: {
      requirements: 1,
      prototypes: 2,
      cases: 3,
      queued: 1,
      running: 0,
    },
    attention: ['requirements', 'generate', 'coverage', 'code', 'changes'].map((module) => ({
      module,
      available: true,
      parts: [
        {
          group: module === 'generate' ? 'suggestions' : 'findings',
          state: 'PENDING',
          label: '待处理',
          count: 2,
        },
      ],
    })),
    recent: [
      {
        module: 'code',
        record_type: 'task',
        record_id: 99,
        title: '待处理的代码问题',
        status: 'COMPLETED',
        created_at: '2026-10-14T10:00:00Z',
        actor: '成员',
        imported: false,
        outcome: 'PARTIAL',
        application_failed: false,
      },
    ],
    unavailable: [],
  };
}
test('overview transport rejects foreign identities and invalid counts; links carry only validated record identity', async () => {
  let response = fixture(),
    seen;
  const api = load('overviewApi.ts', {
    './api/http': {
      apiRequest: async (url, options) => {
        seen = { url, options };
        return response;
      },
    },
  });
  const controller = new AbortController();
  assert.equal((await api.readOverview(7, 'all', controller.signal)).counts.cases, 3);
  assert.equal(seen.url, '/api/projects/7/overview?filter=all');
  assert.equal(seen.options.signal, controller.signal);
  assert.equal(seen.options.method, undefined);
  for (const patch of [
    { project_id: 8 },
    { filter: 'completed' },
    { counts: { ...response.counts, cases: -1 } },
    { recent: [{ ...response.recent[0], record_type: 'run' }] },
    { recent: Array(9).fill(response.recent[0]) },
  ])
    assert.throws(() => api.parseOverview({ ...response, ...patch }, 7, 'all'));
  const href = api.overviewHref(7, response.recent[0], { group: 'findings', state: 'PENDING' });
  assert.ok(href.startsWith('/code?'));
  assert.ok(!href.includes('代码问题'));
  assert.equal(new URLSearchParams(href.split('?')[1]).get('record'), '99');
  response = {
    project_id: 8,
    module: 'code',
    group: 'findings',
    state: 'PENDING',
    page: 1,
    total: 1,
    items: [],
  };
  await assert.rejects(
    api.readAttention(7, 'code', { group: 'findings', state: 'PENDING' }, 1, controller.signal),
    /overview_response_invalid/,
  );
  response = { ...response, project_id: 7, items: [fixture().recent[0]] };
  assert.equal(
    (
      await api.readAttention(
        7,
        'code',
        { group: 'findings', state: 'PENDING' },
        1,
        controller.signal,
      )
    ).items[0].record_id,
    99,
  );
  const partial = fixture();
  partial.unavailable = ['code'];
  partial.counts.queued = null;
  partial.counts.running = null;
  partial.attention[3].available = false;
  partial.attention[3].parts[0].count = null;
  assert.equal(api.parseOverview(partial, 7, 'all').counts.running, null);
  partial.attention[3].parts[0].count = 0;
  assert.throws(() => api.parseOverview(partial, 7, 'all'));
});
test('overview targets survive reload and reject another project, wrong module type, unsafe ids or unrelated filters', () => {
  const api = load('overviewApi.ts', { './api/http': {} });
  const { parseOverviewTarget } = load('OverviewEntry.tsx', { './overviewApi': api });
  const href = api.overviewHref(7, fixture().recent[0], { group: 'findings', state: 'PENDING' }),
    search = href.slice(href.indexOf('?'));
  assert.deepEqual(parseOverviewTarget(search, 7, 'code'), {
    id: 99,
    recordType: 'task',
    group: 'findings',
    state: 'PENDING',
  });
  assert.equal(parseOverviewTarget('', 7, 'code'), null);
  for (const [query, project, module] of [
    [search, 8, 'code'],
    [search, 7, 'coverage'],
    [search.replace('record=99', 'record=1e3'), 7, 'code'],
    [search.replace('findings', 'regressions'), 7, 'code'],
    [search.replace('state=PENDING', 'state=COMPLETED'), 7, 'code'],
  ])
    assert.throws(() => parseOverviewTarget(query, project, module));
  const cleared = new URLSearchParams(search);
  cleared.delete('group');
  cleared.delete('state');
  assert.equal(parseOverviewTarget('?' + cleared, 7, 'code').id, 99);
});

test('overview target waits for project selection to load before reporting a mismatch or mounting a business page', () => {
  const api = load('overviewApi.ts', { './api/http': {} }),
    search = '?overview=1&project=7&record=44&record_type=task';
  const { OverviewEntry } = load('OverviewEntry.tsx', {
    './overviewApi': api,
    'react-router-dom': {
      useLocation: () => ({ search, pathname: '/code' }),
      Link: ({ to, children }) => React.createElement('a', { href: to }, children),
    },
  });
  let mounted = 0;
  const child = () => {
    mounted++;
    return React.createElement('div', null, '业务记录');
  };
  const loading = renderToStaticMarkup(
    React.createElement(OverviewEntry, { module: 'code', projectLoading: true, children: child }),
  );
  assert.match(loading, /正在读取项目/);
  assert.equal(mounted, 0);
  const ready = renderToStaticMarkup(
    React.createElement(OverviewEntry, { module: 'code', projectId: 7, children: child }),
  );
  assert.match(ready, /业务记录/);
  assert.equal(mounted, 1);
  const denied = renderToStaticMarkup(
    React.createElement(OverviewEntry, { module: 'code', projectId: 8, children: child }),
  );
  assert.match(denied, /无法打开概览目标/);
  assert.equal(mounted, 1);
});

function harness() {
  const hooks = [],
    effects = [],
    timers = new Map(),
    requests = [],
    attention = [],
    navigation = [];
  let cursor = 0,
    timerId = 0,
    search = new URLSearchParams(),
    tree;
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
      if (!old || deps.some((d, n) => !Object.is(d, old.deps[n]))) {
        old?.cleanup?.();
        hooks[i] = { deps };
        effects.push(() => (hooks[i].cleanup = fn()));
      }
    },
  };
  const api = load('overviewApi.ts', { './api/http': {} });
  const component = load('ProjectOverview.tsx', {
    react,
    'react-router-dom': {
      Link: ({ to, children, ...props }) =>
        React.createElement('a', { ...props, href: to }, children),
      useNavigate: () => navigate,
      useSearchParams: () => [search, (v) => (search = new URLSearchParams(v))],
    },
    './overviewApi': {
      ...api,
      overviewError: (e) => e.message,
      readOverview: (project, filter, signal) =>
        new Promise((resolve, reject) =>
          requests.push({ project, filter, signal, resolve, reject }),
        ),
      readAttention: (project, module, part, page, signal) =>
        new Promise((resolve, reject) =>
          attention.push({ project, module, part, page, signal, resolve, reject }),
        ),
    },
    './Icon': { Icon: () => null },
    './CaseDialog': {
      CaseDialog: ({ children }) => React.createElement('div', { role: 'dialog' }, children),
    },
    './PageJump': { PageJump: () => null },
  }).ProjectOverview;
  const navigate = (url) => navigation.push(url),
    end = () => {};
  const project = { id: 7, name: '项目', identifier: 'QA', description: '' };
  return {
    requests,
    attention,
    navigation,
    timers,
    project,
    render() {
      cursor = 0;
      tree = component({ project, onSessionEnd: end });
      while (effects.length) effects.shift()();
      return tree;
    },
    html() {
      return renderToStaticMarkup(tree);
    },
    unmount() {
      hooks.forEach((h) => h.cleanup?.());
    },
    async tick() {
      await Promise.resolve();
      await Promise.resolve();
    },
    nodes() {
      const out = [];
      function walk(v) {
        if (!v || typeof v !== 'object') return;
        if (Array.isArray(v)) {
          v.forEach(walk);
          return;
        }
        out.push(v);
        walk(v.props?.children);
      }
      walk(tree);
      return out;
    },
    install() {
      const original = {
        window: global.window,
        document: global.document,
        setInterval: global.setInterval,
        clearInterval: global.clearInterval,
      };
      global.window = { addEventListener() {}, removeEventListener() {} };
      global.document = {
        visibilityState: 'visible',
        addEventListener() {},
        removeEventListener() {},
      };
      global.setInterval = (fn) => {
        timers.set(++timerId, fn);
        return timerId;
      };
      global.clearInterval = (id) => timers.delete(id);
      return () => {
        this.unmount();
        Object.assign(global, original);
      };
    },
  };
}
test('real overview renders four tabs, pending cards and partial results; status filter uses a fresh read', async () => {
  const h = harness(),
    restore = h.install();
  try {
    h.render();
    assert.equal(h.requests.length, 1);
    const initial = fixture();
    initial.recent.push({
      ...initial.recent[0],
      record_id: 100,
      status: 'FAILED',
      outcome: 'PARTIAL',
    });
    const fullTitle = '跨模块需求和代码一致性复核的完整长标题'.repeat(6);
    for (let i = 0; i < 6; i++)
      initial.recent.push({
        ...initial.recent[0],
        record_id: 101 + i,
        title: i === 0 ? fullTitle : `其他记录${i}`,
      });
    h.requests[0].resolve(initial);
    await h.tick();
    h.render();
    const html = h.html();
    assert.equal((html.match(/class="panel ov-stat"/g) || []).length, 4);
    assert.doesNotMatch(html, /用例采纳率|AI结果验收/);
    assert.equal((html.match(/<article class="ov-record"/g) || []).length, 8);
    assert.ok(html.includes(fullTitle));
    assert.match(html, /role="tabpanel"[^>]*tabindex="0"/);
    assert.match(html, /has-pending/);
    assert.match(html, /部分完成/);
    const failedCard = html.match(
      /<article class="ov-record" data-state="失败">([\s\S]*?)<\/article>/,
    );
    assert.ok(failedCard);
    assert.match(failedCard[1], /部分完成/);
    assert.match(html, /已完成/);
    assert.ok(!html.includes('原型状态演示'));
    const completed = h
      .nodes()
      .find((n) => n.props?.role === 'tab' && n.props?.children === '已完成');
    let scrolled = 0;
    h.nodes().find((n) => n.props?.id === 'overview-panel').props.ref.current = {
      scrollTo: ({ top }) => {
        assert.equal(top, 0);
        scrolled++;
      },
    };
    completed.props.onClick();
    assert.equal(scrolled, 1);
    h.render();
    assert.equal(h.requests.at(-1).filter, 'completed');
    assert.equal(h.requests[0].signal.aborted, true);
    h.requests.at(-1).resolve(fixture(7, 'completed'));
    await h.tick();
    h.render();
    assert.match(h.html(), /aria-selected="true"[^>]*>已完成/);
    assert.doesNotMatch(h.html(), /用例采纳率|AI结果验收/);
    const before = h.requests.length;
    [...h.timers.values()][0]();
    assert.equal(h.requests.length, before + 1);
  } finally {
    restore();
  }
});

test('overview has four basic cards and exposes no aggregate acceptance data or links', async () => {
  const h = harness(),
    restore = h.install();
  try {
    h.render();
    const value = fixture();
    value.counts.generation_candidates = 32;
    value.counts.generation_adopted = 1;
    h.requests[0].resolve(value);
    await h.tick();
    h.render();
    assert.equal((h.html().match(/class="panel ov-stat"/g) || []).length, 4);
    assert.doesNotMatch(h.html(), /用例采纳率|AI结果验收|已采纳/);
  } finally {
    restore();
  }
});

test('leaving overview aborts pending reads; unavailable counts remain unknown and permission failure clears old content', async () => {
  const h = harness(),
    restore = h.install();
  try {
    h.render();
    h.requests[0].resolve(fixture());
    await h.tick();
    h.render();
    const refresh = h.nodes().find((n) => n.type === 'button' && n.props?.children === '刷新');
    refresh.props.onClick();
    h.render();
    h.requests.at(-1).reject(Error('project_not_found'));
    await h.tick();
    h.render();
    assert.ok(!h.html().includes('待处理的代码问题'));
    h.unmount();
    assert.equal(h.requests.at(-1).signal.aborted, true);
  } finally {
    restore();
  }
});

test('attention chooser reads real pages and links the chosen historical identity without an AI or write request', async () => {
  const h = harness(),
    restore = h.install();
  try {
    h.render();
    h.requests[0].resolve(fixture());
    await h.tick();
    h.render();
    h.nodes()
      .filter((n) => n.type === 'button' && n.props?.className?.includes('ov-attention-chip'))[3]
      .props.onClick();
    h.render();
    assert.equal(h.attention[0].module, 'code');
    assert.equal(h.attention[0].page, 1);
    const record = fixture().recent[0];
    h.attention[0].resolve({
      project_id: 7,
      module: 'code',
      group: 'findings',
      state: 'PENDING',
      page: 1,
      total: 24,
      items: [record],
    });
    await h.tick();
    h.render();
    const dialog = h.nodes().find((n) => n.props?.title === '选择需要查看的记录');
    assert.ok(dialog);
    assert.ok(dialog.props.footer);
    const footer = dialog.props.footer;
    const footerNodes = [];
    function walk(v) {
      if (Array.isArray(v)) {
        v.forEach(walk);
        return;
      }
      if (!v || typeof v !== 'object') return;
      footerNodes.push(v);
      walk(v.props?.children);
    }
    walk(footer);
    footerNodes.find((n) => n.type === 'button' && n.props?.children === '下一页').props.onClick();
    h.render();
    assert.equal(h.attention.at(-1).page, 2);
    assert.equal(h.attention[0].signal.aborted, true);
    h.attention.at(-1).resolve({
      project_id: 7,
      module: 'code',
      group: 'findings',
      state: 'PENDING',
      page: 2,
      total: 24,
      items: [{ ...record, record_id: 44, title: '旧记录44' }],
    });
    await h.tick();
    h.render();
    assert.match(h.html(), /旧记录44/);
    assert.match(h.html(), /record=44/);
    assert.equal(h.navigation.length, 0);
  } finally {
    restore();
  }
});
