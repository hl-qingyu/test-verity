const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
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
const source = (name) => path.resolve(__dirname, '../src/', name);
const api = load(source('codeAnalysisApi.ts'));
const sample = (name) =>
  JSON.parse(
    fs.readFileSync(
      path.resolve(__dirname, '../../skill/code-review/examples/', name + '.json'),
      'utf8',
    ),
  );
const input = sample('input'),
  report = sample('output');
const raw = {
  id: 4,
  project_id: 1,
  title: '固定分析',
  focus: '',
  targets: input.targets,
  status: 'COMPLETED',
  error_code: '',
  retry_of: null,
  created_at: '2026-09-21T00:00:00Z',
  updated_at: '2026-09-21T00:00:00Z',
  revision: 1,
  origin: 'IMPORT',
  ai: {},
  can_cancel: false,
  can_retry: false,
  findings_count: 2,
  outcome: report.outcome,
  contract_version: 2,
  input,
  report,
  handling: {},
};
const record = api.parseCodeDetail(raw);

test('v3 paired import accepts a candidate before the platform computes outcome', () => {
  const inputV3 = api.parseCodeInput(sample('input-v3'));
  const candidate = sample('output-v3');
  const result = api.parseCodeImportReport(candidate);
  assert.equal(inputV3.contract_version, 3);
  assert.equal(result.contract_version, 3);
  assert.equal(inputV3.request_id, result.request_id);
  assert.throws(() => api.parseCodeReport(candidate));
  assert.equal(api.parseCodeReport({ ...candidate, outcome: 'PARTIAL' }).outcome, 'PARTIAL');
});

test('new analysis submits the complete selection above 16MiB through the shared request', async () => {
  const content = 'x'.repeat(2_000_000);
  const files = Array.from({ length: 9 }, (_, n) => ({ path: `part${n}.py`, content }));
  const selected = {
    source: {
      selection: { kind: 'LOCAL', source_id: 1, source_version: 1, files },
      repositoryKind: 'BACKEND',
      tree: {},
    },
  };
  const states = ['大输入', '', 'LOCAL', ['BUG'], selected, [], 'REQUIREMENT', false, ''];
  let calls = 0;
  await new Promise((resolve, reject) => {
    const { NewCodeAnalysis } = load(source('CodeAnalysisNew.tsx'), {
      react: {
        ...React,
        useEffect() {},
        useRef: (value) => ({ current: value }),
        useState: () => {
          const index = 9 - states.length;
          return [states.shift(), (value) => index === 8 && value && reject(Error(value))];
        },
      },
      './localCodeFiles': {
        readSelection: async () => ({
          files: Object.fromEntries(files.map((file) => [file.path, file])),
          skipped: {},
        }),
      },
      './codeAnalysisApi': {
        ...api,
        codeRequest: async (url, parse, options) => {
          calls++;
          assert.equal(url, '/api/projects/1/code-analysis');
          assert.ok(new TextEncoder().encode(options.body).length > api.CODE_FILE_LIMIT);
          const sent = JSON.parse(options.body).sources[0].files;
          assert.deepEqual(
            sent.map((file) => file.path),
            files.map((file) => file.path),
          );
          assert.ok(sent.every((file) => file.content === content && file.sha256.length === 64));
          assert.ok(options.signal instanceof AbortSignal);
          return record;
        },
      },
    });
    const element = NewCodeAnalysis({
      projectId: 1,
      user: { id: 2 },
      options: { repositories: [], local_sources: [], materials: [], ai: { error_code: '' } },
      onClose() {},
      onCreated: resolve,
      onSessionEnd() {},
    });
    element.props.children.props.onSubmit({ preventDefault() {} });
  });
  assert.equal(calls, 1);
});

test('multi-target preflight hard-blocks missing code sides and accepts Web/mobile roles', () => {
  const targets = Object.keys(api.codeTargets),
    backend = { kind: 'BACKEND', count: 1 },
    web = { kind: 'WEB', count: 1 },
    mobile = { kind: 'FLUTTER', count: 1 };
  for (const sources of [
    [],
    [backend],
    [web],
    [mobile],
    [web, mobile],
    [backend, { kind: 'OTHER', count: 9 }],
    [backend, { ...web, count: 0 }],
  ])
    assert.match(api.codePreflight(targets, sources, 3).blocking, /必须同时选择/);
  for (const client of [web, mobile])
    assert.equal(api.codePreflight(targets, [backend, client], 1).blocking, '');
  assert.equal(api.codePreflight(['BUG'], [backend], 0).blocking, '');
  assert.notEqual(api.codePreflight(['REQUIREMENT_DEVIATION'], [backend], 0).blocking, '');
  assert.equal(api.codePreflight(['BUG', 'REQUIREMENT_DEVIATION'], [backend], 0).blocking, '');
});

