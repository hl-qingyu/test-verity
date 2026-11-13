const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load(file) {
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  new Function('exports', 'require', code)(exports, (name) =>
    load(
      path.resolve(
        path.dirname(file),
        name + (fs.existsSync(path.resolve(path.dirname(file), name + '.ts')) ? '.ts' : '.tsx'),
      ),
    ),
  );
  return exports;
}
const api = load(path.resolve(__dirname, '../src/caseApi.ts'));

test('case response contracts preserve blank fields, P4 and project-owned category data', () => {
  const row = {
    ...api.blankDesign(),
    id: 8,
    number: 'Login_003',
    category_id: null,
    version_id: 9,
    version: 1,
    serial: 1,
    result: '',
    tester: '',
    review_status: '待审核',
    result_origin: 'IMPORT',
    source_kind: 'IMPORT',
    priority: 'P4',
  };
  const data = {
    revision: 2,
    next_number: 4,
    categories: [{ id: 1, name: '用户端', count: 0 }],
    items: [row],
    total: 1,
    page: 1,
    page_size: 10,
  };
  assert.deepEqual(api.parseCaseList(data), data);
  assert.throws(
    () => api.parseCaseList({ ...data, items: [{ ...row, title: null }] }),
    /case_response_invalid/,
  );
  assert.throws(
    () => api.parseCaseMetadata({ ...data, categories: [{ id: 1, name: '用户端' }] }),
    /case_response_invalid/,
  );
  const info = { id: 1, filename: 'a.csv', preview_revision: 0, committed: false };
  assert.deepEqual(api.parseCaseImportInfo(info), info);
  assert.throws(() => api.parseCaseImportInfo({ ...info, id: null }), /case_response_invalid/);
  const preview = {
    preview_revision: 1,
    revision: 2,
    total: 1,
    skipped: 0,
    duplicate_count: 1,
    errors: [],
    warnings: [],
    sheets: [{ name: 'CSV', header_row: 1 }],
    items: [
      {
        key: '0:2',
        sheet: 'CSV',
        row: 2,
        values: { result: '失败', priority: 'P4' },
        matches: [row],
        match_count: 1,
      },
    ],
  };
  assert.deepEqual(api.parseCaseImportPreview(preview), preview);
  assert.throws(
    () =>
      api.parseCaseImportPreview({
        ...preview,
        items: [{ ...preview.items[0], matches: [{ ...row, number: null }] }],
      }),
    /case_response_invalid/,
  );
});

test('case search and export retain protected binary response and errors', async () => {
  const http = load(path.resolve(__dirname, '../src/api/http.ts'));
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (url, options) => {
      assert.equal(url, '/api/projects/1/cases/export');
      assert.equal(options.method, 'POST');
      assert.ok(options.signal);
      return new Response(new Uint8Array([80, 75, 3, 4]));
    };
    const blob = await http.apiDownload('/api/projects/1/cases/export', {
      method: 'POST',
      body: '{}',
    });
    assert.equal(blob.size, 4);
    globalThis.fetch = async () => new Response('not json', { status: 401 });
    await assert.rejects(http.apiDownload('/api/projects/1/cases/export'), /not_authenticated/);
  } finally {
    globalThis.fetch = original;
  }
});

test('inline patches preserve untouched fields and permit explicit clearing across pages', () => {
  const first = { ...api.blankDesign(), id: 1, number: 1, tester: '原人员', result: '通过' };
  const last = { ...first, id: 12, number: 12, title: '原标题' };
  assert.deepEqual(api.caseChanges(first, { ...first, tester: '' }), { tester: '' });
  assert.deepEqual(api.caseChanges(last, { ...last, title: '新标题', number: 999 }), {
    title: '新标题',
  });
  assert.deepEqual(api.caseChanges(first, { ...first }), {});
  assert.throws(() =>
    api.parseBatchResult({ revision: 2, next_number: 13, categories: [], updated: '12' }),
  );
  assert.equal(
    api.parseBatchResult({ revision: 2, next_number: 13, categories: [], updated: 12 }).updated,
    12,
  );
});
