const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test'),
  assert = require('node:assert/strict'),
  fs = require('node:fs'),
  path = require('node:path'),
  ts = require('typescript'),
  React = require('react'),
  { renderToStaticMarkup } = require('react-dom/server');
const src = (name) => path.resolve(__dirname, '../src', name);
function load(file, overrides = {}) {
  const exports = {};
  const js = compileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  evaluateModule(
    js,
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
const api = load(src('generationPage.ts')),
  cases = load(src('caseApi.ts'));
function payload(size = 12) {
  const materials = [
    {
      source_id: 'M1',
      name: '固定需求',
      version: 'v2',
      read_state: 'READ',
      segments: [{ id: 'S1', location: '§1', text: '本门店有效订货成功；只创建一条订单' }],
    },
  ];
  const design = {
    ...cases.blankDesign(),
    module: '订货',
    case_type: '业务流程',
    priority: 'P0',
    title: '本门店提交',
    steps: '1.填写信息\n2.提交',
    expected: '只创建一条订单',
  };
  return {
    input: {
      analysis_type: 'CASE_GENERATION',
      contract_version: 1,
      request_id: 'request-1',
      project_id: 1,
      mode: 'INITIAL',
      scope: '完整声明需求',
      materials,
    },
    report: {
      analysis_type: 'CASE_GENERATION',
      contract_version: 1,
      request_id: 'request-1',
      outcome: 'COMPLETE',
      suggestions: Array.from({ length: size }, (_, i) => ({
        key: 'N' + (i + 1),
        kind: 'NEW',
        function: '订货',
        design: { ...design, title: '场景' + (i + 1) },
        reason: '固定依据',
        blocked: false,
        evidence: [{ source: 'M1', segment: 'S1', quote: '只创建一条订单', side: 'NEW' }],
      })),
      questions: [
        {
          key: 'Q1',
          function: '付款',
          title: '超时未说明',
          text: '请确认失败恢复',
          evidence: '§2',
        },
      ],
      limitations: [],
    },
  };
}
function record(size = 12) {
  const { input, report } = payload(size);
  return {
    id: 'record-1',
    ownerId: 1,
    projectId: 1,
    title: '生成预览',
    createdAt: '2026-10-10T00:00:00Z',
    mode: input.mode,
    origin: 'PREVIEW',
    cancelled: false,
    scope: input.scope,
    focus: '',
    materials: input.materials.map((m) => ({
      sourceId: m.source_id,
      name: m.name,
      version: m.version,
      readState: m.read_state,
      segments: m.segments,
      paths: [],
    })),
    cases: [],
    libraryRevision: null,
    baselineId: '',
    caseScope: '',
    suggestions: report.suggestions,
    questions: report.questions,
    handling: {},
    decisions: [],
    failures: [],
    chatDrafts: {},
    batches: [],
    limitations: [],
    outcome: report.outcome,
    inputText: JSON.stringify(input),
    reportText: JSON.stringify(report),
  };
}
test('sidebar duration uses hours, minutes and seconds, freezes ended batches and handles missing history', () => {
  const start = '2026-10-16T00:00:00Z',
    now = Date.parse(start) + 3723000;
  assert.equal(api.generationDuration([{ startedAt: start, finishedAt: null }], now), '01:02:03');
  const ended = [{ startedAt: start, finishedAt: '2026-10-16T01:02:03Z' }];
  assert.equal(api.generationDuration(ended, now + 86400000), '01:02:03');
  assert.equal(api.generationDuration([...ended, ...ended], now), '02:04:06');
  assert.equal(
    api.generationDuration([{ startedAt: start, finishedAt: null }], now + 360000000),
    '101:02:03',
  );
  assert.equal(
    api.generationDuration([{ startedAt: start, finishedAt: null }], now - 86400000),
    '00:00:00',
  );
  for (const timing of [
    undefined,
    [],
    [{ startedAt: null, finishedAt: null }],
    [{ startedAt: 'bad', finishedAt: null }],
    [...ended, { startedAt: null, finishedAt: null }],
  ])
    assert.equal(api.generationDuration(timing, now), '—');
  const { GenerationWorkspace } = load(src('CaseGeneration.tsx'));
  const html = renderToStaticMarkup(
    React.createElement(
      require('react-router-dom').MemoryRouter,
      null,
      React.createElement(GenerationWorkspace, {
        project: { id: 1 },
        user: { id: 1 },
        rows: [],
        summaries: [{ ...record(), timings: ended }],
        onChange() {},
        onSessionEnd() {},
      }),
    ),
  );
  assert.match(html, /生成记录/);
  assert.match(html, /耗时 01:02:03/);
});

test('adoption counts successful AI case writes once, including revised cases and the full record', () => {
  const r = record(32);
  r.suggestions[1].kind = 'UPDATE';
  r.handling.N1 = [
    { status: '待审阅', draft: { ...r.suggestions[0].design, expected: '人工修订的预期' } },
    { status: '需人工确认' },
    { status: '已应用' },
    { status: '已应用' },
  ];
  r.handling.N2 = [{ status: '待审阅' }];
  r.handling.N3 = [{ status: '需人工确认' }];
  r.handling.N4 = [{ status: '已忽略' }];
  r.applications = [{ status: 'RUNNING', items: [{ key: 'N2', status: 'PENDING' }] }];
  const raw = r.reportText;
  assert.deepEqual(api.generationAdoption(r), { adopted: 1, total: 32, rate: '3.1%' });
  for (const [key, kind, status] of [
    ['REUSE-1', 'REUSE', '已复用'],
    ['RETIRE-1', 'RETIRE', '已应用'],
    ['manual:1', 'NEW', '已应用'],
  ]) {
    r.suggestions.push({ ...r.suggestions[0], key, kind });
    r.handling[key] = [{ status }];
  }
  assert.deepEqual(api.generationAdoption(r), { adopted: 1, total: 32, rate: '3.1%' });
  r.handling.N2.push({ status: '已应用' });
  assert.deepEqual(api.generationAdoption(r), { adopted: 2, total: 32, rate: '6.3%' });
  assert.equal(r.reportText, raw);
  assert.deepEqual(api.generationAdoption(record(0)), { adopted: 0, total: 0, rate: '—' });
  assert.deepEqual(api.generationAdoption(record(1)), { adopted: 0, total: 1, rate: '0.0%' });
  r.handling.N2 = [{ status: '已复用' }];
  assert.equal(api.generationAdoption(r).adopted, 1);
});

test('workspace displays adoption alongside existing counts and handles loading and empty records', () => {
  const { GenerationWorkspace } = load(src('CaseGeneration.tsx'));
  const render = (row, extra = {}) =>
    renderToStaticMarkup(
      React.createElement(
        require('react-router-dom').MemoryRouter,
        null,
        React.createElement(GenerationWorkspace, {
          project: { id: 1 },
          user: { id: 1 },
          rows: row ? [row] : [],
          onChange() {},
          onSessionEnd() {},
          ...extra,
        }),
      ),
    );
  const r = { ...record(32), origin: 'SERVER' };
  r.handling.N1 = [{ status: '已应用', draft: r.suggestions[0].design }];
  assert.match(
    render(r),
    /<strong>3\.1%<\/strong><small>采纳率<\/small><small>已采纳 1\/32<\/small>/,
  );
  assert.match(render(r), /待审阅/);
  assert.match(render(r), /应用\/复用/);
  assert.match(render(r), /需人工确认/);
  assert.match(render({ ...r, suggestions: [], handling: {}, rawReports: [{}] }), /暂无生成用例/);
  assert.doesNotMatch(render(null, { detailLoading: true }), /已采纳|NaN|Infinity/);
  assert.doesNotMatch(render({ ...r, origin: 'DRAFT' }), /已采纳/);
});

test('512 suggestions are selected across pages; retired, ignored and unresolved entries are excluded without mutating the original report', () => {
  const r = record(512),
    raw = r.reportText;
  r.suggestions[1].blocked = true;
  r.suggestions[2].kind = 'RETIRE';
  r.handling.N4 = [
    { status: '已忽略', draft: r.suggestions[3].design, revision: 1, note: '不采用' },
  ];
  const selected = api.generationSelection(r, r.suggestions, []);
  assert.equal(selected.length, 509);
  assert.ok(selected.includes('N512'));
  assert.ok(!selected.includes('N2'));
  assert.ok(!selected.includes('N3'));
  assert.ok(!selected.includes('N4'));
  assert.ok(api.generationSelection(r, r.suggestions.slice(0, 10), ['N512']).includes('N512'));
  assert.equal(r.reportText, raw);
  const text = api.generationMarkdown(r);
  assert.match(text, /N512/);
  assert.match(text, /未进行AI分析/);
});
test('candidate XLSX exports all 512 rows with 14 literal-text columns, blank formal IDs and testers', async () => {
  const r = record(512);
  r.suggestions[0].design.steps = '=HYPERLINK("https://x")';
  const ex = load(src('generationExport.ts'));
  const bytes = Buffer.from(await ex.generationXlsx(r).arrayBuffer());
  let offset = 0,
    xml = '';
  while (bytes.readUInt32LE(offset) === 0x04034b50) {
    const size = bytes.readUInt32LE(offset + 18),
      nameLength = bytes.readUInt16LE(offset + 26),
      extra = bytes.readUInt16LE(offset + 28),
      name = bytes.subarray(offset + 30, offset + 30 + nameLength).toString(),
      start = offset + 30 + nameLength + extra;
    const data = bytes.subarray(start, start + size);
    if (name === 'xl/worksheets/sheet1.xml') xml = data.toString();
    offset = start + size;
  }
  assert.equal((xml.match(/<row /g) || []).length, 513);
  assert.equal((xml.match(/ t="inlineStr"/g) || []).length, 513 * 14);
  assert.ok(!xml.includes('<f>'));
  assert.match(xml, /=HYPERLINK/);
  assert.match(xml, /<c r="B2" t="inlineStr"><is><t xml:space="preserve"><\/t>/);
  assert.match(xml, /<c r="L2" t="inlineStr"><is><t xml:space="preserve">未测<\/t>/);
  assert.match(xml, /<c r="M2" t="inlineStr"><is><t xml:space="preserve"><\/t>/);
});
test('case snapshot uses only the existing readonly endpoint, combines cancellation and rejects truncated scope', async () => {
  let called;
  const read = load(src('generationRead.ts'), {
    './api/http': {
      apiRequest: async (url, init) => {
        called = { url, init };
        return {
          revision: 1,
          next_number: 1,
          categories: [],
          items: [],
          total: 0,
          page: 1,
          page_size: 100,
        };
      },
    },
  });
  const c = new AbortController();
  assert.equal((await read.generationCaseSnapshot(7, c.signal)).total, 0);
  assert.equal(called.url, '/api/projects/7/cases/edit-scope');
  assert.equal(called.init.method, 'POST');
  assert.equal(called.init.signal, c.signal);
  const bad = load(src('generationRead.ts'), {
    './api/http': {
      apiRequest: async () => ({
        revision: 1,
        next_number: 1,
        categories: [],
        items: [],
        total: 500,
        page: 1,
        page_size: 100,
      }),
    },
  });
  await assert.rejects(bad.generationCaseSnapshot(7, c.signal), /case_response_invalid/);
});
test('formal generation UI keeps expanded records, tabs, server operations and user/project isolated workspace', () => {
  const { GenerationWorkspace } = load(src('CaseGeneration.tsx'));
  const props = { project: { id: 1 }, user: { id: 1 }, rows: [], onChange() {}, onSessionEnd() {} };
  const html = renderToStaticMarkup(
    React.createElement(
      require('react-router-dom').MemoryRouter,
      null,
      React.createElement(GenerationWorkspace, props),
    ),
  );
  assert.match(html, /生成记录/);
  assert.match(html, /固定依据与范围/);
  assert.doesNotMatch(html, /id="generation-records" hidden=""/);
  assert.match(html, /aria-expanded="true" aria-controls="generation-records"/);
  assert.match(html, /role="tablist"/);
  assert.match(html, /暂无用例生成记录/);
  assert.ok(!html.includes('512条 ·'));
  const populated = renderToStaticMarkup(
    React.createElement(
      require('react-router-dom').MemoryRouter,
      null,
      React.createElement(GenerationWorkspace, {
        ...props,
        rows: [{ ...record(1), origin: 'SERVER' }],
      }),
    ),
  );
  assert.match(populated, /生成预览/);
  assert.match(populated, /场景1/);
  assert.doesNotMatch(populated, /暂无用例生成记录/);
});

test('continuous review groups stable functions, shows twenty rows and escapes full design text', () => {
  const r = { ...record(25), origin: 'SERVER' };
  r.suggestions[1].function = '付款';
  r.suggestions[0].design.steps = '<img src=x onerror=alert(1)>\n确认提交';
  r.suggestions[0].design.expected = '只创建一条订单';
  r.suggestions[2].blocked = true;
  r.suggestions[3].design.steps = '';
  const grouped = [...api.generationGroups(r.suggestions).values()].flat();
  assert.equal(grouped.length, 25);
  assert.equal(grouped.at(-1).key, 'N2');
  assert.equal(api.GENERATION_PAGE_SIZE, 20);
  const { GenerationTable } = load(src('GenerationTable.tsx'));
  const html = renderToStaticMarkup(
    React.createElement(GenerationTable, {
      record: r,
      rows: grouped.slice(0, api.GENERATION_PAGE_SIZE),
      filtered: grouped,
      chosen: ['N1'],
      busy: false,
      issues: {},
      duplicates: [],
      onChoose() {},
      onDetail() {},
      onReview() {},
      onEvidence() {},
      onAsk() {},
      onApplied() {},
      onResolve() {},
      onBatchReview() {},
    }),
  );
  assert.equal((html.match(/data-cg-row=/g) || []).length, 20);
  assert.match(html, /前置条件/);
  assert.match(html, /操作步骤/);
  assert.match(html, /预期结果/);
  assert.match(html, /展开 \/ 收起本页全文/);
  assert.match(html, /需处理/);
  assert.match(html, /必填内容待补充/);
  assert.match(html, /&lt;img/);
  assert.ok(!html.includes('<img'));
  assert.match(html, /is-selected/);
  assert.match(html, /aria-expanded="false"/);
  const { GenerationWorkspace } = load(src('CaseGeneration.tsx'));
  const page = renderToStaticMarkup(
    React.createElement(
      require('react-router-dom').MemoryRouter,
      null,
      React.createElement(GenerationWorkspace, {
        project: { id: 1 },
        user: { id: 1 },
        rows: [r],
        onChange() {},
        onSessionEnd() {},
      }),
    ),
  );
  assert.match(page, /每页20条/);
  assert.match(page, /第1\/2页/);
  assert.equal((page.match(/data-cg-row=/g) || []).length, 20);
});

test('new generation prepares complete scope without asking users to accept batching rules', () => {
  const { CaseGenerationNew } = load(src('CaseGenerationNew.tsx'));
  const html = renderToStaticMarkup(
    React.createElement(CaseGenerationNew, {
      projectId: 1,
      user: { id: 1 },
      options: { materials: [], connections: [] },
      prototypes: [],
      snapshot: { items: [], categories: [], revision: 0 },
      records: [],
      onClose() {},
      onCreate() {},
      onSessionEnd() {},
    }),
  );
  assert.match(html, /不对照已有用例/);
  assert.match(html, /开始用例生成/);
  assert.ok(!/500\+分批计划|已核对资料、用例范围和分批调用规则/.test(html));
});

test('generation activity shows live loading and explicit safe failure diagnostics without fake progress', () => {
  const { GenerationActivity } = load(src('CaseGeneration.tsx'));
  const base = {
    key: 'b1',
    function: 'scope',
    attempts: 1,
    reason: '',
    status: 'RUNNING',
    startedAt: new Date(Date.now() - 65000).toISOString(),
    diagnostics: { phase: 'receiving', received_bytes: 1024, output_characters: 20 },
  };
  const render = (b) =>
    renderToStaticMarkup(React.createElement(GenerationActivity, { record: { batches: [b] } }));
  const html = render(base);
  assert.match(html, /generation-spinner/);
  assert.match(html, /aria-busy="true"/);
  assert.match(html, /正在接收AI响应/);
  assert.match(html, /已运行/);
  assert.match(html, /1,024/);
  assert.ok(!html.includes('%'));
  const cli = render({
    ...base,
    diagnostics: {
      call_mode: 'CODEX_EXEC',
      phase: 'cli_waiting',
      received_bytes: 230,
      output_characters: 0,
    },
  });
  assert.match(cli, /CLI已启动，等待模型结果/);
  assert.match(cli, /CLI事件已接收/);
  assert.match(cli, /230/);
  assert.ok(!cli.includes('正在接收AI响应'));
  const failed = render({
    ...base,
    status: 'FAILED',
    reason: 'ai_stream_failed',
    diagnostics: {
      error_category: 'timeout',
      request_id: 'req_abcdef123456',
      elapsed_seconds: 900,
    },
  });
  assert.match(failed, /上游超时/);
  assert.match(failed, /req_abcdef123456/);
  assert.ok(!failed.includes('generation-spinner'));
  const candidate = render({
    ...base,
    status: 'FAILED',
    reason: 'generation_contract_invalid',
    candidateAvailable: true,
  });
  assert.match(candidate, /原始响应已保存/);
  assert.match(candidate, /免费重新校验/);
  assert.ok(!candidate.includes('调用失败'));
  assert.equal(
    render({ ...base, status: 'COMPLETED' }),
    '<div class="generation-activity-list"></div>',
  );
});

test('saved CLI rounds suppress the activity card until a newer generation needs attention', () => {
  const { GenerationActivity } = load(src('CaseGeneration.tsx'));
  const original = {
      id: 9,
      key: 'B1',
      status: 'FAILED',
      reason: 'generation_terminal_turn_interrupted',
      startedAt: '2026-11-16T09:32:00Z',
      diagnostics: { received_bytes: 7526, output_characters: 0 },
    },
    rounds = [
      { id: 'new', batchId: 11, timestamp: '2026-11-17T08:15:00Z', caseCount: 97 },
      { id: 'old', batchId: 10, timestamp: '2026-11-17T06:12:00Z', caseCount: 41 },
    ],
    record = { batches: [original], nativeRounds: rounds },
    before = JSON.stringify(record),
    render = () =>
      renderToStaticMarkup(
        React.createElement(GenerationActivity, {
          record,
          onRetry() {},
        }),
      );
  const html = render();
  assert.equal(html, '<div class="generation-activity-list"></div>');
  assert.equal(JSON.stringify(record), before);

  original.startedAt = '2026-11-18T08:00:00Z';
  const laterFailure = render();
  assert.doesNotMatch(laterFailure, /对话候选已保存/);
  assert.match(laterFailure, /生成失败/);
  original.status = 'QUEUED';
  original.startedAt = null;
  assert.match(render(), /排队中/);
  assert.doesNotMatch(render(), /对话候选已保存/);
  original.status = 'RUNNING';
  const active = render();
  assert.match(active, /generation-spinner/);
  assert.match(active, /aria-busy="true"/);
  assert.doesNotMatch(active, /对话候选已保存/);

  original.startedAt = '2026-11-18T08:00:00Z';
  original.status = 'COMPLETED';
  assert.equal(render(), html);

  original.status = 'FAILED';
  original.nativeResultId = 'new';
  assert.equal(render(), html);
});

test('initial record fetch shows loading rather than claiming saved records are absent', () => {
  const { CaseGeneration } = load(src('CaseGeneration.tsx'));
  const html = renderToStaticMarkup(
    React.createElement(CaseGeneration, {
      project: { id: 5 },
      user: { id: 30 },
      onSessionEnd() {},
    }),
  );
  assert.match(html, /正在读取生成记录/);
  assert.match(html, /aria-busy="true"/);
  assert.ok(!html.includes('暂无用例生成记录'));
});

test('execution preparation gaps remain separate from business clarification and expose missing scope', () => {
  const { GenerationGaps } = load(src('CaseGeneration.tsx'));
  const html = renderToStaticMarkup(
    React.createElement(GenerationGaps, {
      record: {
        rawReports: [
          {
            discovery_gaps: [
              {
                kind: 'EXECUTION_SETUP',
                reason: '库存观察入口待确认',
                next_step: '执行前补齐权限',
                scenario_refs: ['b1:S1'],
              },
              {
                kind: 'UNMODELED',
                reason: '筛选功能尚未覆盖',
                next_step: '继续分析明确分支',
                scenario_refs: [],
              },
            ],
          },
        ],
      },
    }),
  );
  assert.match(html, /执行准备待补/);
  assert.match(html, /库存观察入口待确认/);
  assert.match(html, /筛选功能尚未覆盖/);
  assert.match(html, /下一步/);
  assert.doesNotMatch(html, /业务待澄清/);
});

test('compact reports show preparation and unfinished notes without inventing discovery structures', () => {
  const { GenerationGaps } = load(src('CaseGeneration.tsx'));
  const html = renderToStaticMarkup(
    React.createElement(GenerationGaps, {
      record: {
        rawReports: [
          {
            contract_version: 3,
            model_output: {
              cases: [],
              notes: [
                { kind: 'EXECUTION_SETUP', text: '库存观察权限待补', sources: ['M1-current'] },
                { kind: 'UNFINISHED', text: '数量边界尚未完成', sources: ['M2-current'] },
                { kind: 'BUSINESS_QUESTION', text: '税费公式需澄清', sources: ['M1-current'] },
              ],
              complete: false,
            },
          },
        ],
      },
    }),
  );
  assert.match(html, /执行准备待补/);
  assert.match(html, /库存观察权限待补/);
  assert.match(html, /未完成范围/);
  assert.match(html, /数量边界尚未完成/);
  assert.match(html, /M2-current/);
  assert.ok(!html.includes('税费公式需澄清'));
  assert.ok(!html.includes('下一步：'));
  const fullReport = renderToStaticMarkup(
    React.createElement(GenerationGaps, {
      includeBusiness: true,
      record: {
        rawReports: [
          {
            contract_version: 3,
            model_output: {
              cases: [],
              notes: [
                { kind: 'BUSINESS_QUESTION', text: '税费公式需澄清', sources: ['M1-current'] },
              ],
              complete: false,
            },
          },
        ],
      },
    }),
  );
  assert.match(fullReport, /简短说明与待处理范围/);
  assert.match(fullReport, /业务待澄清/);
  assert.match(fullReport, /税费公式需澄清/);
});

test('compact report details retain the entire result and expose completion as an AI declaration', () => {
  const { GenerationReportDetails } = load(src('CaseGeneration.tsx'));
  const modelOutput = {
    cases: Array.from({ length: 80 }, (_, i) => ({
      action: 'NEW',
      target: null,
      design: { ...cases.blankDesign(), title: `CASE ${i + 1}`, expected: '明确业务预期' },
      sources: ['M1-current'],
      note: '',
    })),
    notes: [{ kind: 'EXECUTION_SETUP', text: '执行账号待补', sources: ['M1-current'] }],
    complete: true,
  };
  const report = { contract_version: 3, model_output: modelOutput, suggestions: [], evidence: [] };
  const render = (r) =>
    renderToStaticMarkup(React.createElement(GenerationReportDetails, { report: r, index: 0 }));
  const html = render(report);
  assert.match(html, /80.*条建议/);
  assert.match(html, /1 条简短说明/);
  assert.match(html, /AI声明范围已完成，仍需人工审核/);
  assert.match(html, /原始用例结果与简短说明/);
  assert.match(html, /CASE 80/);
  assert.match(html, /执行账号待补/);
  assert.ok(!html.includes('规则、分支、场景及覆盖依据'));
  assert.match(
    render({ ...report, model_output: { ...modelOutput, complete: false } }),
    /AI声明范围未完成/,
  );
  const legacy = render({ contract_version: 2, rules: [{ key: 'R1' }], coverage: {} });
  assert.match(legacy, /完整本批规则、分支、场景及覆盖依据/);
  assert.match(legacy, /R1/);
});

test('compact notes keep the clarification panel from claiming there is nothing to handle', () => {
  const { GenerationWorkspace } = load(src('CaseGeneration.tsx'), {
    react: {
      ...React,
      useState: (initial) => [initial === 'suggestions' ? 'questions' : initial, () => {}],
    },
  });
  const r = {
    ...record(0),
    origin: 'SERVER',
    status: 'COMPLETED',
    outcome: 'PARTIAL',
    questions: [],
    rawReports: [
      {
        contract_version: 3,
        model_output: {
          cases: [],
          notes: [{ kind: 'UNFINISHED', text: '保存失败恢复尚未生成', sources: ['M1-current'] }],
          complete: false,
        },
      },
    ],
  };
  const render = (row) =>
    renderToStaticMarkup(
      React.createElement(
        require('react-router-dom').MemoryRouter,
        null,
        React.createElement(GenerationWorkspace, {
          project: { id: 1 },
          user: { id: 1 },
          rows: [row],
          onChange() {},
          onSessionEnd() {},
        }),
      ),
    );
  const html = render(r);
  assert.match(html, /保存失败恢复尚未生成/);
  assert.ok(!html.includes('暂无冲突与待澄清项'));
  assert.match(
    render({
      ...r,
      rawReports: [{ contract_version: 3, model_output: { cases: [], notes: [], complete: true } }],
    }),
    /暂无冲突与待澄清项/,
  );
});

test('workspace separates an active application for the open suggestion from request busy state', () => {
  let stateIndex, detailProps;
  const { GenerationWorkspace } = load(src('CaseGeneration.tsx'), {
    react: {
      ...React,
      useState: (initial) => [stateIndex++ === 8 ? 'N1' : initial, () => {}],
    },
    './CaseGenerationDialogs': {
      GenerationDetail: (props) => {
        detailProps = props;
        return null;
      },
    },
  });
  for (const [status, key, itemStatus, expected] of [
    ['QUEUED', 'N1', 'PENDING', 'QUEUED'],
    ['RUNNING', 'N1', 'PENDING', 'RUNNING'],
    ['RUNNING', 'N1', 'RUNNING', 'RUNNING'],
    ['QUEUED', 'N2', 'PENDING', undefined],
    ['RUNNING', 'N1', 'COMPLETED', undefined],
    ['COMPLETED', 'N1', 'COMPLETED', undefined],
    ['FAILED', 'N1', 'PENDING', undefined],
  ]) {
    stateIndex = 0;
    detailProps = undefined;
    renderToStaticMarkup(
      React.createElement(
        require('react-router-dom').MemoryRouter,
        null,
        React.createElement(GenerationWorkspace, {
          project: { id: 1 },
          user: { id: 1 },
          rows: [
            { ...record(2), applications: [{ status, items: [{ key, status: itemStatus }] }] },
          ],
          onChange() {},
          onSessionEnd() {},
        }),
      ),
    );
    assert.ok(detailProps);
    assert.equal(detailProps.busy, false);
    assert.equal(detailProps.applicationStatus, expected);
  }
});
