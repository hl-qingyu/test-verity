const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load(file) {
  const exports = {};
  const code = compileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  evaluateModule(
    code,
    (name) =>
      name.startsWith('.') ? load(path.resolve(path.dirname(file), name + '.ts')) : require(name),
    exports,
  );
  return exports;
}
const api = load(path.resolve(__dirname, '../src/changeAnalysisApi.ts'));
test('new-request validation is distinguished from AI result contract failure', () => {
  const end = () => assert.fail('validation must not end the session');
  assert.match(api.changeError(new Error('change_request_invalid'), end), /请求.*字段/);
  assert.match(api.changeError(new Error('change_json_invalid'), end), /请求JSON编码/);
  assert.match(api.changeError(new Error('change_contract_invalid'), end), /结果结构/);
  assert.match(api.changeError(new Error('code_private_key_content'), end), /私钥标记或疑似密钥/);
});

function fixture(name = 'code') {
  const root = path.resolve(__dirname, '../../skill/change-impact/examples');
  const input = JSON.parse(fs.readFileSync(path.join(root, `${name}-input.json`), 'utf8'));
  const report = JSON.parse(fs.readFileSync(path.join(root, `${name}-report.json`), 'utf8'));
  return {
    id: 4,
    project_id: 1,
    title: '固定变更',
    focus: input.focus,
    mode: input.mode,
    targets: input.targets,
    status: 'COMPLETED',
    error_code: '',
    revision: 1,
    created_at: '2026-10-10T00:00:00Z',
    updated_at: '2026-10-10T00:00:00Z',
    origin: 'IMPORT',
    input,
    report,
    handling: {},
    selections: {},
  };
}
test('empty-input failures retain retry availability and preparation semantics', () => {
  const raw = {
    ...fixture(),
    origin: 'AI',
    status: 'FAILED',
    input: {},
    report: {},
    can_retry: true,
    retry_preparation: true,
    error_code: 'github_connection_failed',
  };
  const record = api.parseChangeDetail(raw, 1);
  assert.equal(record.can_retry, true);
  assert.equal(record.retry_preparation, true);
  assert.equal(record.status, 'FAILED');
  assert.equal(record.changes.length, 0);
});
test('known AI gateway timeout shows the saved failure and keeps fixed-input manual retry', () => {
  const raw = {
    ...fixture(),
    origin: 'AI',
    status: 'FAILED',
    report: {},
    can_retry: true,
    retry_preparation: false,
    error_code: 'ai_gateway_timeout',
  };
  const record = api.parseChangeDetail(raw, 1);
  assert.equal(record.status, 'FAILED');
  assert.equal(record.can_retry, true);
  assert.equal(record.retry_preparation, false);
  assert.deepEqual(JSON.parse(record.inputText), raw.input);
  const end = () => assert.fail('AI gateway timeout must not end the session');
  const message = api.changeError(new Error(record.error_code), end);
  assert.match(message, /AI中转.*超时.*504/);
  assert.match(message, /未取得完整结果.*未自动重试/);
  assert.doesNotMatch(message, /操作结果尚未确认/);
  assert.match(api.changeError(new Error('unrecognized-error'), end), /操作结果尚未确认/);
});

test('evidence validation failures keep the raw candidate download flag', () => {
  const raw = {
    ...fixture(),
    origin: 'AI',
    status: 'FAILED',
    report: {},
    error_code: 'change_evidence_invalid',
    candidate_available: true,
    can_retry: true,
  };
  const record = api.parseChangeDetail(raw, 1);
  assert.equal(record.candidate_available, true);
  assert.match(
    api.changeError(new Error(record.error_code), () => {}),
    /下载原始候选核对/,
  );
});

test('three-mode adapter preserves original report, dual evidence, attribution and every result group', () => {
  for (const mode of ['code', 'requirement', 'prototype']) {
    const raw = fixture(mode),
      fixed = JSON.stringify(raw.report),
      record = api.parseChangeDetail(raw, 1);
    assert.equal(record.mode, raw.mode);
    assert.equal(record.changes.length, raw.report.changes.length);
    assert.equal(
      record.impacts.length,
      ['function_impacts', 'code_impacts', 'case_impacts', 'risks', 'historical_reviews'].reduce(
        (n, g) => n + raw.report[g].length,
        0,
      ),
    );
    assert.deepEqual(JSON.parse(record.reportText), raw.report);
    assert.equal(JSON.stringify(raw.report), fixed);
    assert.ok(record.changes[0].before.includes(raw.report.evidence[0].excerpt));
  }
  const record = api.parseChangeDetail(fixture(), 1);
  assert.equal(record.impacts.find((r) => r.key === 'R1').cause, 'pre_existing');
  assert.ok(record.impacts.find((r) => r.key === 'R1').details.some((v) => v.label === '根因'));
  for (const mutate of [
    (r) => (r.project_id = 2),
    (r) => (r.report.request_id = 'wrong'),
    (r) => (r.report.contract_version = 1),
    (r) => (r.status = 'fake'),
    (r) => (r.report.risks[0].key = 'C1'),
  ]) {
    const raw = fixture();
    mutate(raw);
    assert.throws(() => api.parseChangeDetail(raw, 1), /change_response_invalid/);
  }
});
test('opaque result keys never inherit handling properties', () => {
  const raw = fixture();
  raw.report.risks[0].key = 'constructor';
  const record = api.parseChangeDetail(raw, 1);
  assert.equal(Object.getPrototypeOf(record.handling), null);
  assert.equal(record.handling.constructor, undefined);
  assert.equal(
    record.impacts.find((r) => r.key === 'constructor').title,
    raw.report.risks[0].title,
  );
});