test('v2 API parsing preserves goal views and rejects old/malformed structures', () => {
  assert.equal(record.report.findings.length, 2);
  assert.equal(record.report.findings[1].target_views.length, 2);
  assert.equal(record.input.sources[2].repository_kind, 'FLUTTER');
  const corrected = api.parseCodeDetail({
    ...raw,
    can_revalidate: true,
    evidence_corrections: [
      {
        evidence_key: 'E1',
        original_start_line: 14,
        original_end_line: 16,
        start_line: 15,
        end_line: 16,
        removed_trailing_lf: true,
      },
    ],
  });
  assert.equal(corrected.can_revalidate, true);
  assert.equal(corrected.evidence_corrections[0].start_line, 15);
  assert.throws(() => api.parseCodeInput({ ...input, contract_version: 1 }));
  assert.throws(() =>
    api.parseCodeReport({
      ...report,
      findings: [{ ...report.findings[0], severity: 'constructor' }],
    }),
  );
  assert.throws(() => api.parseCodeDetail({ ...raw, can_cancel: 'true' }));
  assert.equal(
    api.parseCodeDetail({
      ...raw,
      status: 'RUNNING',
      input: {},
      report: {},
      contract_version: null,
    }).report,
    null,
  );
});

test('requests use shared HTTP, preserve body and caller cancellation, handle expired sessions', async () => {
  const original = global.fetch,
    calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify(raw), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  try {
    const c = new AbortController(),
      body = JSON.stringify({ input_json: '{}', report_json: '{}' });
    const result = await api.codeRequest(
      '/api/projects/1/code-analysis/import',
      api.parseCodeDetail,
      { method: 'POST', body, signal: c.signal },
    );
    assert.equal(result.id, 4);
    assert.equal(calls[0].options.body, body);
    assert.equal(calls[0].options.method, 'POST');
    await api.codeRequest('/api/projects/1/code-analysis/4/revalidate', api.parseCodeDetail, {
      method: 'POST',
    });
    assert.equal(calls[1].url, '/api/projects/1/code-analysis/4/revalidate');
    assert.equal(calls[1].options.method, 'POST');
    c.abort();
    assert.equal(calls[0].options.signal.aborted, true);
    global.fetch = async () =>
      new Response(JSON.stringify({ detail: 'code_evidence_invalid' }), { status: 422 });
    await assert.rejects(
      api.codeRequest('/api/projects/1/code-analysis/import', api.parseCodeDetail),
      /code_evidence_invalid/,
    );
    global.fetch = async () => new Response('{}', { status: 401 });
    await assert.rejects(
      api.codeRequest('/api/projects/1/code-analysis', api.parseCodeDetail),
      /not_authenticated/,
    );
    let ended = false;
    api.codeError(new Error('not_authenticated'), () => (ended = true));
    assert.equal(ended, true);
  } finally {
    global.fetch = original;
  }
});

test('paired file loading enforces size and JSON boundaries', async () => {
  const parsed = await api.readCodeJSON({
    name: 'input.json',
    size: 10,
    text: async () => '\uFEFF' + JSON.stringify(input),
  });
  assert.equal(api.parseCodeInput(parsed.data).request_id, input.request_id);
  await assert.rejects(api.readCodeJSON({ name: 'bad.txt', size: 1 }), /code_import_file_invalid/);
  await assert.rejects(
    api.readCodeJSON({ name: 'huge.json', size: api.CODE_FILE_LIMIT + 1 }),
    /code_import_file_invalid/,
  );
  await assert.rejects(
    api.readCodeJSON({ name: 'bad.json', size: 1, text: async () => '{' }),
    /code_json_invalid/,
  );
});

