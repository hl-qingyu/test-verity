const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

// Run the real TypeScript module with native Node fetch/AbortSignal; no extra test framework.
function load(file) {
  const source = fs.readFileSync(file, 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exported = {};
  new Function('exports', 'require', compiled)(exported, (name) =>
    load(
      path.resolve(
        path.dirname(file),
        name + (fs.existsSync(path.resolve(path.dirname(file), name + '.ts')) ? '.ts' : '.tsx'),
      ),
    ),
  );
  return exported;
}

test('caller cancellation and timeout both work; 401 and HTTP errors keep their codes', async () => {
  const originalFetch = globalThis.fetch;
  const originalTimeout = AbortSignal.timeout;
  const { apiRequest, apiErrorMessage } = load(path.resolve(__dirname, '../src/api/http.ts'));
  let timeoutController;
  AbortSignal.timeout = () => {
    timeoutController = new AbortController();
    return timeoutController.signal;
  };
  try {
    globalThis.fetch = (url, options) =>
      new Promise((resolve, reject) => {
        assert.equal(url, '/api/projects');
        assert.equal(options.headers.get('X-Test'), 'kept');
        options.signal.addEventListener('abort', () => reject(options.signal.reason), {
          once: true,
        });
      });
    const caller = new AbortController();
    const first = apiRequest('/api/projects', {
      signal: caller.signal,
      headers: new Headers({ 'X-Test': 'kept' }),
    });
    timeoutController.abort(new Error('timeout-reached'));
    await assert.rejects(first, /timeout-reached/);
    assert.equal(caller.signal.aborted, false);
    const second = apiRequest('/api/projects', {
      signal: caller.signal,
      headers: { 'X-Test': 'kept' },
    });
    caller.abort(new Error('caller-cancelled'));
    await assert.rejects(second, /caller-cancelled/);
    globalThis.fetch = async () => new Response('not json', { status: 401 });
    await assert.rejects(apiRequest('/api/projects'), /not_authenticated/);
    let expired = false;
    apiErrorMessage(
      new Error('not_authenticated'),
      () => {
        expired = true;
      },
      {},
    );
    assert.equal(expired, true);
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ detail: 'project_changed' }), { status: 409 });
    await assert.rejects(apiRequest('/api/projects'), /project_changed/);
    globalThis.fetch = async () => new Response(JSON.stringify([{ id: 1 }]));
    assert.deepEqual(await apiRequest('/api/projects'), [{ id: 1 }]);
  } finally {
    globalThis.fetch = originalFetch;
    AbortSignal.timeout = originalTimeout;
  }
});

test('GitHub discovery validates repository owners and groups mixed-owner results', () => {
  const { parseProbeResult, groupRepositories } = load(
    path.resolve(__dirname, '../src/githubApi.ts'),
  );
  const repository = {
    github_id: 1,
    full_name: 'alice/server',
    owner_type: 'User',
    default_branch: 'main',
    private: true,
  };
  const result = {
    github_login: 'alice',
    repositories: [
      repository,
      { ...repository, github_id: 2, full_name: 'team/app', owner_type: 'Organization' },
    ],
    receipt: 'signed',
    has_more: false,
    page: 1,
  };
  assert.deepEqual(
    groupRepositories(parseProbeResult(result).repositories).map(([name, repos]) => [
      name,
      repos.length,
    ]),
    [
      ['个人 · alice', 1],
      ['组织 · team', 1],
    ],
  );
  assert.deepEqual(groupRepositories([]), []);
  for (const malformed of [
    null,
    {},
    { ...result, repositories: [{ ...repository, owner_type: 'unknown' }] },
    { ...result, repositories: [{ ...repository, full_name: '../injected' }] },
  ]) {
    assert.throws(() => parseProbeResult(malformed), /github_invalid_response/);
  }
});

test('document requests preserve binary uploads and reject inconsistent file ownership', async () => {
  const { parseLibrary, libraryRequest } = load(path.resolve(__dirname, '../src/documentApi.ts'));
  const version = {
    id: 1,
    document_id: 3,
    number: 1,
    filename: 'large.txt',
    extension: 'txt',
    size: 21 * 1024 * 1024,
    sha256: 'a'.repeat(64),
    created_at: '2026-09-12T00:00:00Z',
    created_by: '测试账号',
  };
  const data = {
    revision: 1,
    groups: [{ id: 2, name: '截图' }],
    documents: [{ id: 3, group_id: 2, position: 0, current: version }],
  };
  assert.deepEqual(parseLibrary(data), data);
  assert.throws(
    () => parseLibrary({ ...data, documents: [{ ...data.documents[0], group_id: 999 }] }),
    /document_response_invalid/,
  );
  assert.throws(
    () =>
      parseLibrary({
        ...data,
        documents: [{ ...data.documents[0], current: { ...version, document_id: 4 } }],
      }),
    /document_response_invalid/,
  );
  const original = globalThis.fetch;
  const body = new Blob(['file content']);
  try {
    globalThis.fetch = async (_, options) => {
      assert.equal(options.headers.get('Content-Type'), 'application/octet-stream');
      assert.equal(options.body, body);
      return new Response(JSON.stringify(data));
    };
    assert.deepEqual(
      await libraryRequest('/api/projects/1/documents/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body,
      }),
      data,
    );
  } finally {
    globalThis.fetch = original;
  }
});

test('document link responses preserve version identity and reject malformed bindings', () => {
  const { parseLinks, linkKey } = load(path.resolve(__dirname, '../src/documentApi.ts'));
  const target = {
    id: 7,
    document_id: 3,
    number: 1,
    filename: '说明.md',
    extension: 'md',
    size: 12,
    sha256: 'a'.repeat(64),
    created_at: '2026-09-12T00:00:00Z',
    created_by: '检查账号',
  };
  const binding = { id: 9, revision: 1, target, latest_number: 2, inherited: true };
  const value = {
    source_version_id: 8,
    revision: 4,
    editable: true,
    truncated: false,
    links: [{ href: 'doc/%E8%AF%B4%E6%98%8E.md', label: '新标题', binding }],
  };
  assert.deepEqual(parseLinks(value), value);
  assert.equal(linkKey(value.links[0].href), 'doc/说明.md');
  assert.equal(linkKey('bad%XX%E4%BD%BF'), 'bad%XX%E4%BD%BF');
  for (const bad of [
    { ...binding, latest_number: 0 },
    { ...binding, inherited: 'true' },
    { ...binding, target: { ...target, id: null } },
  ]) {
    assert.throws(
      () => parseLinks({ ...value, links: [{ ...value.links[0], binding: bad }] }),
      /document_response_invalid/,
    );
  }
});
