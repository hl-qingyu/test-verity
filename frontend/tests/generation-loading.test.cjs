const { test } = require('node:test'),
  assert = require('node:assert/strict'),
  fs = require('node:fs'),
  path = require('node:path'),
  ts = require('typescript');

function harness(mode = 'remote', pageCache) {
  const hooks = [],
    effects = [],
    timers = new Map(),
    reads = [],
    cache = new Map(),
    downloads = [];
  const actions = [];
  let cursor = 0,
    timerId = 0,
    tree,
    summaryReads = 0;
  const react = {
    useState(initial) {
      const i = cursor++;
      if (mode === 'export' && i === 19) initial = true;
      if (mode === 'export' && i === 20) initial = ['2', '1'];
      if (!hooks[i]) hooks[i] = { value: typeof initial === 'function' ? initial() : initial };
      return [
        hooks[i].value,
        (v) => {
          hooks[i].value = typeof v === 'function' ? v(hooks[i].value) : v;
        },
      ];
    },
    useRef(initial) {
      const i = cursor++;
      return (hooks[i] ||= { current: initial });
    },
    useId() {
      return `form-${cursor++}`;
    },
    useEffect(fn, deps) {
      const i = cursor++,
        old = hooks[i];
      if (!old || deps.some((d, n) => !Object.is(d, old.deps[n]))) {
        old?.cleanup?.();
        hooks[i] = { deps };
        effects.push(() => {
          hooks[i].cleanup = fn();
        });
      }
    },
  };
  const summaries = ['2', '1'].map((id) => ({
    id,
    projectId: 7,
    title: id,
    createdAt: '2026-10-13T12:00:00+08:00',
    mode: 'INITIAL',
    status: 'COMPLETED',
    serverRevision: 1,
    hasMaterials: true,
    active: false,
    refreshKey: id.repeat(64),
  }));
  const api = {
    generationBase: (id) => `/api/projects/${id}/case-generation`,
    generationSummaries: async (projectId, signal, page, runId) => {
      summaryReads++;
      if (runId)
        return {
          items: [{ ...structuredClone(summaries[0]), id: runId, refreshKey: runId.repeat(64) }],
          hasMore: false,
        };
      return { items: structuredClone(summaries), hasMore: false };
    },
    generationDetail: (project, id, signal) =>
      new Promise((resolve, reject) => reads.push({ project, id, signal, resolve, reject })),
    generationError: (e) => e.message,
    generationAction: async (project, route, body) => {
      actions.push({ route, body });
      const row = structuredClone(props.rows[0]);
      if (route.endsWith('/start')) {
        row.status = 'QUEUED';
        row.batches[0].status = 'QUEUED';
        row.batches[0].terminalAvailable = mode === 'start-cli';
      } else if (route.includes('/terminal/results/')) {
        row.status = 'COMPLETED';
        row.batches[0].status = 'FAILED';
        row.nativeRounds = [
          {
            id: 'a'.repeat(64),
            batchId: 10,
            batchRef: 'cli-a',
            timestamp: '2026-11-17T06:12:00Z',
            caseCount: 0,
            status: 'COMPLETED',
          },
        ];
      } else if (route.endsWith('/handling')) {
        row.handling.C1 = [
          { draft: body.draft, revision: 1, status: '待审阅', evidenceChecked: true },
        ];
      } else {
        row.handling.C1 = [{ ...row.handling.C1[0], status: '已应用' }];
        row.applications = [
          { id: 9, requestId: body.request_id, status: 'COMPLETED', items: [], error: '' },
        ];
      }
      return row;
    },
    generationApplyPreview: async (project, run, keys) => ({
      items: [
        {
          key: keys[0],
          kind: 'NEW',
          design: props.rows[0].suggestions[0].design,
          revision: 1,
          problem: '',
          matches: [],
          categoryId: 7,
        },
      ],
      keys,
      revision: 0,
    }),
  };
  function load(file) {
    if (cache.has(file)) return cache.get(file);
    const exports = {};
    cache.set(file, exports);
    const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    new Function('exports', 'require', code)(exports, (name) => {
      if (name === 'react') return react;
      if (name === './generationApi') return api;
      if (name === './generationRead')
        return { generationCaseSnapshot: async () => ({ items: [], categories: [], revision: 0 }) };
      if (name === './generationExport')
        return { downloadGeneration: (...args) => downloads.push(args) };
      if (name.endsWith('.css')) return {};
      if (!name.startsWith('.')) return require(name);
      const base = path.resolve(path.dirname(file), name);
      return load(base + (fs.existsSync(base + '.ts') ? '.ts' : '.tsx'));
    });
    return exports;
  }
  const { CaseGeneration, GenerationWorkspace } = load(
    path.resolve(__dirname, '../src/CaseGeneration.tsx'),
  );
  const full = (id) => ({
    id,
    projectId: 7,
    title: `完整记录${id}`,
    mode: 'INITIAL',
    status: 'COMPLETED',
    createdAt: summaries[0].createdAt,
    serverRevision: 1,
    origin: 'SERVER',
    outcome: 'COMPLETE',
    materials: [],
    suggestions: [],
    questions: [],
    handling: {},
    batches: [],
    failures: [],
    decisions: [],
    failureHistory: [],
    chatDrafts: {},
    limitations: [],
    caseScope: '',
    scope: '',
    focus: '',
    inputText: '{}',
    reportText: '{}',
    rawReports: [{}],
    cancelled: false,
  });
  const props = { project: { id: 7 }, user: { id: 3 }, onSessionEnd() {}, pageCache },
    remote = ['export', 'single', 'start-cli', 'start-api'].includes(mode)
      ? GenerationWorkspace
      : CaseGeneration(props).type;
  hooks.length = 0;
  cursor = 0;
  if (mode === 'target')
    props.overviewTarget = { id: 3, recordType: 'run', group: 'suggestions', state: 'PENDING' };
  if (mode === 'export') Object.assign(props, { rows: [full('2')], summaries, onChange() {} });
  if (mode === 'start-cli' || mode === 'start-api') {
    Object.assign(props, {
      rows: [
        {
          ...full('2'),
          status: 'PREPARED',
          ownerId: 3,
          outcome: '',
          rawReports: [],
          reportText: '',
          batches: [{ id: 9, key: 'B1', status: 'PREPARED', inputBytes: 100 }],
          aiPreview: { version: 1, call_mode: mode === 'start-cli' ? 'CODEX_EXEC' : 'API' },
        },
      ],
      onChange(rows) {
        props.rows = rows;
      },
    });
  }
  if (mode === 'single') {
    const design = load(path.resolve(__dirname, '../src/caseApi.ts')).blankDesign();
    Object.assign(design, { title: '本条用例', steps: '提交', expected: '成功' });
    Object.assign(props, {
      rows: [
        {
          ...full('2'),
          suggestions: [
            {
              key: 'C1',
              kind: 'NEW',
              design,
              function: '订单',
              functionRef: 'F1',
              caseId: null,
              baseVersion: null,
              blocked: false,
              evidence: [],
            },
          ],
        },
      ],
      onChange(rows) {
        props.rows = rows;
      },
    });
  }
  function render() {
    cursor = 0;
    tree = remote(props);
    while (effects.length) effects.shift()();
  }
  async function settle() {
    for (let n = 0; n < 4; n++) {
      await Promise.resolve();
      render();
    }
  }
  function workspace() {
    let found;
    function walk(node) {
      if (Array.isArray(node)) return node.forEach(walk);
      if (!node || typeof node !== 'object') return;
      if (node.type?.name === 'GenerationWorkspace') found = node.props;
      walk(node.props?.children);
    }
    walk(tree);
    return found;
  }
  const previousWindow = global.window;
  global.window = {
    setInterval: (fn) => {
      timers.set(++timerId, fn);
      return timerId;
    },
    clearInterval: (id) => timers.delete(id),
  };
  return {
    render,
    settle,
    workspace,
    reads,
    summaries,
    downloads,
    actions,
    component(name, matches = () => true) {
      let found;
      function walk(node) {
        if (Array.isArray(node)) return node.forEach(walk);
        if (!node || typeof node !== 'object') return;
        if (node.type?.name === name && matches(node.props)) found = node;
        walk(node.props?.children);
      }
      walk(tree);
      return found;
    },
    button(label) {
      let found;
      function walk(node) {
        if (Array.isArray(node)) return node.forEach(walk);
        if (!node || typeof node !== 'object') return;
        if (node.type === 'button' && node.props.children === label) found = node;
        walk(node.props?.children);
        walk(node.props?.footer);
      }
      walk(tree);
      return found;
    },
    tick: () => {
      for (const fn of [...timers.values()]) fn();
    },
    summaryReads: () => summaryReads,
    finish: (n, patch = {}) => reads[n].resolve({ ...full(reads[n].id), ...patch }),
    close() {
      hooks.forEach((h) => h?.cleanup?.());
      global.window = previousWindow;
    },
  };
}