test('goal-specific detail renders evidence and escapes untrusted source text', () => {
  const { CodeFindingDetail } = load(source('CodeAnalysisDetail.tsx'));
  const props = { record, onClose() {}, onSaved() {}, onAsk() {}, onSessionEnd() {} };
  const requirement = renderToStaticMarkup(
    React.createElement(CodeFindingDetail, { ...props, finding: record.report.findings[0] }),
  );
  assert.match(requirement, /需求与实现对照/);
  assert.match(requirement, /执行路径与错误原因/);
  assert.ok(!requirement.includes('接口与字段对照'));
  const mismatch = renderToStaticMarkup(
    React.createElement(CodeFindingDetail, { ...props, finding: record.report.findings[1] }),
  );
  for (const text of [
    '接口与字段对照',
    'verificationStatus',
    'verifyStatus',
    '调用链与证据',
    '固定',
    '影响范围',
    '修复建议',
    '验证建议',
    '人工处理',
  ])
    assert.ok(mismatch.includes(text), text);
  assert.ok(!mismatch.includes('<select'));
  const tainted = structuredClone(record);
  tainted.report.evidence[0].excerpt = '<img src=x onerror=bad()>';
  const markup = renderToStaticMarkup(
    React.createElement(CodeFindingDetail, {
      ...props,
      record: tainted,
      finding: tainted.report.findings[1],
    }),
  );
  assert.ok(!markup.includes('<img src=x'));
  assert.match(markup, /&lt;img/);
});

test('new/import dialogs and file tree retain prototype controls and ordering', () => {
  const { NewCodeAnalysis, CodeFileTree } = load(source('CodeAnalysisNew.tsx'));
  const { ImportCodeAnalysis } = load(source('CodeAnalysisImport.tsx'));
  const options = {
    ai: { name: '个人AI', model: 'demo', version: 1, error_code: '' },
    file_limit: api.CODE_FILE_LIMIT,
    repositories: [],
    connections: [],
    local_sources: [],
    materials: [
      {
        id: 7,
        name: '未命名资料',
        purpose: 'REQUIREMENT',
        kind: 'FILE',
        commit: '',
        files: [],
        versions: [{ id: 8, number: 1, filename: '业务需求.docx', extension: 'docx' }],
      },
    ],
  };
  const props = {
    projectId: 1,
    user: { id: 2 },
    options,
    onClose() {},
    onCreated() {},
    onImported() {},
    onSessionEnd() {},
  };
  const create = renderToStaticMarkup(React.createElement(NewCodeAnalysis, props));
  const titles = [
    '分析名称',
    '检查目标',
    '代码来源与文件范围',
    '需求与原型依据',
    '本次检查范围确认',
    '补充关注点',
  ];
  for (let i = 1; i < titles.length; i++)
    assert.ok(create.indexOf(titles[i - 1]) < create.indexOf(titles[i]));
  assert.ok(!create.includes('<select'));
  assert.match(create, /前后端一致性必须同时选择/);
  assert.match(create, /业务需求\.docx/);
  assert.doesNotMatch(create, /未命名资料/);
  const imported = renderToStaticMarkup(React.createElement(ImportCodeAnalysis, props));
  assert.match(imported, /input.json/);
  assert.match(imported, /report.json/);
  assert.match(imported, /每份最大 16 MB/);
  assert.equal((imported.match(/选择文件/g) || []).length, 2);
  const tree = renderToStaticMarkup(
    React.createElement(CodeFileTree, {
      paths: ['src/a.py', 'src/b.py'],
      selected: ['src/a.py'],
      onChange() {},
    }),
  );
  assert.match(tree, /code-tree-directory/);
  assert.match(tree, /src\//);
  assert.ok(!tree.includes('a.py'));
  assert.match(tree, /选择当前可见文件/);
  assert.match(tree, /清空/);
  const largeTree = renderToStaticMarkup(
    React.createElement(CodeFileTree, {
      paths: Array.from({ length: 250 }, (_, index) => `file-${index}.ts`),
      selected: [],
      onChange() {},
    }),
  );
  assert.equal((largeTree.match(/code-tree-file/g) || []).length, 200);
  assert.match(largeTree, /显示更多（剩余 50 项）/);
});

test('production layout follows prototype columns, statuses, scroll and narrow-screen rules', () => {
  const css = fs.readFileSync(source('code-analysis.css'), 'utf8');
  assert.match(css, /grid-template-columns:\s*220px minmax\(0, 1fr\) 270px/);
  assert.match(css, /overflow-y:\s*scroll/);
  assert.match(css, /@media \(max-width: 680px\)/);
  assert.match(css, /\.code-target-detail/);
  assert.match(css, /\.code-evidence-chain/);
  const { CodeAnalysis } = load(source('CodeAnalysis.tsx'));
  const { MemoryRouter } = require('react-router-dom');
  const markup = renderToStaticMarkup(
    React.createElement(
      MemoryRouter,
      null,
      React.createElement(CodeAnalysis, { project: { id: 1 }, user: { id: 1 }, onSessionEnd() {} }),
    ),
  );
  assert.match(markup, /新建代码分析/);
  assert.match(markup, /导入代码分析/);
  assert.match(markup, /分析记录/);
  assert.match(markup, /本记录范围/);
});
