const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
function load(file, overrides = {}) {
  const code = compileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const exports = {};
  evaluateModule(
    code,
    (name) => {
      if (overrides[name]) return overrides[name];
      if (name.endsWith('.css')) return {};
      if (!name.startsWith('.')) return require(name);
      const base = path.resolve(path.dirname(file), name);
      return load(base + (fs.existsSync(base + '.ts') ? '.ts' : '.tsx'), overrides);
    },
    exports,
  );
  return exports;
}
const source = (name) => path.resolve(__dirname, '../src', name);
const api = load(source('changeAnalysisPage.ts'));

test('cancelled entry requests restart immediately and stale completion cannot unlock the new request', async () => {
  const slots = new Map(),
    effects = [],
    pending = [];
  let hook = 0;
  const hooks = {
    ...React,
    useEffect: (setup) => effects.push(setup),
    useRef: (value) => {
      const key = hook++;
      if (!slots.has(key)) slots.set(key, { current: value });
      return slots.get(key);
    },
    useState: (initial) => {
      const key = hook++;
      if (!slots.has(key)) slots.set(key, typeof initial === 'function' ? initial() : initial);
      return [
        slots.get(key),
        (next) => slots.set(key, typeof next === 'function' ? next(slots.get(key)) : next),
      ];
    },
  };
  const originalWindow = global.window;
  const browser = new EventTarget();
  global.window = browser;
  try {
    const liveApi = load(source('changeAnalysisApi.ts'));
    const { ChangeAnalysis } = load(source('ChangeAnalysis.tsx'), {
      react: hooks,
      './changeAnalysisApi': {
        ...liveApi,
        changeListing: (url, projectId, signal) =>
          new Promise((resolve, reject) => {
            pending.push({ url, projectId, signal, resolve, reject });
          }),
      },
    });
    const outer = ChangeAnalysis({ project: { id: 1 }, user: { id: 7 }, onSessionEnd: () => {} });
    hook = 0;
    slots.clear();
    outer.type(outer.props);
    const initialCleanup = effects.map((setup) => setup());
    assert.equal(pending.length, 1);
    initialCleanup.forEach((cleanup) => cleanup?.());
    const restartedCleanup = effects.map((setup) => setup());
    assert.equal(pending.length, 2, 'entry must not wait for the 3500ms poll');
    assert.equal(pending[0].signal.aborted, true);
    assert.equal(pending[1].signal.aborted, false);
    pending[0].reject(new DOMException('aborted', 'AbortError'));
    await new Promise(setImmediate);
    browser.dispatchEvent(new Event('focus'));
    assert.equal(pending.length, 2, 'old finally must not unlock the active request');
    const summary = {
      id: '4',
      updatedAt: 'fixed',
      revision: 1,
      can_retry: true,
      retry_preparation: true,
    };
    pending[1].resolve({ items: [summary], has_more: false });
    await new Promise(setImmediate);
    const unchangedRows = slots.get(0);
    browser.dispatchEvent(new Event('focus'));
    assert.equal(pending.length, 3);
    pending[2].resolve({ items: [{ ...summary }], has_more: false });
    await new Promise(setImmediate);
    assert.equal(slots.get(0), unchangedRows, 'unchanged polling must preserve loaded rows');
    browser.dispatchEvent(new Event('focus'));
    pending[3].resolve({ items: [{ ...summary, updatedAt: 'new', revision: 2 }], has_more: false });
    await new Promise(setImmediate);
    assert.notEqual(slots.get(0), unchangedRows);
    assert.equal(slots.get(0)[0].loaded, false, 'updated records must load their new detail');
    slots.set(0, [
      {
        ...summary,
        updatedAt: 'new',
        revision: 2,
        status: 'RUNNING',
        loaded: true,
        inputText: '{"snapshots":[1]}',
        pairs: ['fixed pair'],
        context: ['fixed source'],
      },
    ]);
    browser.dispatchEvent(new Event('focus'));
    pending[4].resolve({
      items: [
        {
          ...summary,
          updatedAt: 'progress',
          revision: 2,
          status: 'RUNNING',
          pairs: [],
          context: [],
        },
      ],
      has_more: false,
    });
    await new Promise(setImmediate);
    assert.equal(
      slots.get(0)[0].loaded,
      true,
      'batch progress must not redownload the full fixed input',
    );
    assert.deepEqual(slots.get(0)[0].pairs, ['fixed pair']);
    assert.deepEqual(slots.get(0)[0].context, ['fixed source']);
    restartedCleanup.forEach((cleanup) => cleanup?.());
  } finally {
    global.window = originalWindow;
  }
});