test('native generation opens the existing history area and retains its cached terminal when returning to the report', async () => {
  for (const mode of ['start-cli', 'start-api']) {
    const h = harness(mode);
    try {
      h.render();
      assert.equal(h.button('CLI 工作区（试用）'), undefined);
      h.button('继续并开始本人AI生成').props.onClick();
      await h.settle();
      assert.equal(h.actions.length, 1);
      assert.equal(h.actions[0].route, '/2/start');
      const cached = h.component('GenerationCliWorkspace');
      if (mode === 'start-cli') {
        assert.equal(cached.props.runId, '2');
        assert.equal(cached.props.open, true);
        assert.equal(
          h.component('GenerationChat'),
          undefined,
          'native history must not create another API chat',
        );
        h.button('返回生成报告').props.onClick();
        await h.settle();
        assert.equal(h.component('GenerationCliWorkspace').key, cached.key);
        assert.equal(h.component('GenerationCliWorkspace').props.open, false);
        h.button('历史对话').props.onClick();
        await h.settle();
        assert.equal(h.component('GenerationCliWorkspace').props.open, true);
        assert.equal(h.actions.length, 1, 'navigation must not create or cancel model tasks');
      } else assert.equal(cached, undefined);
    } finally {
      h.close();
    }
  }
});

test('single confirmation stays above the same detail instance through cancel and direct application', async () => {
  const h = harness('single');
  try {
    h.render();
    h.component('GenerationTable').props.onDetail('C1');
    await h.settle();
    const detailKey = h.component('GenerationDetail').key;
    const review = () =>
      h.component('GenerationDetail').props.onSave(
        {
          draft: { title: '本条用例', steps: '提交', expected: '成功' },
          status: '待审阅',
          note: '',
          evidenceChecked: true,
          resolved: true,
          categoryId: 7,
        },
        0,
        'review',
      );
    review();
    await h.settle();
    await h.settle();
    assert.equal(h.actions.length, 1);
    assert.match(h.actions[0].route, /\/handling$/);
    assert.ok(h.component('GenerationSingleReview'));
    assert.ok(h.component('GenerationDetail'));
    assert.equal(h.component('GenerationDetail').key, detailKey);
    assert.equal(h.component('GenerationDetail').props.busy, true);
    assert.equal(h.component('GenerationDetail').props.confirmationOpen, true);
    assert.equal(h.component('GenerationReview'), undefined);
    h.component('GenerationSingleReview').props.onClose();
    await h.settle();
    assert.ok(h.component('GenerationDetail'));
    assert.equal(h.component('GenerationDetail').key, detailKey);
    assert.equal(h.component('GenerationDetail').props.busy, false);
    assert.equal(h.component('GenerationDetail').props.confirmationOpen, false);
    assert.equal(h.actions.length, 1);
    h.component('GenerationDetail').props.onSave(
      {
        draft: { title: '本条用例', steps: '提交', expected: '成功' },
        status: '待审阅',
        note: '',
        evidenceChecked: true,
        resolved: true,
        categoryId: 7,
      },
      1,
      'review',
    );
    await h.settle();
    await h.settle();
    const confirm = h.component('GenerationSingleReview');
    confirm.props.onSubmit([
      {
        key: 'C1',
        draft_revision: 1,
        action: 'apply',
        target_id: null,
        target_version: null,
        reason: '',
        category_mode: 'KEEP',
        category_id: null,
      },
    ]);
    await h.settle();
    await h.settle();
    assert.equal(h.actions.length, 3);
    assert.match(h.actions[2].route, /\/applications$/);
    assert.deepEqual(
      h.actions[2].body.items.map((i) => i.key),
      ['C1'],
    );
    assert.ok(h.component('GenerationDetail'));
    assert.equal(h.component('GenerationDetail').key, detailKey);
    assert.equal(h.component('GenerationApplicationResult'), undefined);
    assert.equal(h.component('GenerationDetail').props.record.handling.C1.at(-1).status, '已应用');
    confirm.props.onSubmit(h.actions[2].body.items);
    await h.settle();
    assert.equal(
      h.actions.length,
      3,
      'a retained confirmation cannot replay an already applied item',
    );
  } finally {
    h.close();
  }
});

