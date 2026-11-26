const { compileModule, load: loadModule, evaluateModule } = require('./helpers/load.cjs');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { test } = require('node:test'),
  assert = require('node:assert/strict'),
  fs = require('node:fs'),
  path = require('node:path'),
  ts = require('typescript');
function load(name, overrides = {}) {
  const file = path.resolve(__dirname, '../src', name),
    exports = {};
  const code = compileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  evaluateModule(
    code,
    (n) =>
      overrides[n] ||
      (n.startsWith('.')
        ? load(
            path.relative(path.resolve(__dirname, '../src'), path.resolve(path.dirname(file), n)) +
              '.ts',
            overrides,
          )
        : require(n)),
    exports,
  );
  return exports;
}
function fixed() {
  return {
    id: 1,
    project_id: 7,
    title: '分析',
    mode: 'QUALITY',
    actor_id: 2,
    parent_id: null,
    status: 'COMPLETED',
    outcome: 'COMPLETE',
    revision: 1,
    error_code: '',
    created_at: '2026-10-14',
    updated_at: '2026-10-14',
    input: {
      type: 'CASE_REVIEW',
      request_id: 'uuid',
      materials: [],
      cases: [],
      focus: '',
      scope: {},
    },
    report: { findings: [], notes: [], checked_case_ids: [], complete: true },
    handling: {},
    manual: [],
    notice: '仅本次范围',
    attempts: [],
    ai_config: {},
    chat: [],
    applications: [],
  };
}
test('review parser keeps zero scope and immutable report separate from manual findings', () => {
  const api = load('caseAnalysisApi.ts', { './api/http': {} }),
    r = fixed();
  assert.equal(api.parseReview(r).input.cases.length, 0);
  assert.equal(api.allReviewFindings(r).length, 0);
  r.manual = [
    {
      key: 'M1',
      kind: 'QUESTION',
      title: '业务待确认',
      severity: '中',
      reason: '未知',
      description: '缺有效期',
      impact: '无法确定预期',
      suggestion: '业务确认',
      case_ids: [],
      fields: [],
      evidence: [],
    },
  ];
  assert.equal(api.allReviewFindings(r).length, 1);
  assert.equal(r.report.findings.length, 0);
  assert.throws(() => api.parseReviewSummary({ ...r, mode: 'GENERATE' }));
  assert.throws(() => api.parseReviewFinding({ ...r.manual[0], kind: 'UNKNOWN' }));
  assert.throws(() =>
    api.parseReview({ ...r, input: { type: 'CASE_GENERATION', materials: [], cases: [] } }),
  );
});
test('review requests use common transport with body and cancellation; failures propagate', async () => {
  const calls = [],
    controller = new AbortController(),
    api = load('caseAnalysisApi.ts', {
      './api/http': {
        apiRequest: async (url, options) => {
          calls.push({ url, options });
          return fixed();
        },
      },
    });
  const r = await api.reviewRequest(
    7,
    '/1/start',
    api.parseReview,
    { confirmed: true },
    controller.signal,
  );
  assert.equal(r.project_id, 7);
  assert.equal(calls[0].url, '/api/projects/7/case-analysis/1/start');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.signal, controller.signal);
  assert.deepEqual(JSON.parse(calls[0].options.body), { confirmed: true });
  await api.reviewRequest(7, '/1', api.parseReview);
  assert.equal(calls[1].options.method, 'GET');
  const failed = load('caseAnalysisApi.ts', {
    './api/http': {
      apiRequest: async () => {
        throw Error('unauthorized');
      },
    },
  });
  await assert.rejects(failed.reviewRequest(7, '/1', failed.parseReview), /unauthorized/);
});