test('collapsed scopes defer thousands of file nodes and reveal the complete list on expansion', () => {
  let opened = false;
  const hooks = {
    ...React,
    useEffect: () => {},
    useRef: (value) => ({ current: value }),
    useState: (initial) => [
      typeof initial === 'boolean' ? opened : typeof initial === 'function' ? initial() : initial,
      (next) => {
        opened = next;
      },
    ],
  };
  const { ChangeAnalysis } = load(source('ChangeAnalysis.tsx'), { react: hooks });
  const paths = Array.from({ length: 3327 }, (_, i) => `src/file${i}.java`);
  const row = {
    id: '4',
    pairs: [{ name: 'source', before: 'old', after: 'new', update: '固定提交', scope: paths }],
    context: [],
    targets: [],
    status: 'FAILED',
    changes: [],
    impacts: [],
    regressions: [],
    handling: {},
  };
  function nodes(node) {
    if (!node || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(nodes);
    return [node, ...nodes(node.props?.children)];
  }
  const Outer = ChangeAnalysis({
    project: { id: 1 },
    user: { id: 7 },
    rows: [row],
    onSessionEnd: () => {},
  });
  const workspace = Outer.type(Outer.props);
  const scope = nodes(workspace).find((node) => node.type?.name === 'ChangeScope');
  const files = nodes(scope.type(scope.props)).find((node) => node.type?.name === 'SelectedFiles');
  const collapsed = files.type(files.props);
  assert.equal(nodes(collapsed).filter((node) => node.type === 'p').length, 0);
  assert.match(renderToStaticMarkup(collapsed), /3327/);
  collapsed.props.onToggle({ currentTarget: { open: true } });
  const expanded = files.type(files.props);
  assert.equal(nodes(expanded).filter((node) => node.type === 'p').length, paths.length);
  assert.match(renderToStaticMarkup(expanded), /src\/file3326.java/);
});
const html = fs.readFileSync(
  path.resolve(__dirname, '../../docs/prototypes/verity-requirement-risk-review.html'),
  'utf8',
);
const examples = html.slice(
  html.indexOf('function changeExampleRecords(){'),
  html.indexOf('\nfunction changeRecords()'),
);
const sample = vm.runInNewContext(
  `const clone=x=>JSON.parse(JSON.stringify(x));${examples};JSON.stringify(changeExampleRecords()[0]);`,
);
const demo = JSON.parse(sample);
function payload() {
  return {
    input: {
      contract_version: 1,
      analysis_type: 'CHANGE_IMPACT',
      request_id: 'example-1',
      mode: demo.mode,
      comparison_pairs: [
        {
          name: 'server',
          before: demo.before,
          after: demo.after,
          update: demo.update,
          scope: demo.scope,
        },
      ],
      targets: demo.targets,
      context: demo.context,
      focus: '',
    },
    report: {
      contract_version: 1,
      analysis_type: 'CHANGE_IMPACT',
      request_id: 'example-1',
      changes: demo.changes,
      risks: demo.impacts,
      regression_scope: demo.regressions,
    },
  };
}
function record() {
  const p = payload();
  return {
    origin: 'PREVIEW',
    projectId: 1,
    mode: p.input.mode,
    pairs: p.input.comparison_pairs,
    targets: p.input.targets.map((t) => t.name),
    context: p.input.context,
    focus: p.input.focus || '',
    changes: p.report.changes,
    impacts: p.report.risks,
    regressions: p.report.regression_scope,
    handling: {},
    chatDraft: '',
    inputText: JSON.stringify(p.input),
    reportText: JSON.stringify(p.report),
    id: 'record-1',
    title: '核销变化',
    createdAt: '2026-10-08T00:00:00Z',
  };
}

test('page preflight rejects missing target-side code, same versions and unconfirmed scope', () => {
  const pair = {
    name: 'server',
    before: 'old',
    after: 'new',
    scope: ['Service.java'],
    kind: 'BACKEND',
    targetFiles: 1,
  };
  const check = (pairs, targets = ['代码Bug', '前后端一致性'], confirmed = true) =>
    api.changeScopeError('CODE_CHANGE', pairs, targets, confirmed, true);
  assert.match(check([pair]), /缺一端/);
  assert.match(check([pair, { ...pair, kind: 'FLUTTER', targetFiles: 0 }]), /缺一端/);
  assert.equal(check([pair, { ...pair, kind: 'WEB' }]), '');
  assert.match(check([{ ...pair, before: 'new' }], ['代码Bug']), /版本相同/);
  assert.match(check([pair], ['代码Bug'], false), /确认/);
  assert.match(
    api.changeScopeError('CODE_CHANGE', [pair], ['需求符合性'], true, false),
    /固定版本/,
  );
  assert.equal(
    api.changeScopeError('CODE_CHANGE', [pair], ['代码Bug', '需求符合性'], true, false),
    '',
  );
});

test('change list excludes unchanged items without mutating the original report export', () => {
  const r = record(),
    fixed = r.reportText;
  r.changes = [...r.changes, { ...r.changes[0], key: 'KEEP-1', kind: '旧规则保留' }];
  assert.equal(api.changeItems(r, 'changes').length, 3);
  assert.equal(r.reportText, fixed);
});

test('React page keeps reviewed layout, escapes fixed content and exposes persisted personal-AI state', () => {
  const { ChangeAnalysis } = load(source('ChangeAnalysis.tsx'));
  const props = {
    project: { id: 1, name: '项目' },
    user: { id: 7, display_name: '测试', platform_role: 'USER' },
    onChange: () => {},
    onSessionEnd: () => {},
  };
  const empty = renderToStaticMarkup(React.createElement(ChangeAnalysis, { ...props, rows: [] }));
  assert.match(empty, /新建变更分析/);
  assert.match(empty, /导入分析结果/);
  assert.match(empty, /历史对话/);
  assert.match(empty, /code-analysis-workspace/);
  const r = { ...record(), origin: 'IMPORT', status: 'COMPLETED', loaded: true, structured: {} };
  r.changes[0].title = '<img src=x onerror=alert(1)>';
  const preview = renderToStaticMarkup(
    React.createElement(ChangeAnalysis, { ...props, rows: [r] }),
  );
  assert.match(preview, /&lt;img/);
  assert.ok(!preview.includes('<img src=x'));
  assert.match(preview, /role="tablist"/);
  assert.match(preview, /已完成/);
  const draft = renderToStaticMarkup(
    React.createElement(ChangeAnalysis, {
      ...props,
      rows: [
        {
          ...r,
          origin: 'AI',
          status: 'QUEUED',
          loaded: true,
          changes: [],
          impacts: [],
          regressions: [],
        },
      ],
    }),
  );
  assert.match(draft, /后台任务尚未完成/);
  assert.ok(!draft.includes('<strong>0</strong>'));
  const { ChangeAnalysis: KeyedChangeAnalysis } = load(source('ChangeAnalysis.tsx'), {
    react: { ...React, useState: (initial) => [initial, () => {}] },
  });
  const key = (project, user) =>
    KeyedChangeAnalysis({ project: { id: project }, user: { id: user } }).key;
  assert.equal(key(1, 7), key(1, 7));
  assert.notEqual(key(1, 7), key(2, 7));
  assert.notEqual(key(1, 7), key(1, 8));
});

test('failed preparation shows retry and explains original-scope preparation without replacing history', () => {
  const { ChangeAnalysis } = load(source('ChangeAnalysis.tsx'));
  const row = {
    ...record(),
    origin: 'AI',
    status: 'FAILED',
    loaded: true,
    can_retry: true,
    retry_preparation: true,
    changes: [],
    impacts: [],
    regressions: [],
  };
  const props = {
    project: { id: 1, name: '项目' },
    user: { id: 7 },
    onSessionEnd: () => {},
    rows: [row],
  };
  const html = renderToStaticMarkup(React.createElement(ChangeAnalysis, props));
  assert.match(html, />重试<\/button>/);
  assert.match(html, /沿用原选择重新准备双侧输入/);
  assert.match(html, /使用你的当前AI配置/);
  assert.match(html, /原失败记录保留/);
  const fixed = renderToStaticMarkup(
    React.createElement(ChangeAnalysis, {
      ...props,
      rows: [{ ...row, retry_preparation: false }],
    }),
  );
  assert.match(fixed, /沿用已固定输入重试/);
  const queued = renderToStaticMarkup(
    React.createElement(ChangeAnalysis, {
      ...props,
      rows: [{ ...row, status: 'QUEUED', can_retry: false }],
    }),
  );
  assert.doesNotMatch(queued, />重试<\/button>/);
});

test('legacy batch progress remains readable while retry uses the complete fixed input', async () => {
  const input = JSON.parse(
    fs.readFileSync(
      path.resolve(__dirname, '../../skill/change-impact/examples/code-input.json'),
      'utf8',
    ),
  );
  const details = {
    id: 41,
    project_id: 1,
    actor_id: 7,
    title: '分批计划',
    mode: 'CODE_CHANGE',
    targets: ['BUG'],
    focus: '',
    status: 'PREPARED',
    error_code: '',
    revision: 1,
    origin: 'AI',
    created_at: 'fixed',
    updated_at: 'fixed',
    input,
    report: {},
    handling: {},
    batches: {
      total: 2,
      completed: 0,
      failed: 0,
      batches: [
        { id: 1, status: 'QUEUED', error_code: '', input_bytes: 1000, files: ['First.py'] },
        { id: 2, status: 'QUEUED', error_code: '', input_bytes: 2000, files: ['Second.py'] },
      ],
    },
  };
  const calls = [];
  const live = load(source('changeAnalysisApi.ts'), {
    './api/http': {
      apiRequest: async (url, options) => {
        calls.push({ url, options });
        return details;
      },
    },
  });
  const parsed = live.parseChangeDetail(details, 1);
  assert.equal(parsed.batches.total, 2);
  assert.throws(() =>
    live.parseChangeDetail({ ...details, batches: { ...details.batches, completed: 1 } }, 1),
  );
  await live.changeDetail('/api/projects/1/change-analysis/41/retry', 1, {
    method: 'POST',
    body: JSON.stringify({ request_id: 'retry-fixed-input' }),
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.method, 'POST');
  const { ChangeAnalysis } = load(source('ChangeAnalysis.tsx'));
  const props = { project: { id: 1 }, user: { id: 7 }, onSessionEnd: () => {} };
  const prepared = renderToStaticMarkup(
    React.createElement(ChangeAnalysis, { ...props, rows: [parsed] }),
  );
  assert.match(prepared, /历史分批进度/);
  assert.match(prepared, /历史批次，仅供查看/);
  assert.doesNotMatch(prepared, /开始分批分析/);
  const partial = renderToStaticMarkup(
    React.createElement(ChangeAnalysis, {
      ...props,
      rows: [
        {
          ...parsed,
          status: 'COMPLETED',
          can_retry: true,
          batches: { ...parsed.batches, completed: 1, failed: 1 },
        },
      ],
    }),
  );
  assert.match(partial, /部分批次失败/);
  assert.match(partial, /完整输入重新分析（1次调用）/);
  assert.match(partial, /原分批成果和人工处理保留在原记录/);
  assert.doesNotMatch(partial, /仅执行未完成批次/);
});

test('association plan validates stages, dependencies and chargeable calls while keeping legacy fields optional', async () => {
  const input = JSON.parse(
    fs.readFileSync(
      path.resolve(__dirname, '../../skill/change-impact/examples/code-input.json'),
      'utf8',
    ),
  );
  const details = {
    id: 41,
    project_id: 1,
    actor_id: 7,
    title: '关联计划',
    mode: 'CODE_CHANGE',
    targets: ['BUG'],
    focus: '',
    status: 'PREPARED',
    error_code: '',
    revision: 1,
    origin: 'AI',
    created_at: 'fixed',
    updated_at: 'fixed',
    input,
    report: {},
    handling: {},
    batches: {
      version: 2,
      total: 3,
      completed: 0,
      failed: 1,
      planned_calls: 2,
      remaining_calls: 2,
      review_batches: 1,
      batches: [
        {
          id: 1,
          status: 'QUEUED',
          error_code: '',
          input_bytes: 1000,
          files: ['Controller.java', 'Service.java'],
          kind: 'ANALYSIS',
          depends_on: [],
          blocked_targets: [],
          callable: true,
        },
        {
          id: 2,
          status: 'QUEUED',
          error_code: 'change_batch_dependencies_pending',
          input_bytes: 2000,
          files: ['Service.java', 'Mapper.java'],
          kind: 'INTEGRATION',
          depends_on: [1],
          blocked_targets: [],
          callable: true,
          oversized: true,
        },
        {
          id: 3,
          status: 'FAILED',
          error_code: 'change_batch_pairing_unavailable',
          input_bytes: 900,
          files: ['Unmatched.java'],
          kind: 'ANALYSIS',
          depends_on: [],
          blocked_targets: ['FRONTEND_BACKEND_MISMATCH'],
          callable: false,
          blocking_reason: '缺少 /orders 实际消费端。',
        },
      ],
    },
  };
  const calls = [];
  const live = load(source('changeAnalysisApi.ts'), {
    './api/http': {
      apiRequest: async (url, options) => {
        calls.push({ url, options });
        return details;
      },
    },
  });
  const parsed = live.parseChangeDetail(details, 1);
  assert.equal(parsed.batches.remaining_calls, 2);
  assert.equal(parsed.batches.batches[2].callable, false);
  assert.equal(parsed.batches.batches[1].kind, 'INTEGRATION');
  for (const invalid of [
    { ...details.batches, planned_calls: 3 },
    { ...details.batches, remaining_calls: 1 },
    { ...details.batches, review_batches: 0 },
    { ...details.batches, version: 3 },
    ...[
      { kind: 'UNKNOWN' },
      { callable: 'false' },
      { oversized: 1 },
      { depends_on: [1] },
      { depends_on: [99] },
      { depends_on: [2, 2] },
      { blocked_targets: ['UNKNOWN'] },
    ].map((bad) => ({
      ...details.batches,
      batches: [{ ...details.batches.batches[0], ...bad }, ...details.batches.batches.slice(1)],
    })),
  ])
    assert.throws(
      () => live.parseChangeDetail({ ...details, batches: invalid }, 1),
      /change_response_invalid/,
    );
  const legacy = {
    ...details,
    batches: {
      version: null,
      total: 1,
      completed: 0,
      failed: 0,
      planned_calls: null,
      remaining_calls: null,
      review_batches: null,
      batches: [
        {
          id: 1,
          status: 'QUEUED',
          error_code: '',
          input_bytes: 1000,
          files: ['First.py'],
          kind: null,
          depends_on: null,
          blocked_targets: null,
          callable: null,
          oversized: null,
          blocking_reason: null,
        },
      ],
    },
  };
  assert.equal(live.parseChangeDetail(legacy, 1).batches.version, undefined);
  await live.changeDetail('/api/projects/1/change-analysis/41/retry', 1, {
    method: 'POST',
    body: JSON.stringify({ request_id: 'retry-fixed-input' }),
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.method, 'POST');
  const { ChangeAnalysis } = load(source('ChangeAnalysis.tsx'));
  const props = { project: { id: 1 }, user: { id: 7 }, onSessionEnd: () => {} };
  const html = renderToStaticMarkup(
    React.createElement(ChangeAnalysis, { ...props, rows: [parsed] }),
  );
  assert.match(html, /历史分批进度/);
  assert.doesNotMatch(html, /开始分批分析/);
  assert.match(html, /文件分析/);
  assert.match(html, /关联复核/);
  assert.match(html, /前置批次：1/);
  assert.match(html, /等待前置批次，未调用AI/);
  assert.match(html, /依据未配对，未调用AI/);
  assert.match(html, /原完整关联证据包超过当时单批建议大小，正文未裁剪/);
  assert.match(html, /缺少 \/orders 实际消费端/);
  const old = renderToStaticMarkup(
    React.createElement(ChangeAnalysis, {
      ...props,
      rows: [{ ...parsed, status: 'CANCELLED', can_retry: true, retry_replan: true }],
    }),
  );
  assert.match(old, /完整输入重新分析（1次调用）/);
  assert.match(old, /原分批成果和人工处理保留在原记录/);
  assert.doesNotMatch(old, /仅执行未完成批次/);
  const blocked = renderToStaticMarkup(
    React.createElement(ChangeAnalysis, {
      ...props,
      rows: [
        {
          ...parsed,
          status: 'COMPLETED',
          targetResults: [
            { name: '代码Bug', status: 'BLOCKED', note: '仅本批固定范围，关联证据尚未复核。' },
          ],
        },
      ],
    }),
  );
  assert.match(blocked, /依据不足／未执行/);
  assert.match(blocked, /仅本批固定范围，关联证据尚未复核/);
});

test('legacy V2 full-input retry creates one request and never continues a saved batch plan', async () => {
  const slots = new Map(),
    calls = [];
  let hook = 0;
  const hooks = {
    ...React,
    useEffect: () => {},
    useRef: (value) => ({ current: value }),
    useState: (initial) => {
      const key = hook++;
      if (!slots.has(key)) slots.set(key, typeof initial === 'function' ? initial() : initial);
      return [
        slots.get(key),
        (next) => slots.set(key, typeof next === 'function' ? next(slots.get(key)) : next),
      ];
    },
  };
  const row = {
    ...record(),
    origin: 'AI',
    status: 'CANCELLED',
    loaded: true,
    can_retry: true,
    retry_replan: true,
    batches: {
      version: 2,
      total: 2,
      completed: 1,
      failed: 1,
      batches: [
        { id: 1, status: 'COMPLETED', files: ['First.py'], input_bytes: 1000, error_code: '' },
        {
          id: 2,
          status: 'FAILED',
          files: ['Second.py'],
          input_bytes: 2000,
          error_code: 'ai_gateway_timeout',
        },
      ],
    },
  };
  const liveApi = load(source('changeAnalysisApi.ts'));
  const { ChangeAnalysis } = load(source('ChangeAnalysis.tsx'), {
    react: hooks,
    './changeAnalysisApi': {
      ...liveApi,
      changeDetail: async (url, projectId, options) => {
        calls.push({ url, projectId, options });
        return {
          ...row,
          id: 'new-full-input',
          status: 'QUEUED',
          batches: undefined,
          can_retry: false,
        };
      },
    },
  });
  const outer = ChangeAnalysis({
    project: { id: 1 },
    user: { id: 7 },
    rows: [row],
    onSessionEnd: () => {},
  });
  hook = 0;
  slots.clear();
  const tree = outer.type(outer.props);
  function nodes(node) {
    if (!node || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(nodes);
    return [node, ...nodes(node.props?.children)];
  }
  const buttons = nodes(tree).filter((n) => n.type === 'button');
  assert.ok(!buttons.some((button) => String(button.props.children).includes('开始分批分析')));
  const retry = buttons.find((button) => button.props.children === '完整输入重新分析（1次调用）');
  assert.ok(retry);
  await retry.props.onClick();
  await new Promise(setImmediate);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, `/api/projects/1/change-analysis/${row.id}/retry`);
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(Object.keys(JSON.parse(calls[0].options.body)), ['request_id']);
  assert.match(
    liveApi.changeError(new Error('change_full_input_required'), () =>
      assert.fail('no session end'),
    ),
    /完整输入重新分析.*一次新的AI请求/,
  );
});

test('page actions paginate and open the selected record independent conversation', () => {
  const r = { ...record(), origin: 'IMPORT', status: 'COMPLETED', loaded: true, structured: {} },
    values = new Map();
  let hook = 0;
  const hooks = {
    ...React,
    useEffect: () => {},
    useRef: (value) => ({ current: value }),
    useState: (initial) => {
      const key = hook++;
      if (!values.has(key)) values.set(key, typeof initial === 'function' ? initial() : initial);
      return [
        values.get(key),
        (next) => values.set(key, typeof next === 'function' ? next(values.get(key)) : next),
      ];
    },
  };
  const { ChangeAnalysis } = load(source('ChangeAnalysis.tsx'), { react: hooks });
  const props = {
    project: { id: 1 },
    user: { id: 7 },
    rows: [r],
    onChange: () => {},
    onSessionEnd: () => {},
  };
  function render() {
    hook = 0;
    const outer = ChangeAnalysis(props);
    return outer.type(outer.props);
  }
  function elements(node) {
    if (!node || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(elements);
    return [node, ...elements(node.props?.children)];
  }
  let tree = render(),
    nodes = elements(tree);
  nodes.find((x) => x.props?.id === 'change-tab-regressions').props.onClick();
  tree = render();
  nodes = elements(tree);
  assert.equal(nodes.filter((x) => x.type === 'article').length, 10);
  nodes.find((x) => x.type === 'button' && x.props.children === '下一页').props.onClick();
  nodes = elements(render());
  assert.equal(nodes.filter((x) => x.type === 'article').length, 2);
  nodes.find((x) => x.type === 'button' && x.props.children === '历史对话').props.onClick();
  nodes = elements(render());
  const conversation = nodes.find((x) => x.type?.name === 'ChangeAnalysisChat');
  assert.equal(conversation.props.record.id, r.id);
  assert.equal(conversation.props.findingKey, '');
  assert.equal(conversation.props.record.reportText, r.reportText);
});

test('new dialog keeps prototype section order and external submit footer bound to the validated form', () => {
  const { ChangeAnalysisNew } = load(source('ChangeAnalysisNew.tsx'));
  const markup = renderToStaticMarkup(
    React.createElement(ChangeAnalysisNew, {
      projectId: 1,
      user: { id: 7 },
      options: { materials: [], repositories: [], local_sources: [], connections: [] },
      onClose: () => {},
      onCreate: () => {},
      onSessionEnd: () => {},
    }),
  );
  const formId = markup.match(/<form[^>]*id="([^"]+)"/)[1];
  assert.ok(markup.includes(`form="${formId}"`));
  assert.ok(markup.indexOf('change-dialog-footer') > markup.indexOf('</form>'));
  assert.ok(markup.indexOf('变更方式') < markup.indexOf('change-analysis-targets'));
  assert.ok(markup.indexOf('change-analysis-targets') < markup.indexOf('资料配对'));
  assert.ok(markup.indexOf('补充依据与固定引用') < markup.indexOf('补充关注点'));
  assert.match(markup, /指定当前代码快照/);
  assert.match(markup, /现有用例/);
  assert.match(markup, /历史报告与人工结论快照/);
  assert.match(markup, /所选资料将发送至你的AI服务/);
  assert.doesNotMatch(markup, /先准备分批计划|每批单独计费/);
  assert.ok(!markup.includes('<select'));
  const css = fs.readFileSync(source('change-analysis.css'), 'utf8');
  assert.match(
    css,
    /\.change-analysis-page \.code-analysis-overview[^}]*background: var\(--soft\)/s,
  );
  assert.match(css, /\.change-result-tabs button[^}]*border-radius: 0/s);
  assert.match(css, /\.change-dialog-footer[^}]*flex-shrink: 0/s);
  assert.match(css, /max-width: 680px/);
});

