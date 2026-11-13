const { test } = require('node:test'),
  assert = require('node:assert/strict'),
  fs = require('node:fs'),
  path = require('node:path'),
  ts = require('typescript');
function load(name, overrides = {}) {
  const file = path.resolve(__dirname, '../src', name),
    exports = {};
  const source = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  new Function('exports', 'require', source)(
    exports,
    (n) =>
      overrides[n] ||
      (n.startsWith('.')
        ? load(
            path.relative(path.resolve(__dirname, '../src'), path.resolve(path.dirname(file), n)) +
              '.ts',
            overrides,
          )
        : require(n)),
  );
  return exports;
}
function row() {
  return {
    id: '10',
    projectId: 7,
    ownerId: 2,
    title: '固定生成',
    createdAt: '2026-10-12T12:00:00+08:00',
    mode: 'INITIAL',
    origin: 'SERVER',
    status: 'PREPARED',
    serverRevision: 1,
    canCancel: true,
    cancelled: false,
    scope: '选定范围',
    focus: '',
    materials: [],
    cases: [],
    caseScope: '所选空库',
    libraryRevision: 0,
    baselineId: '',
    suggestions: [],
    questions: [],
    handling: {},
    decisions: [],
    failures: [],
    failureHistory: [],
    chatDrafts: {},
    batches: [
      {
        id: 3,
        key: 'b1',
        function: '范围',
        status: 'PREPARED',
        attempts: 0,
        reason: '',
        inputBytes: 100,
        candidateAvailable: false,
      },
    ],
    limitations: [],
    outcome: '',
    inputText: '{}',
    reportText: '{}',
    rawReports: [],
    applications: [],
    planNote: '按计划调用本人AI',
    skillVersion: '1.0.0',
    aiPreview: null,
  };
}

test('summary and detail reads preserve scope, cancellation and reject foreign or mismatched identities', async () => {
  const calls = [],
    controller = new AbortController();
  const summary = {
    id: '10',
    projectId: 7,
    title: '生成摘要',
    createdAt: '2026-10-13T12:00:00+08:00',
    mode: 'INITIAL',
    status: 'COMPLETED',
    serverRevision: 2,
    hasMaterials: true,
    active: false,
    timings: [{ startedAt: '2026-10-13T12:00:00+08:00', finishedAt: '2026-10-13T13:02:03+08:00' }],
    refreshKey: 'a'.repeat(64),
  };
  let response = { items: [summary], has_more: true };
  const api = load('generationApi.ts', {
    './api/http': {
      apiRequest: async (url, options) => {
        calls.push([url, options]);
        return response;
      },
    },
  });
  const parsed = (await api.generationSummaries(7, controller.signal, 2)).items[0];
  assert.equal(parsed.id, '10');
  assert.deepEqual(parsed.timings, summary.timings);
  assert.match(calls[0][0], /page=2&summary=true$/);
  assert.equal(calls[0][1].signal, controller.signal);
  for (const patch of [
    { projectId: 8 },
    { refreshKey: 'bad' },
    { active: 'false' },
    { status: 'success' },
    { timings: [{ startedAt: 'bad', finishedAt: null }] },
    { timings: '01:02:03' },
  ]) {
    response = { items: [{ ...summary, ...patch }], has_more: false };
    await assert.rejects(
      api.generationSummaries(7, controller.signal),
      /generation_response_invalid/,
    );
  }
  response = row();
  assert.equal((await api.generationDetail(7, '10', controller.signal)).id, '10');
  assert.match(calls.at(-1)[0], /case-generation\/10$/);
  await assert.rejects(
    api.generationDetail(7, '11', controller.signal),
    /generation_response_invalid/,
  );
});

test('application failure category intent survives record parsing and rejects unknown modes', () => {
  const api = load('generationApi.ts'),
    r = row();
  r.failures = [
    {
      key: 'C1',
      caseId: null,
      version: null,
      reason: '分类已删除',
      time: '2026-10-13T12:00:00+08:00',
      categoryId: 7,
      categoryMode: 'SET',
    },
  ];
  assert.equal(api.parseGenerationRecord(r, 7).failures[0].categoryId, 7);
  assert.equal(api.parseGenerationRecord(r, 7).failures[0].categoryMode, 'SET');
  r.failures[0].categoryMode = 'MOVE_ALL';
  assert.throws(() => api.parseGenerationRecord(r, 7), /generation_response_invalid/);
});