test('local and link versions display capture time to seconds while preserving frozen refs and Git versions', () => {
  for (const sourceKind of ['LOCAL', 'LINK', 'GITHUB']) {
    const raw = fixture();
    for (const [index, snapshot] of raw.input.snapshots.entries()) {
      snapshot.provenance.source_kind = sourceKind;
      snapshot.provenance.captured_at = `2026-10-27T00:09:0${index + 1}Z`;
    }
    const original = JSON.stringify(raw.input);
    const record = api.parseChangeDetail(raw, 1);
    assert.equal(
      record.pairs[0].before,
      sourceKind === 'GITHUB'
        ? raw.input.snapshots[0].provenance.version_ref
        : '2026-10-27 08:09:01',
    );
    assert.equal(
      record.pairs[0].after,
      sourceKind === 'GITHUB'
        ? raw.input.snapshots[1].provenance.version_ref
        : '2026-10-27 08:09:02',
    );
    assert.equal(JSON.stringify(raw.input), original);
    raw.input.snapshots[0].provenance.captured_at = 'unknown';
    assert.equal(
      api.parseChangeDetail(raw, 1).pairs[0].before,
      raw.input.snapshots[0].provenance.version_ref,
    );
  }
});

test('page projections preserve all three modes, scope and displayed evidence without fixed bodies', () => {
  for (const mode of ['code', 'requirement', 'prototype']) {
    const full = fixture(mode);
    const expected = api.parseChangeDetail(full, 1);
    const projected = structuredClone(full);
    const pick = (value, keys) => Object.fromEntries(keys.map((key) => [key, value[key] ?? null]));
    projected.input.snapshots = full.input.snapshots.map((snapshot) => ({
      ...pick(snapshot, ['snapshot_ref', 'name', 'provenance']),
      units: snapshot.units.map((unit) => pick(unit, ['unit_id', 'path'])),
    }));
    projected.input.cases = full.input.cases.map((item) =>
      pick(item, ['case_id', 'display_number', 'title', 'design_version']),
    );
    projected.input.historical_items = full.input.historical_items.map((item) =>
      pick(item, ['module', 'report_id', 'item_key', 'title', 'review_warnings']),
    );
    const actual = api.parseChangeDetail(projected, 1);
    for (const key of ['pairs', 'context', 'changes', 'impacts', 'regressions', 'limitations'])
      assert.deepEqual(actual[key], expected[key], `${mode}: ${key}`);
  }
});

test('change requests retain project/record identity, cancellation, backend errors and expired-session handling', async () => {
  const original = global.fetch,
    calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify(fixture()), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  try {
    const c = new AbortController(),
      body = JSON.stringify({ revision: 1, item_key: 'R1', status: 'CONFIRMED', note: '人工核对' });
    const record = await api.changeDetail('/api/projects/1/change-analysis/4/handling', 1, {
      method: 'POST',
      body,
      signal: c.signal,
    });
    assert.equal(record.id, '4');
    const projected = fixture();
    projected.input_projected = true;
    for (const snapshot of projected.input.snapshots)
      for (const unit of snapshot.units) delete unit.segments;
    global.fetch = async () => new Response(JSON.stringify(projected), { status: 200 });
    const pageRecord = await api.changeDetail(
      '/api/projects/1/change-analysis/4?page_view=true',
      1,
    );
    assert.deepEqual(pageRecord.changes, record.changes);
    assert.deepEqual(pageRecord.impacts, record.impacts);
    assert.deepEqual(pageRecord.pairs, record.pairs);
    await assert.rejects(
      api.changeDetail('/api/projects/1/change-analysis/9?page_view=true', 1),
      /change_response_invalid/,
    );
    assert.equal(calls[0].options.body, body);
    assert.equal(calls[0].options.method, 'POST');
    c.abort();
    assert.equal(calls[0].options.signal.aborted, true);
    await assert.rejects(
      api.changeDetail('/api/projects/1/change-analysis/9', 1),
      /change_response_invalid/,
    );
    global.fetch = async () =>
      new Response(JSON.stringify({ detail: 'change_handling_changed' }), { status: 409 });
    await assert.rejects(
      api.changeDetail('/api/projects/1/change-analysis/4/handling', 1, { method: 'POST' }),
      /change_handling_changed/,
    );
    global.fetch = async () => new Response('{}', { status: 401 });
    await assert.rejects(
      api.changeDetail('/api/projects/1/change-analysis/4', 1),
      /not_authenticated/,
    );
    let ended = false;
    api.changeError(new Error('not_authenticated'), () => (ended = true));
    assert.equal(ended, true);
  } finally {
    global.fetch = original;
  }
});