test('entry reads summaries then only the selected detail; unchanged polls reuse full records', async () => {
  const h = harness();
  try {
    h.render();
    await h.settle();
    assert.equal(h.reads.length, 1);
    assert.equal(h.reads[0].id, '2');
    assert.equal(h.workspace().summaries.length, 2);
    assert.equal(h.workspace().detailLoading, true);
    h.finish(0);
    await h.settle();
    assert.equal(h.workspace().detailLoading, false);
    h.tick();
    await h.settle();
    assert.equal(h.summaryReads(), 2);
    assert.equal(h.reads.length, 1);
    h.workspace().onSelectRecord('1');
    await h.settle();
    assert.equal(h.reads.length, 2);
    assert.equal(h.reads[1].id, '1');
    h.finish(1);
    await h.settle();
    h.workspace().onSelectRecord('2');
    await h.settle();
    assert.equal(h.reads.length, 2);
    h.summaries[0].refreshKey = 'b'.repeat(64);
    h.tick();
    await h.settle();
    assert.equal(h.reads.length, 3);
    assert.equal(h.reads[2].id, '2');
  } finally {
    h.close();
  }
});

test('returning to generation restores the record and list range and reloads their data', async () => {
  const pageCache = { projectId: 7 };
  const first = harness('remote', pageCache);
  try {
    first.render();
    await first.settle();
    first.workspace().onSelectRecord('1');
    first.workspace().onMore();
    await first.settle();
  } finally {
    first.close();
  }

  const reopened = harness('remote', pageCache);
  try {
    reopened.render();
    assert.equal(reopened.workspace(), undefined);
    await reopened.settle();
    assert.equal(reopened.summaryReads(), 2);
    assert.equal(reopened.workspace().selectedRecordId, '1');
    assert.equal(reopened.reads[0].id, '1');
    assert.deepEqual(reopened.workspace().rows, []);
  } finally {
    reopened.close();
  }
});