test('direct application results keep request identity when another confirmation follows', () => {
  const api = load('generationApi.ts'),
    r = row();
  r.applications = [
    { id: 30, requestId: 'this-confirmation', status: 'COMPLETED', items: [], error: '' },
    { id: 31, requestId: 'another-confirmation', status: 'COMPLETED', items: [], error: '' },
  ];
  const parsed = api.parseGenerationRecord(r, 7);
  assert.equal(parsed.applications.find((a) => a.requestId === 'this-confirmation').id, 30);
  r.applications[0].requestId = 1;
  assert.throws(() => api.parseGenerationRecord(r, 7), /generation_response_invalid/);
});
test('server generation records reject wrong-project and malformed ownership/progress rather than showing fake success', () => {
  const api = load('generationApi.ts');
  assert.equal(api.parseGenerationRecord(row(), 7).libraryRevision, 0);
  for (const mutate of [
    (v) => (v.projectId = 8),
    (v) => (v.origin = 'PREVIEW'),
    (v) => (v.ownerId = 0),
    (v) => (v.batches[0].id = 'display-number'),
    (v) => (v.batches[0].attempts = -1),
    (v) => (v.handling.bad = [{ status: '已应用' }]),
  ]) {
    const v = row();
    mutate(v);
    assert.throws(() => api.parseGenerationRecord(v, 7));
  }
});
test('prepare/start/apply actions use shared HTTP, caller cancellation and stable request/selected versions', async () => {
  let call;
  const api = load('generationApi.ts', {
    './api/http': {
      apiRequest: async (url, init) => {
        call = { url, init };
        return row();
      },
      apiErrorMessage: () => '',
    },
  });
  const c = new AbortController(),
    body = {
      request_id: 'fixed-request',
      confirmed: true,
      items: [{ key: 'b1:A1', draft_revision: 2, target_version: 4 }],
    };
  await api.generationAction(7, '/10/applications', body, c.signal);
  assert.equal(call.url, '/api/projects/7/case-generation/10/applications');
  assert.equal(call.init.signal, c.signal);
  assert.equal(call.init.method, 'POST');
  assert.deepEqual(JSON.parse(call.init.body), body);
  assert.equal(call.init.timeoutMs, 600000);
  await api.generationAction(7, '/prepare', body, c.signal);
  assert.equal(call.init.timeoutMs, 600000);
  assert.equal(call.init.signal, c.signal);
  assert.deepEqual(JSON.parse(call.init.body), body);
});

test('prepare timeout stays uncertain and precise quote or GitHub errors are readable', async () => {
  let calls = 0;
  const api = load('generationApi.ts', {
    './api/http': {
      ...load('api/http.ts'),
      apiRequest: async () => {
        calls++;
        throw new DOMException('Timed out', 'TimeoutError');
      },
    },
  });
  await assert.rejects(api.generationAction(7, '/prepare', {}), /generation_prepare_timeout/);
  assert.equal(calls, 1);
  const end = () => assert.fail('validation failure must not expire session');
  for (const [code, expected] of [
    ['generation_evidence_quote_mismatch', /摘录.*固定资料原文不一致/],
    ['github_connection_failed', /无法连接 GitHub/],
    ['generation_prepare_timeout', /后台可能仍在准备.*刷新记录核对/],
  ]) {
    assert.match(api.generationError(new Error(code), end), expected);
    assert.equal(api.generationFailure(code), api.generationError(new Error(code), end));
  }
});
test('generation response parser keeps all 512 suggestions and blocks execution fields in designs', () => {
  const api = load('generationApi.ts'),
    v = row(),
    design = load('caseApi.ts').blankDesign();
  v.suggestions = Array.from({ length: 512 }, (_, n) => ({
    key: `b1:A${n}`,
    kind: 'NEW',
    function: '订单',
    functionRef: 'F',
    design: { ...design, title: `场景${n}`, steps: '提交', expected: '订单处于待处理' },
    before: null,
    generated: null,
    caseId: null,
    baseVersion: null,
    reason: '当前依据',
    blocked: false,
    evidence: [{ source: 'M', segment: 's', side: 'CURRENT', quote: '待处理' }],
  }));
  assert.equal(api.parseGenerationRecord(v, 7).suggestions.length, 512);
  v.suggestions[0].design.result = '通过';
  assert.throws(() => api.parseGenerationRecord(v, 7), /非法字段/);
});