test('review prose and design field labels use Chinese without changing raw reports or source text', () => {
  const api = load('caseAnalysisApi.ts', { './api/http': {} });
  assert.equal(
    api.reviewText('preconditions缺少订单状态，expected只写操作正常。'),
    '前置条件缺少订单状态，预期结果只写操作正常。',
  );
  assert.equal(
    api.reviewText('steps需写清顺序；data_requirements和cleanup待补。'),
    '操作步骤需写清顺序；测试数据要求和清理要求待补。',
  );
  assert.equal(api.reviewFieldName('case_type'), '用例类型');
  assert.equal(api.reviewFieldName('expected'), '预期结果');
  assert.equal(api.reviewFieldName('unrecognized'), '相关内容');
  assert.equal(api.reviewFieldName('constructor'), '相关内容');
  assert.equal(
    api.reviewText('Preconditions未说明角色，Expected不明确。'),
    '前置条件未说明角色，预期结果不明确。',
  );
  const identifiers =
    'expected_qty unexpected expectedGain expected.png /expected/module src/expected.ts';
  assert.equal(api.reviewText(identifiers), identifiers);
  const r = fixed();
  r.report.findings = [
    {
      key: 'F1',
      kind: 'QUALITY',
      title: 'expected不明确',
      severity: '中',
      reason: 'expected无法判断',
      description: 'preconditions未说明角色',
      impact: '无法按steps执行',
      suggestion: '补齐expected',
      case_ids: [],
      fields: ['preconditions', 'expected'],
      evidence: [{ source: 'M1', quote: '原文明确叫expected字段' }],
    },
  ];
  const raw = JSON.stringify(r);
  assert.equal(api.reviewText(r.report.findings[0].title), '预期结果不明确');
  assert.equal(JSON.stringify(r), raw);
  const file = path.resolve(__dirname, '../src/CaseAnalysis.tsx');
  const source = fs.readFileSync(file, 'utf8') + '\nexport { ReviewDetail };';
  const { outputText } = compileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  });
  const exported = {};
  evaluateModule(
    outputText,
    (name) => {
      if (name.endsWith('.css')) return {};
      if (name === './CaseDialog') {
        return {
          CaseDialog: ({ title, footer, sideControls, children }) =>
            React.createElement('section', null, title, sideControls, children, footer),
        };
      }
      if (!name.startsWith('.')) return require(name);
      const base = path.resolve(path.dirname(file), name);
      return loadModule(base + (fs.existsSync(base + '.ts') ? '.ts' : '.tsx'));
    },
    exported,
  );
  const finding = r.report.findings[0];
  finding.case_ids = [11];
  r.input.cases = [{ id: 11, number: 'C11', version: 1, title: '固定用例' }];
  r.input.materials = [
    {
      source_id: 'M1',
      name: '固定需求',
      version: '1',
      segments: [{ location: '§1', text: '原文明确叫expected字段' }],
    },
  ];
  const markup = renderToStaticMarkup(
    React.createElement(exported.ReviewDetail, {
      record: r,
      finding,
      sequence: [finding.key],
      busy: false,
      onClose() {},
      onSave() {},
      onNavigate() {},
      onDraft() {},
      onAsk() {},
    }),
  );
  assert.match(markup, /预期结果不明确/);
  assert.match(markup, /前置条件、预期结果/);
  assert.match(markup, /原文明确叫expected字段/);
  assert.match(markup, /class="change-dialog-footer review-dialog-footer"/);
  assert.match(markup, /form="reviewHandle"[^>]*>保存处理/);
});
test('formal route has no demo state and shares safe literal 14-column spreadsheet export', () => {
  const { CaseAnalysis } = loadModule(path.resolve(__dirname, '../src/CaseAnalysis.tsx'));
  const { MemoryRouter } = require('react-router-dom');
  const view = renderToStaticMarkup(
    React.createElement(
      MemoryRouter,
      null,
      React.createElement(CaseAnalysis, {
        project: { id: 7 },
        user: { id: 2 },
        onSessionEnd() {},
      }),
    ),
  );
  assert.match(view, /用例分析/);
  assert.doesNotMatch(view, /CR-DEMO|Review_001/);
  const exports = load('generationExport.ts', { './generationPage': {} }),
    d = Object.fromEntries(
      load('caseApi.ts', { './api/http': {} }).DESIGN_FIELDS.map((f) => [f, '']),
    );
  d.title = '=1+1';
  const blob = exports.caseDesignXlsx([d]);
  assert.equal(blob.type, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
  assert.ok(blob.size > 1000);
});

test('prototype workspace has an actual grid and every review dialog has themed form/footer styling', () => {
  const css = fs.readFileSync(path.resolve(__dirname, '../src/case-analysis.css'), 'utf8');
  const workspace = css.match(/\.case-review-page \.code-analysis-layout\s*\{([^}]+)\}/)[1];
  assert.match(workspace, /display:\s*grid/);
  assert.match(workspace, /grid-template-columns:\s*220px minmax\(0, 1fr\) 240px/);
  assert.match(workspace, /gap:\s*18px/);
  assert.match(css, /\.review-audit-layout\s*\{[^}]*flex-shrink:\s*0/);
  assert.match(css, /\.case-review-dialog \.review-dialog-footer\s*\{[^}]*display:\s*flex/);
  assert.match(css, /\.case-review-dialog \.field-label > textarea\s*\{/);
  assert.match(css, /\.case-review-dialog \.form-grid\s*\{[^}]*grid-template-columns:/);
});

test('new review labels use original selected/latest filenames for requirement and prototype files', async () => {
  const state = [],
    refs = [],
    prepared = [];
  let cursor = 0,
    refCursor = 0;
  const react = {
    useState(initial) {
      const i = cursor++;
      if (!(i in state)) state[i] = initial;
      return [
        state[i],
        (value) => {
          state[i] = typeof value === 'function' ? value(state[i]) : value;
        },
      ];
    },
    useRef(initial) {
      return (refs[refCursor++] ||= { current: initial });
    },
  };
  const code = compileModule(
    fs.readFileSync(path.resolve(__dirname, '../src/CaseAnalysisNew.tsx'), 'utf8'),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    },
  ).outputText;
  const exports = {},
    stubs = {
      react,
      './CaseDialog': { CaseDialog: 'dialog' },
      './Form': { Form: 'form' },
      './FormSelect': { FormSelect: 'themed-select' },
      './PageJump': { PageJump: 'page-jump' },
      './CaseGenerationNew': { GithubMaterial: 'github-material' },
      './PrototypeDirectoryFiles': { PrototypeDirectoryFiles: () => null },
      './PrototypeLinkPages': { PrototypeLinkPages: 'prototype-pages' },
    };
  evaluateModule(code, (name) => stubs[name] || require(name), exports);
  const props = {
    projectId: 7,
    prototypes: [],
    snapshot: { items: [], categories: [], revision: 1 },
    busy: false,
    error: '',
    onClose() {},
    onSessionEnd() {},
    async onPrepare(value) {
      prepared.push(value);
    },
    options: {
      materials: [
        {
          id: 8,
          name: '未命名资料',
          purpose: 'REQUIREMENT',
          kind: 'FILE',
          versions: [
            { id: 81, number: 1, filename: '旧需求.md' },
            { id: 83, number: 3, filename: '需求原文件.md' },
          ],
        },
        {
          id: 9,
          name: '未命名资料',
          purpose: 'PROTOTYPE',
          kind: 'FILE',
          versions: [{ id: 91, number: 1, filename: '原型原文件.png' }],
        },
        {
          id: 10,
          name: '门店端',
          purpose: 'PROTOTYPE',
          kind: 'GITHUB',
          commit: 'fixed-sha',
          versions: [],
        },
      ],
    },
  };
  function render() {
    cursor = refCursor = 0;
    const nodes = [];
    function walk(node) {
      if (Array.isArray(node)) return node.forEach(walk);
      if (!node || typeof node !== 'object') return;
      nodes.push(node);
      walk(node.props?.children);
    }
    walk(exports.CaseAnalysisNew(props));
    return nodes;
  }
  const labels = (nodes) =>
    nodes.filter((n) => n.props?.className === 'review-source-name').map((n) => n.props.children);
  let nodes = render();
  assert.deepEqual(labels(nodes), ['需求原文件.md', '原型原文件.png', '门店端']);
  nodes
    .filter((n) => n.type === 'input' && n.props.type === 'checkbox')[0]
    .props.onChange({ target: { checked: true } });
  nodes = render();
  const version = nodes.find((n) => n.type === 'themed-select' && n.props.label === '固定版本');
  assert.equal(version.props.value, '83');
  version.props.onChange('81');
  nodes = render();
  assert.deepEqual(labels(nodes), ['旧需求.md', '原型原文件.png', '门店端']);
  await nodes.find((n) => n.type === 'form').props.onSubmit({ preventDefault() {} });
  await Promise.resolve();
  assert.equal(prepared[0].materials[0].document_id, 8);
  assert.equal(prepared[0].materials[0].version, '81');
  nodes
    .filter((n) => n.type === 'input' && n.props.type === 'checkbox')[0]
    .props.onChange({ target: { checked: false } });
  assert.equal(labels(render())[0], '需求原文件.md');
});