test('overview entry fetches an older summary by identity and opens it instead of the first list row', async () => {
  const h = harness('target');
  try {
    h.render();
    await h.settle();
    assert.equal(h.reads[0].id, '3');
    assert.equal(h.workspace().selectedRecordId, '3');
    assert.equal(h.summaryReads(), 2);
    h.finish(0);
    await h.settle();
    assert.equal(h.workspace().rows[0].id, '3');
    assert.equal(h.workspace().overviewTarget.state, 'PENDING');
  } finally {
    h.close();
  }
});

test('switching cancels a slow detail and a late response cannot replace the selected record', async () => {
  const h = harness();
  try {
    h.render();
    await h.settle();
    h.workspace().onSelectRecord('1');
    await h.settle();
    assert.equal(h.reads[0].signal.aborted, true);
    h.finish(1);
    await h.settle();
    h.finish(0);
    await h.settle();
    assert.equal(h.workspace().selectedRecordId, '1');
    assert.deepEqual(
      h.workspace().rows.map((r) => r.id),
      ['1'],
    );
  } finally {
    h.close();
  }
});

test('combined export reads every selected full record including unopened history, and never downloads a partial result', async () => {
  for (const fail of [false, true]) {
    const h = harness('export');
    try {
      h.render();
      h.button('导出全部所选记录').props.onClick();
      assert.deepEqual(
        h.reads.map((r) => r.id),
        ['2', '1'],
      );
      assert.equal(h.downloads.length, 0);
      h.finish(0);
      if (fail) h.reads[1].reject(Error('读取失败'));
      else h.finish(1);
      await h.settle();
      assert.equal(h.downloads.length, fail ? 0 : 1);
      if (!fail) {
        assert.match(h.downloads[0][1], /完整记录2/);
        assert.match(h.downloads[0][1], /完整记录1/);
      } else assert.equal(h.button('导出全部所选记录').props.disabled, false);
    } finally {
      h.close();
    }
  }
});

test('saving a CLI round keeps the original conversation and reviews that round on request', async () => {
  const h = harness('start-cli');
  try {
    h.render();
    h.button('继续并开始本人AI生成').props.onClick();
    await h.settle();
    const native = h.component('GenerationCliWorkspace');
    assert.equal(native.props.open, true);
    assert.equal(await native.props.onSaveResult('a'.repeat(64), 'save-request'), true);
    await h.settle();
    assert.equal(h.actions[1].route, '/2/terminal/results/' + 'a'.repeat(64) + '/save');
    assert.deepEqual(h.actions[1].body, { request_id: 'save-request', confirmed: true });
    assert.equal(h.component('GenerationCliWorkspace').key, native.key);
    assert.equal(h.component('GenerationCliWorkspace').props.runId, '2');
    assert.equal(h.component('GenerationCliWorkspace').props.open, true);
    const roundFilter = () => h.component('FormSelect', (props) => props.label === '候选轮次');
    h.component('GenerationCliWorkspace').props.onClose();
    await h.settle();
    assert.equal(roundFilter().props.value, '');
    h.button('历史对话').props.onClick();
    await h.settle();
    h.component('GenerationCliWorkspace').props.onReviewResult('a'.repeat(64));
    await h.settle();
    assert.equal(h.component('GenerationCliWorkspace').props.open, false);
    assert.equal(roundFilter().props.value, 'a'.repeat(64));
    assert.ok(h.button('历史对话'));
    assert.equal(h.actions.filter((a) => a.route.endsWith('/start')).length, 1);
    assert.equal(h.actions.filter((a) => a.route.endsWith('/cancel')).length, 0);
  } finally {
    h.close();
  }
});
