const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const React = require('react');
const { MemoryRouter } = require('react-router-dom');
const { renderToStaticMarkup } = require('react-dom/server');
function load(file, react = React, overrides = {}) {
  const source = fs
    .readFileSync(file, 'utf8')
    .replace(/^function StartAnalysis\(/m, 'export function StartAnalysis(')
    .replace(/^function ScopeDialog\(/m, 'export function ScopeDialog(')
    .replace(/^function RiskCoverage\(/m, 'export function RiskCoverage(')
    .replace(/^function CatalogRiskDialog\(/m, 'export function CatalogRiskDialog(');
  const code = compileModule(source, {
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
      if (name === 'react') return react;
      if (name.endsWith('.css')) return {};
      if (!name.startsWith('.')) return require(name);
      const base = path.resolve(path.dirname(file), name);
      return load(base + (fs.existsSync(base + '.ts') ? '.ts' : '.tsx'), react, overrides);
    },
    exports,
  );
  return exports;
}
const api = load(path.resolve(__dirname, '../src/riskApi.ts'));
const input = JSON.parse(
  fs.readFileSync(
    path.resolve(__dirname, '../../skill/requirement-analysis/examples/input.json'),
    'utf8',
  ),
);
const report = JSON.parse(
  fs.readFileSync(
    path.resolve(__dirname, '../../skill/requirement-analysis/examples/output.json'),
    'utf8',
  ),
);
const version = {
  id: 3,
  document_id: 2,
  number: 1,
  filename: '需求.txt',
  extension: 'txt',
  size: 30,
  sha256: 'a'.repeat(64),
  created_at: '2026-09-15T00:00:00Z',
  created_by: '成员',
};
const detail = {
  id: 5,
  project_id: 1,
  revision: 1,
  title: '报告',
  created_by: '成员',
  created_at: '2026-09-15T00:00:00Z',
  updated_at: '2026-09-15T00:00:00Z',
  input,
  report,
  bindings: [
    {
      source_id: 'D1',
      document_id: 2,
      version,
      name: '需求',
      kind: 'FILE',
      purpose: 'REQUIREMENT',
      deleted: false,
      url: null,
      branch: null,
      commit: null,
    },
  ],
  handling: [],
  manual_risks: [],
  duplicate: false,
};
const queuedTask = (project, init) => ({
  ...JSON.parse(init.body),
  id: 17,
  project_id: project,
  status: 'QUEUED',
  error_code: '',
  report_id: null,
  created_by: '成员',
  can_cancel: true,
  candidate_available: false,
  can_revalidate: false,
  function_risk_corrections: [],
  created_at: detail.created_at,
  updated_at: detail.updated_at,
});

test('analysis task candidate state and validation path stay visible', async () => {
  const original = global.fetch;
  try {
    global.fetch = async () =>
      new Response(
        JSON.stringify({
          items: [
            {
              id: 16,
              project_id: 1,
              request_id: crypto.randomUUID(),
              retry_of: null,
              title: '门店订货',
              focus: '',
              selections: [],
              status: 'FAILED',
              error_code: 'risk_report_invalid|risks[1]|inconsistent_reference',
              report_id: null,
              created_by: '成员',
              can_cancel: false,
              candidate_available: true,
              can_revalidate: true,
              function_risk_corrections: [],
              created_at: detail.created_at,
              updated_at: detail.updated_at,
            },
          ],
        }),
        { status: 200 },
      );
    const [task] = await api.riskAnalyses('/risk-analyses', new AbortController().signal);
    assert.equal(task.candidate_available, true);
    assert.equal(task.can_revalidate, true);
    assert.match(api.riskTaskFailure(task.error_code), /risks\[1\].*功能与风险关联不一致/);
    assert.match(
      api.riskTaskFailure(
        'risk_report_invalid|report.risks[6].source_comparison.known_facts|string_type',
      ),
      /known_facts.*应为文本/,
    );
  } finally {
    global.fetch = original;
  }
});

test('v3 responses preserve evidence, reject old contracts and prevent foreign-project results', async () => {
  assert.equal(api.parseRiskDetail(detail, 1).report.risks[0].key, 'R1');
  assert.throws(() => api.parseRiskDetail(detail, 2));
  assert.throws(() => api.parseRiskReport({ ...report, contract_version: 2 }));
  assert.throws(() =>
    api.parseRiskReport({ ...report, risks: [{ ...report.risks[0], severity: 'constructor' }] }),
  );
  assert.throws(() =>
    api.parseRiskDetail(
      { ...detail, bindings: [{ ...detail.bindings[0], version: { ...version, document_id: 9 } }] },
      1,
    ),
  );
  const read = await api.readRiskFile(new File([JSON.stringify(report)], 'risk-report.json'));
  assert.equal(api.parseRiskReport(read.data).request_id, input.request_id);
  await assert.rejects(api.readRiskFile(new File(['```json\n{}\n```'], 'report.json')));
});

test('AI review warnings survive parsing and appear beside fixed report scope', () => {
  const warning = {
    path: 'risks[0].evidence',
    code: 'evidence_excerpt_mismatch',
    source_id: 'D1',
    segment_id: 's1',
    risk_key: 'R1',
  };
  const parsed = api.parseRiskDetail({ ...detail, review_warnings: [warning] }, 1);
  assert.deepEqual(parsed.review_warnings, [warning]);
  const { ScopeDialog } = load(path.resolve(__dirname, '../src/RiskReports.tsx'));
  const markup = renderToStaticMarkup(
    React.createElement(ScopeDialog, {
      detail: parsed,
      onClose() {},
    }),
  );
  assert.match(markup, /1 处 AI 依据\/覆盖待人工核对/);
  assert.match(markup, /R1.*摘录未匹配固定原文/);
});

test('v4 scope renders evidence reference labels and v3 keeps its coverage reasons', () => {
  const { ScopeDialog, RiskCoverage } = load(path.resolve(__dirname, '../src/RiskReports.tsx'));
  const render = (Component, value) =>
    renderToStaticMarkup(React.createElement(Component, { detail: value, onClose() {} }));
  const candidate = structuredClone(detail);
  candidate.report.contract_version = 4;
  candidate.input.contract_version = 4;
  const material = candidate.input.materials[0];
  material.segments.push({ ...material.segments[0], segment_id: 's2', location: '默认排序' });
  const segments = candidate.report.coverage[0].segments;
  segments[0].disposition = 'REFERENCED';
  delete segments[0].reason;
  segments.push({
    segment_id: 's2',
    disposition: 'UNREFERENCED',
    function_keys: [],
    risk_keys: [],
  });
  const parsed = api.parseRiskDetail(candidate, 1);
  const { coverage, outcome, ...raw } = candidate.report;
  assert.equal(api.parseRiskImportReport(raw).contract_version, 4);
  assert.throws(() => api.parseRiskReport(raw));
  assert.throws(() => api.parseRiskImportReport({ ...raw, coverage }));
  assert.equal(api.parseRiskImportReport({ ...raw, coverage, outcome }).contract_version, 4);
  const markup = render(ScopeDialog, parsed);
  assert.match(markup, /默认排序 · 未被引用/);
  assert.match(markup, / · 被引用/);
  assert.match(markup, /<details class="evidence">/);
  const legacy = render(RiskCoverage, api.parseRiskDetail(detail, 1));
  assert.match(legacy, /已审查/);
  assert.ok(legacy.includes(report.coverage[0].segments[0].reason));
  assert.throws(() => api.parseRiskDetail({ ...candidate, input }, 1));
  segments[0].disposition = 'REVIEWED';
  assert.throws(() => api.parseRiskDetail(candidate, 1));
});

test('catalog risk groups coverage warnings and shows the actual function mismatch', () => {
  const warnings = ['s1', 's2'].map((segment_id, index) => ({
    path: `coverage[0].segments[${index}]`,
    code: 'invalid_coverage',
    source_id: 'D1',
    segment_id,
    risk_key: 'R1',
  }));
  const expanded = {
    ...detail,
    input: {
      materials: [
        {
          ...input.materials[0],
          segments: [
            input.materials[0].segments[0],
            {
              ...input.materials[0].segments[0],
              segment_id: 's2',
              location: '合成需求 · 商品详情',
            },
          ],
        },
      ],
    },
    report: {
      ...report,
      functions: [...report.functions, { ...report.functions[0], key: 'F2', name: '商品详情' }],
      coverage: [
        {
          source_id: 'D1',
          segments: ['s1', 's2'].map((segment_id) => ({
            segment_id,
            function_keys: ['F2'],
            risk_keys: ['R1'],
            disposition: 'REVIEWED',
            reason: '',
          })),
          limitation: '',
        },
      ],
    },
  };
  let state = 0;
  const { CatalogRiskDialog } = load(path.resolve(__dirname, '../src/RiskReports.tsx'), {
    ...React,
    useState: (initial) => [state++ === 4 ? expanded : initial, () => {}],
    useEffect: () => {},
  });
  const markup = renderToStaticMarkup(
    React.createElement(
      MemoryRouter,
      null,
      React.createElement(CatalogRiskDialog, {
        item: {
          risk_key: 'R1',
          report_id: 5,
          risk: report.risks[0],
          review_warnings: warnings,
          functions: [{ key: 'F1', module: '订单管理', name: '订单查询' }],
          status: 'PENDING',
          note: '',
          revision: 1,
          source_kind: 'ANALYSIS',
        },
        base: '/api/projects/1/requirements/risk-reports',
        projectId: 1,
        onClose() {},
        onSaved() {},
        onSessionEnd() {},
      }),
    ),
  );
  assert.match(markup, /2 个资料片段上的功能归属与本风险不一致/);
  assert.match(markup, /合成需求 · 商品详情.*片段标注“商品详情”.*R1 归属“订单查询”/);
  assert.doesNotMatch(markup, /片段的功能与风险标签待核对/);
});

test('cumulative catalog preserves report identity and manual risk origin', async () => {
  const original = global.fetch;
  try {
    global.fetch = async () =>
      new Response(
        JSON.stringify({
          overview: { reports: 1, functions: 1, risks: 1, high: 0, medium: 1, low: 0, pending: 1 },
          reports: [
            {
              id: 5,
              title: '报告',
              created_at: detail.created_at,
              created_by: '成员',
              outcome: 'COMPLETE',
              functions: 1,
              risks: 1,
              review_warning_count: 1,
              materials: [{ name: '需求', version: 'v1' }],
            },
          ],
          functions: [
            {
              id: '5:F1',
              report_id: 5,
              key: 'F1',
              module: '订单',
              name: '取消订单',
              risk_count: 1,
            },
          ],
          total: 1,
          page: 1,
          pages: 1,
          items: [
            {
              id: 'M8',
              source_kind: 'MANUAL',
              manual_id: 8,
              message_turn_id: 7,
              report_id: 5,
              report_title: '报告',
              risk_key: 'M8',
              risk: {
                key: 'M8',
                function_keys: ['F1'],
                title: '人工风险',
                type: 'AMBIGUITY',
                severity: 'MEDIUM',
                description: '描述',
                evidence: report.risks[0].evidence,
                impact: '影响',
                questions: ['问题'],
                improvement: report.risks[0].improvement,
              },
              review_warnings: [
                {
                  path: 'risks[0].evidence',
                  code: 'evidence_excerpt_mismatch',
                  source_id: 'D1',
                  segment_id: 's1',
                  risk_key: 'M8',
                },
              ],
              functions: [{ key: 'F1', module: '订单', name: '取消订单' }],
              status: 'PENDING',
              note: '',
              history: [],
              revision: 1,
              created_at: detail.created_at,
            },
          ],
        }),
      );
    const value = await api.riskCatalog('/catalog', new AbortController().signal);
    assert.equal(value.items[0].source_kind, 'MANUAL');
    assert.equal(value.items[0].report_id, 5);
    assert.equal(value.overview.pending, 1);
    assert.equal(value.reports[0].review_warning_count, 1);
    assert.equal(value.items[0].review_warnings[0].code, 'evidence_excerpt_mismatch');
  } finally {
    global.fetch = original;
  }
});

function findForm(node) {
  if (Array.isArray(node)) return node.map(findForm).find(Boolean);
  if (!node?.props) return null;
  return node.props.onSubmit ? node : findForm(node.props.children);
}
test('import submits both original JSON texts and explicit source version; never calls AI', async () => {
  const requests = [],
    results = [];
  const inputText = JSON.stringify(input, null, 2),
    reportText = JSON.stringify(report, null, 2);
  const values = [
    { filename: 'input.json', text: inputText, data: input, parsed: api.parseRiskInput(input) },
    {
      filename: 'risk-report.json',
      text: reportText,
      data: report,
      parsed: api.parseRiskReport(report),
    },
    [{ id: 2, name: '需求', kind: 'FILE', purpose: 'REQUIREMENT', versions: [version] }],
    [{ source_id: 'D1', document_id: 2, version_id: 3 }],
    '报告',
  ];
  let index = 0;
  const component = load(
    path.resolve(__dirname, '../src/RiskReports.tsx'),
    {
      ...React,
      useState: (initial) => [
        index < values.length ? values[index++] : (index++, initial),
        () => {},
      ],
      useEffect() {},
      useRef: (value) => ({ current: value }),
    },
    {
      './riskApi': {
        ...api,
        riskDetailRequest: async (url, project, options) => {
          requests.push({ url, project, options });
          return detail;
        },
      },
    },
  ).ImportReport;
  const tree = component({
    base: '/api/projects/1/requirements/risk-reports',
    project: 1,
    onClose() {},
    onSessionEnd() {},
    onImported: (value) => results.push(value),
  });
  await findForm(tree).props.onSubmit({ preventDefault() {} });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/projects/1/requirements/risk-reports/import');
  const payload = JSON.parse(requests[0].options.body);
  assert.equal(payload.input_json, inputText);
  assert.equal(payload.report_json, reportText);
  assert.deepEqual(payload.bindings, [{ source_id: 'D1', document_id: 2, version_id: 3 }]);
  assert.equal(results[0].id, 5);
});

test('human handling sends revision and conclusion without rewriting the report', async () => {
  const requests = [];
  let index = 0;
  const component = load(
    path.resolve(__dirname, '../src/RiskReports.tsx'),
    {
      ...React,
      useState: (initial) => [['RESOLVED', '已核对产品补充规则。'][index++] ?? initial, () => {}],
      useEffect() {},
      useRef: (value) => ({ current: value }),
    },
    {
      './riskApi': {
        ...api,
        riskDetailRequest: async (url, project, options) => {
          requests.push({ url, options });
          return detail;
        },
      },
    },
  ).HandleRisk;
  await findForm(
    component({
      base: '/api/projects/1/requirements/risk-reports',
      detail,
      risk: report.risks[0],
      onClose() {},
      onSource() {},
      onSessionEnd() {},
      onSaved() {},
    }),
  ).props.onSubmit({ preventDefault() {} });
  assert.equal(requests.length, 1);
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    risk_key: 'R1',
    status: 'RESOLVED',
    note: '已核对产品补充规则。',
    revision: 1,
  });
});

test('form escapes rendered content', () => {
  const Form = load(path.resolve(__dirname, '../src/Form.tsx')).Form;
  const markup = renderToStaticMarkup(
    React.createElement(Form, {}, React.createElement('p', {}, '<script>secret</script>')),
  );
  assert.ok(!markup.includes('<script>'));
});
test('analysis material groups preserve prototype-only selections and fixed versions', async () => {
  const options = [
    { id: 2, name: '需求', kind: 'FILE', purpose: 'REQUIREMENT', versions: [version] },
    {
      id: 7,
      name: '页面.html',
      kind: 'FILE',
      purpose: 'PROTOTYPE',
      versions: [{ ...version, id: 9 }],
    },
    { id: 8, name: '原型链接', kind: 'LINK', purpose: 'PROTOTYPE', versions: [] },
  ];
  const requests = [];
  let index = 0;
  const values = [options, { 7: 9 }, {}, '原型检查', '', false, '', '个人AI'];
  const component = load(
    path.resolve(__dirname, '../src/RiskReports.tsx'),
    {
      ...React,
      useState: (initial) => [index < values.length ? values[index++] : initial, () => {}],
      useEffect() {},
    },
    {
      './api/http': {
        apiRequest: async (url, init) => {
          requests.push({ url, ...init });
          return queuedTask(1, init);
        },
      },
    },
  ).StartAnalysis;
  const tree = component({
    project: 1,
    base: '/reports',
    retry: null,
    onClose() {},
    onStarted() {},
    onSessionEnd() {},
  });
  function nodes(node) {
    if (Array.isArray(node)) return node.flatMap(nodes);
    return node?.props ? [node, ...nodes(node.props.children)] : [];
  }
  const groups = nodes(tree).filter((node) => node.type === 'fieldset');
  assert.equal(groups.length, 2);
  assert.equal(nodes(groups[0]).filter((node) => node.type === 'input').length, 1);
  const prototypeInputs = nodes(groups[1]).filter((node) => node.type === 'input');
  assert.deepEqual(
    prototypeInputs.map((node) => node.props.checked),
    [true, false],
  );
  const versionSelect = nodes(groups[1]).find((node) => node.props.label === '固定版本');
  assert.equal(versionSelect.props.value, '9');
  await findForm(tree).props.onSubmit({ preventDefault() {} });
  assert.equal(requests.length, 1);
  assert.deepEqual(JSON.parse(requests[0].body).selections, [{ document_id: 7, version_id: 9 }]);
});
test('retry submits only stored selection fields, without report source IDs', async () => {
  const original = global.fetch;
  const selection = {
    document_id: 83,
    version_id: null,
    paths: ['page-1097.html'],
    snapshot: 'a'.repeat(64),
    url: 'https://prototype.geekuat.com/p/Test123/',
  };
  let retry;
  try {
    global.fetch = async () =>
      new Response(
        JSON.stringify({
          items: [
            {
              id: 16,
              project_id: 5,
              request_id: crypto.randomUUID(),
              retry_of: null,
              title: '门店订货测试',
              focus: '',
              selections: [selection],
              status: 'FAILED',
              error_code: 'risk_report_invalid|risks[1]|inconsistent_reference',
              report_id: null,
              created_by: '成员',
              can_cancel: false,
              candidate_available: false,
              can_revalidate: false,
              function_risk_corrections: [],
              created_at: detail.created_at,
              updated_at: detail.updated_at,
            },
          ],
        }),
        { status: 200 },
      );
    [retry] = await api.riskAnalyses('/risk-analyses', new AbortController().signal);
  } finally {
    global.fetch = original;
  }
  assert.deepEqual(retry.selections, [selection]);
  const requests = [];
  let index = 0;
  const values = [
    [],
    { 83: null },
    { 83: { paths: selection.paths, snapshot: selection.snapshot } },
    '门店订货测试 · 重新分析',
    '',
    false,
    '',
    '个人AI',
  ];
  const component = load(
    path.resolve(__dirname, '../src/RiskReports.tsx'),
    {
      ...React,
      useState: (initial) => [index < values.length ? values[index++] : initial, () => {}],
      useEffect() {},
    },
    {
      './api/http': {
        apiRequest: async (url, init) => {
          requests.push({ url, ...init });
          return queuedTask(5, init);
        },
      },
    },
  ).StartAnalysis;
  const tree = component({
    project: 5,
    base: '/reports',
    retry,
    onClose() {},
    onStarted() {},
    onSessionEnd() {},
  });
  await findForm(tree).props.onSubmit({ preventDefault() {} });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/projects/5/requirements/risk-analyses');
  assert.deepEqual(JSON.parse(requests[0].body).selections, [selection]);
  assert.equal(JSON.parse(requests[0].body).retry_of, 16);
  assert.match(
    api.riskError(new Error('invalid_request'), () => {}),
    /提交字段校验未通过/,
  );
});
test('HTML preview offers a new-tab link without fetching source', () => {
  const effects = [];
  const { OriginalPreview } = load(
    path.resolve(__dirname, '../src/Documents.tsx'),
    {
      ...React,
      useState: (initial) => [initial, () => {}],
      useEffect: (effect) => effects.push(effect),
    },
    {
      './api/http': {
        apiRequest() {
          assert.fail('HTML source must not be fetched');
        },
      },
    },
  );
  for (const extension of ['html', 'htm']) {
    const tree = OriginalPreview({
      base: '/api/projects/1/documents',
      version: { ...version, extension, filename: `页面.${extension}` },
      onSessionEnd() {},
      onOpen() {},
      onLinksChanged() {},
    });
    const markup = renderToStaticMarkup(tree);
    assert.match(markup, /href="\/api\/projects\/1\/documents\/versions\/3\/browser"/);
    assert.match(markup, /target="_blank"/);
    assert.match(markup, /rel="noopener noreferrer"/);
    assert.ok(!markup.includes('<pre'));
    effects.pop()();
  }
});