test('one selected document exposes old/new versions with distinct defaults and explicit supplement pairing', () => {
  const material = {
    id: 12,
    name: '未命名资料',
    kind: 'FILE',
    purpose: 'REQUIREMENT',
    versions: [
      { id: 21, number: 1, filename: '核销需求.md' },
      { id: 22, number: 2, filename: '核销补充.md' },
    ],
  };
  const supplement = {
    id: 13,
    name: '未命名资料',
    kind: 'FILE',
    purpose: 'REQUIREMENT',
    versions: [{ id: 31, number: 1, filename: '门店补充.md' }],
  };
  const values = new Map();
  let hook = 0;
  const hooks = {
    ...React,
    useEffect: () => {},
    useRef: (value) => ({ current: value }),
    useId: () => 'version-test',
    useState: (initial) => {
      const key = hook++;
      if (!values.has(key)) values.set(key, typeof initial === 'function' ? initial() : initial);
      return [
        values.get(key),
        (next) => values.set(key, typeof next === 'function' ? next(values.get(key)) : next),
      ];
    },
  };
  const { ChangeAnalysisNew } = load(source('ChangeAnalysisNew.tsx'), { react: hooks });
  const props = {
    projectId: 1,
    user: { id: 7 },
    options: {
      materials: [material, supplement],
      repositories: [],
      local_sources: [],
      connections: [],
    },
    onClose: () => {},
    onCreate: () => {},
    onSessionEnd: () => {},
  };
  function render() {
    hook = 0;
    return ChangeAnalysisNew(props);
  }
  function nodes(node) {
    if (!node || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(nodes);
    return [node, ...nodes(node.props?.children)];
  }
  function versions(tree) {
    return nodes(tree).filter(
      (x) => typeof x.type === 'function' && ['旧基准', '新目标'].includes(x.props.label),
    );
  }
  function row(tree, index = 0) {
    return nodes(tree).filter((x) => x.props?.className === 'change-version-row')[index];
  }
  let tree = render();
  assert.equal(versions(tree).length, 0);
  nodes(row(tree))
    .find((x) => x.type === 'input')
    .props.onChange({ target: { checked: true } });
  tree = render();
  assert.equal(versions(tree).find((x) => x.props.label === '旧基准').props.value, '21');
  assert.equal(versions(tree).find((x) => x.props.label === '新目标').props.value, '22');
  versions(tree)[0].props.onChange('22');
  tree = render();
  assert.ok(
    nodes(tree).some(
      (x) => x.props?.role === 'alert' && x.props.children === '旧基准与新目标不能是同一个版本。',
    ),
  );
  versions(tree)[0].props.onChange('21');
  tree = render();
  nodes(row(tree, 1))
    .find((x) => x.type === 'input')
    .props.onChange({ target: { checked: true } });
  tree = render();
  assert.equal(versions(tree).at(-2).props.value, '');
  assert.equal(versions(tree).at(-1).props.value, '31');
  nodes(row(tree, 1))
    .find((x) => x.type === 'input')
    .props.onChange({ target: { checked: false } });
  tree = render();
  assert.equal(versions(tree).length, 2);
  const contextRow = nodes(tree).find((x) => x.props?.className === 'change-material-row');
  nodes(contextRow)
    .find((x) => x.type === 'input')
    .props.onChange({ target: { checked: true } });
  tree = render();
  const contextVersion = nodes(tree).find(
    (x) => typeof x.type === 'function' && x.props.label === '固定版本',
  );
  assert.match(contextVersion.props.value, /12:22/);
  assert.ok(!contextVersion.props.options.some((x) => x.label === '不带入'));
  nodes(tree)
    .find((x) => x.type === 'button' && x.props.children === '添加补充文件配对')
    .props.onClick();
  tree = render();
  const supplementRow = () =>
    nodes(tree).find((x) => x.props?.className === 'evidence change-supplement-pair');
  const checks = () => nodes(supplementRow()).filter((x) => x.type === 'input');
  checks()[0].props.onChange({ target: { checked: true } });
  tree = render();
  checks()[3].props.onChange({ target: { checked: true } });
  tree = render();
  assert.equal(
    nodes(supplementRow()).find((x) => x.props?.label === '旧基准版本').props.value,
    '22',
  );
  assert.equal(
    nodes(supplementRow()).find((x) => x.props?.label === '补充文件版本').props.value,
    '31',
  );
  checks()[2].props.onChange({ target: { checked: true } });
  tree = render();
  assert.ok(
    nodes(tree).some(
      (x) =>
        x.props?.role === 'alert' &&
        x.props.children === '请选择不同文件；同一资料使用旧、新版本对比。',
    ),
  );
  const { ChangeAnalysisNew: RealNew } = load(source('ChangeAnalysisNew.tsx'));
  const markup = renderToStaticMarkup(React.createElement(RealNew, props));
  assert.ok(markup.includes('核销补充.md'));
  assert.ok(!markup.includes('未命名资料'));
  assert.ok(!markup.includes('不带入'));
  assert.ok(!markup.includes('选择需求／原型文件'));
});

test('prototype mode separates GitHub commits from link baselines and rejects URL-only old material', () => {
  const { linkBaseline, ChangePrototypeSources } = load(source('ChangePrototype.tsx'));
  const linkSource = { id: 3, kind: 'LINK', url: 'https://prototype.geekuat.com/p/Example/' };
  const material = {
    source_id: 'S1',
    origin: 'PROTOTYPE',
    kind: 'LINK',
    snapshot_ref: 'a'.repeat(64),
    read_state: 'PARTIAL',
    segments: [{ location: '订单详情 · HTML原文', text: '<p>旧规则</p>' }],
  };
  const report = {
    bindings: [
      {
        source_id: 'S1',
        document_id: 3,
        kind: 'LINK',
        purpose: 'PROTOTYPE',
        deleted: false,
        url: linkSource.url,
      },
    ],
    input: { materials: [material] },
  };
  assert.equal(linkBaseline(report, linkSource), material);
  assert.throws(
    () =>
      linkBaseline(
        {
          ...report,
          input: { materials: [{ ...material, read_state: 'NOT_LOADED', segments: [] }] },
        },
        linkSource,
      ),
    /旧基准/,
  );
  assert.throws(
    () =>
      linkBaseline(
        { ...report, input: { materials: [{ ...material, segments: [{ text: '   ' }] }] } },
        linkSource,
      ),
    /旧基准/,
  );
  assert.throws(
    () => linkBaseline(report, { ...linkSource, url: linkSource.url + 'changed' }),
    /旧基准/,
  );
  assert.throws(
    () => linkBaseline({ ...report, bindings: [{ ...report.bindings[0], deleted: true }] }, source),
    /旧基准/,
  );
  const markup = renderToStaticMarkup(
    React.createElement(ChangePrototypeSources, {
      projectId: 1,
      onChange: () => {},
      onSessionEnd: () => {},
    }),
  );
  assert.match(markup, /GitHub 原型/);
  assert.match(markup, /原型链接/);
  assert.ok(!markup.includes('旧基准文件'));
  assert.ok(Object.hasOwn(api.changeModes, 'PROTOTYPE_CHANGE'));
  const pair = {
    name: '原型',
    before: '报告 #1 · 固定旧正文',
    after: '新目录（正文未固定）',
    update: '链接',
    scope: ['新：page-1.html'],
  };
  assert.equal(
    api.changeScopeError('PROTOTYPE_CHANGE', [pair], ['原型行为变化与功能影响'], true, false),
    '',
  );
  assert.match(
    api.changeScopeError(
      'PROTOTYPE_CHANGE',
      [{ ...pair, before: '' }],
      ['原型行为变化与功能影响'],
      true,
      false,
    ),
    /新旧/,
  );
});
