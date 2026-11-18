const { test } = require('node:test'),
  assert = require('node:assert/strict'),
  fs = require('node:fs'),
  path = require('node:path'),
  ts = require('typescript');
function load(transport) {
  const exports = {};
  const code = ts.transpileModule(
    fs.readFileSync(path.resolve(__dirname, '../src/nativeResultApi.ts'), 'utf8'),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
  ).outputText;
  new Function('require', 'exports', code)(
    (name) => (name === './api/http' ? transport : require(name)),
    exports,
  );
  return exports;
}
const id = 'a'.repeat(64);
test('native results use shared read transport, preserve cancellation and bind previews to the selected result', async () => {
  const calls = [],
    controller = new AbortController();
  let body = {
    items: [
      { id, timestamp: '2026-11-17T06:12:00Z', case_count: 41, note_count: 9, complete: false },
    ],
  };
  const api = load({
    apiRequest: async (url, options) => {
      calls.push([url, options]);
      return body;
    },
  });
  const values = await api.nativeResults('/terminal', controller.signal);
  assert.equal(values[0].case_count, 41);
  assert.equal(calls[0][1].signal, controller.signal);
  body = { id, raw_json: '{"cases":[]}', valid_cases: 1, issues: 1, can_save: true };
  assert.equal((await api.nativeResultPreview('/terminal', id, controller.signal)).issues, 1);
  assert.equal(calls[1][0], '/terminal/results/' + id);
  body = { ...body, id: 'b'.repeat(64) };
  await assert.rejects(api.nativeResultPreview('/terminal', id, controller.signal));
  assert.ok(
    calls.every(([, options]) => !options.method),
    'listing and preview cannot create model/library writes',
  );
});
test('malformed dates, counts, duplicate identities and permission flags are rejected', async () => {
  let body;
  const api = load({ apiRequest: async () => body });
  const base = {
    id,
    timestamp: '2026-11-17T06:12:00Z',
    case_count: 41,
    note_count: 9,
    complete: false,
  };
  for (const patch of [
    { id: '../state' },
    { timestamp: 'invalid' },
    { case_count: -1 },
    { complete: 'false' },
  ]) {
    body = { items: [{ ...base, ...patch }] };
    await assert.rejects(api.nativeResults('/terminal', new AbortController().signal));
  }
  body = { items: [base, base] };
  await assert.rejects(api.nativeResults('/terminal', new AbortController().signal));
  body = { id, raw_json: '{}', valid_cases: 1, issues: 0, can_save: 'yes' };
  await assert.rejects(api.nativeResultPreview('/terminal', id, new AbortController().signal));
});

test('round filtering isolates candidates, questions and issues while retaining all review history', () => {
  const file = path.resolve(__dirname, '../src/generationPage.ts'),
    exports = {};
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  new Function('require', 'exports', code)(
    () => ({ blankDesign: () => ({}), DESIGN_FIELDS: [], CASE_COLUMNS: [] }),
    exports,
  );
  const a = 'a'.repeat(64),
    b = 'b'.repeat(64),
    record = {
      id: '2',
      suggestions: [
        { key: 'A:C1', nativeResultId: a },
        { key: 'B:C1', nativeResultId: b },
        { key: 'base:C1' },
      ],
      questions: [
        { key: 'A:Q1', nativeResultId: a },
        { key: 'B:Q1', nativeResultId: b },
      ],
      candidateIssues: [{ key: 'B:bad', nativeResultId: b }],
      rawReports: [{ batch_ref: 'A' }, { batch_ref: 'B' }, { batch_ref: 'base' }],
      nativeRounds: [
        { id: a, batchRef: 'A' },
        { id: b, batchRef: 'B' },
      ],
      handling: { 'A:C1': [{ status: '已应用' }] },
    };
  const before = JSON.stringify(record),
    one = exports.generationRoundRecord(record, a),
    two = exports.generationRoundRecord(record, b);
  assert.deepEqual(
    one.suggestions.map((s) => s.key),
    ['A:C1'],
  );
  assert.deepEqual(
    two.suggestions.map((s) => s.key),
    ['B:C1'],
  );
  assert.equal(one.candidateIssues.length, 0);
  assert.equal(two.candidateIssues.length, 1);
  assert.equal(one.rawReports[0].batch_ref, 'A');
  assert.equal(one.handling, record.handling);
  assert.equal(exports.generationRoundRecord(record, '').suggestions.length, 3);
  assert.equal(exports.generationRoundRecord(record, '__initial__').suggestions[0].key, 'base:C1');
  assert.equal(JSON.stringify(record), before);
});