test('generation records preserve quote warnings without changing review state and reject malformed warning values', () => {
  const api = load('generationApi.ts'),
    v = row(),
    design = load('caseApi.ts').blankDesign(),
    evidence = {
      source: 'M',
      segment: '',
      side: 'CURRENT',
      quote: '待数为0',
      verifiedQuote: false,
      quoteWarning: '摘录未匹配固定原文，请人工核对。',
    };
  v.suggestions = [
    {
      key: 'b1:A1',
      kind: 'NEW',
      function: '订单',
      functionRef: 'F',
      design: { ...design, title: '数量核对', steps: '提交', expected: '保存本次记录' },
      before: null,
      generated: null,
      caseId: null,
      baseVersion: null,
      reason: '当前依据',
      blocked: false,
      evidence: [evidence],
    },
  ];
  const parsed = api.parseGenerationRecord(v, 7);
  assert.equal(parsed.suggestions[0].evidence[0].quote, evidence.quote);
  assert.equal(parsed.suggestions[0].evidence[0].quoteWarning, evidence.quoteWarning);
  assert.equal(parsed.suggestions[0].evidence[0].verifiedQuote, false);
  assert.equal(parsed.suggestions[0].blocked, false);
  for (const invalid of [null, 1, true, {}, [], 'bad\0warning']) {
    v.suggestions[0].evidence[0] = { ...evidence, quoteWarning: invalid };
    assert.throws(() => api.parseGenerationRecord(v, 7), /generation_response_invalid/);
  }
  v.suggestions[0].evidence[0] = {
    source: 'M',
    segment: 's',
    side: 'CURRENT',
    quote: '仅来源引用',
  };
  assert.equal(api.parseGenerationRecord(v, 7).suggestions[0].evidence[0].quoteWarning, undefined);
});

test('generation progress validates timestamps and numeric diagnostics at the response boundary', () => {
  const api = load('generationApi.ts'),
    value = row();
  value.batches[0].startedAt = '2026-10-12T15:24:16+08:00';
  value.batches[0].diagnostics = {
    phase: 'receiving',
    elapsed_seconds: 1.5,
    message: 'drop arbitrary prose',
  };
  assert.deepEqual(api.parseGenerationRecord(value, 7).batches[0].diagnostics, {
    phase: 'receiving',
    elapsed_seconds: 1.5,
  });
  value.batches[0].diagnostics.elapsed_seconds = -1;
  assert.throws(() => api.parseGenerationRecord(value, 7));
  value.batches[0].diagnostics = {};
  value.batches[0].startedAt = 'invalid';
  assert.throws(() => api.parseGenerationRecord(value, 7));
});

test('generation candidate issues preserve both duplicate values alongside otherwise valid results', () => {
  const api = load('generationApi.ts', { './api/http': {} }),
    value = row();
  value.candidateIssues = [
    {
      key: '3:case-2',
      issueId: 'case-2',
      batchId: 3,
      kind: 'case',
      ordinal: 2,
      status: 'PENDING',
      reason: 'risk_json_invalid',
      rawJson: '{"priority":"P2","priority":"P1"}',
      correctedJson: '',
      duplicates: [{ path: 'design.priority', values: ['"P2"', '"P1"'] }],
      note: '',
      canEdit: true,
    },
  ];
  const parsed = api.parseGenerationRecord(value, 7);
  assert.deepEqual(parsed.candidateIssues[0].duplicates[0].values, ['"P2"', '"P1"']);
  value.candidateIssues[0].status = 'SUCCESS';
  assert.throws(() => api.parseGenerationRecord(value, 7));
});
