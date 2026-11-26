const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(name) {
  const file = path.resolve(__dirname, '../src', name);
  const compiled = compileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exported = {};
  evaluateModule(
    compiled,
    (dependency) =>
      load(
        path.relative(
          path.resolve(__dirname, '../src'),
          path.resolve(path.dirname(file), dependency + '.ts'),
        ),
      ),
    exported,
  );
  return exported;
}
const files = load('localCodeFiles.ts');

test('snapshot names use Shanghai capture time to seconds and preserve legacy and same-second identities', () => {
  const { snapshotTime } = load('snapshotTime.ts');
  const { snapshotName } = load('localCodeStore.ts');
  assert.equal(snapshotTime('2026-10-26T16:00:01.999Z'), '2026-10-27 00:00:01');
  assert.equal(snapshotTime('2026-10-27T08:09:03+08:00'), '2026-10-27 08:09:03');
  assert.equal(snapshotTime('unknown'), '');
  assert.equal(
    snapshotName({ sequence: 7, foundAt: '2026-10-27T00:09:03Z' }),
    '2026-10-27 08:09:03',
  );
  assert.equal(snapshotName({ sequence: 7, foundAt: 'unknown' }), '读取 #7');
});

test('actual file tree renders nested and empty directories once without self-recursion', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const source = fs.readFileSync(path.resolve(__dirname, '../src/LocalCode.tsx'), 'utf8');
  const treeSource = source.slice(
    source.indexOf('function FileTree('),
    source.indexOf('function LocalHistory('),
  );
  const compiled = compileModule(treeSource, {
    compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const Tree = new Function('React', 'inScope', compiled + ';return FileTree;')(
    React,
    files.inScope,
  );
  const tree = {
    directories: ['src/', 'src/pages/', 'empty/'],
    files: [{ path: 'src/pages/index.ts' }, { path: 'root.ts' }],
    excluded: 0,
  };
  const options = { tree, scope: ['src/'], search: '', disabled: false, toggle() {} };
  const html = renderToStaticMarkup(React.createElement(Tree, options));
  assert.equal((html.match(/<details/g) || []).length, 3);
  assert.equal((html.match(/index\.ts/g) || []).length, 1);
  assert.equal((html.match(/root\.ts/g) || []).length, 1);
  const filtered = renderToStaticMarkup(
    React.createElement(Tree, { ...options, search: 'index.ts' }),
  );
  assert.equal((filtered.match(/<details/g) || []).length, 2);
  assert.ok(filtered.includes('index.ts'));
  assert.ok(!filtered.includes('empty/'));
  assert.equal(
    renderToStaticMarkup(
      React.createElement(Tree, { ...options, tree: { directories: [], files: [] } }),
    ),
    '',
  );
});
const file = (name, text) => ({
  kind: 'file',
  name,
  async getFile() {
    return new File([text], name, { lastModified: 1 });
  },
});
const directory = (name, children) => ({
  kind: 'directory',
  name,
  async queryPermission() {
    return 'granted';
  },
  async requestPermission() {
    return 'granted';
  },
  async *values() {
    yield* children;
  },
});
const signal = () => new AbortController().signal;

test('local directory reads fresh files, excludes secrets before opening, and detects real differences', async () => {
  const children = [
    file('old.ts', 'a'),
    file('removed.ts', 'gone'),
    directory('.git', [file('secret', 'private')]),
    file('.env', 'secret'),
    directory('src', [file('app.ts', 'one')]),
  ];
  const root = directory('my-code', children);
  const before = await files.readSelection(
    await files.scanDirectory(root, signal()),
    ['/'],
    signal(),
  );
  assert.deepEqual(Object.keys(before.files).sort(), ['old.ts', 'removed.ts', 'src/app.ts']);
  children.splice(0, 2, file('old.ts', 'changed'), file('new.ts', 'new'));
  const after = await files.readSelection(
    await files.scanDirectory(root, signal()),
    ['/'],
    signal(),
  );
  const changes = files.compareReads(before, after, ['/'], ['/']);
  assert.deepEqual(
    changes.map((c) => [c.path, c.kind]),
    [
      ['new.ts', '新增'],
      ['old.ts', '修改'],
      ['removed.ts', '删除'],
    ],
  );
  assert.equal(before.files['old.ts'].content, 'a');
  assert.deepEqual(files.compareReads(after, after, ['/'], ['/']), []);
});

test('scope changes and unreadable content never masquerade as file deletion', async () => {
  const root = directory('code', [file('a.ts', 'a'), file('b.ts', 'b')]);
  const tree = await files.scanDirectory(root, signal());
  const before = await files.readSelection(tree, ['/'], signal());
  const after = await files.readSelection(tree, ['a.ts'], signal());
  assert.deepEqual(
    files.compareReads(before, after, ['/'], ['a.ts']).map((c) => c.kind),
    ['移出范围'],
  );
  assert.deepEqual(
    files.compareReads(after, before, ['a.ts'], ['/']).map((c) => c.kind),
    ['纳入范围'],
  );
  const changed = directory('code', [
    file('a.ts', '\0binary'),
    file('b.ts', new Uint8Array([255, 254, 255])),
  ]);
  const skipped = await files.readSelection(
    await files.scanDirectory(changed, signal()),
    ['/'],
    signal(),
  );
  assert.equal(Object.keys(skipped.skipped).length, 2);
  assert.ok(files.compareReads(before, skipped, ['/'], ['/']).every((c) => c.kind === '未能比较'));
  const denied = directory('code', []);
  denied.queryPermission = async () => 'denied';
  await assert.rejects(files.scanDirectory(denied, signal()), /directory_denied/);
  const broken = directory('code', []);
  broken.values = () => ({
    [Symbol.asyncIterator]() {
      return this;
    },
    async next() {
      throw Error('disk failure');
    },
  });
  await assert.rejects(files.scanDirectory(broken, signal()), /disk failure/);
});

test('cancellation and unsafe path guard fail closed', async () => {
  assert.equal(files.inScope('src/new.ts', ['src/']), true);
  assert.equal(files.inScope('src-new/file.ts', ['src/']), false);
  for (const name of ['.ENV.local', 'node_modules/a.js', 'id_rsa', '.ssh/config', 'cert.pem'])
    assert.equal(files.excludedPath(name), true);
  await assert.rejects(
    files.scanDirectory(directory('code', [file('../escape', 'x')]), signal()),
    /directory_invalid_entry/,
  );
  const abort = new AbortController();
  abort.abort();
  await assert.rejects(files.scanDirectory(directory('code', [file('a', 'a')]), abort.signal));
});

test('local-code API sends metadata only and rejects wrong-project server responses', async () => {
  const api = load('localCodeApi.ts');
  const original = global.fetch;
  const seen = [];
  const row = {
    id: 1,
    project_id: 4,
    owner_id: 2,
    client_id: '11111111-1111-1111-1111-111111111111',
    name: 'local',
    directory_name: 'code',
    kind: 'PROTOTYPE',
    version: 1,
    created_at: '2026-09-14',
    updated_at: '2026-09-14',
  };
  try {
    global.fetch = async (url, options) => {
      seen.push([url, options]);
      return new Response(JSON.stringify(row));
    };
    const input = {
      client_id: row.client_id,
      name: row.name,
      directory_name: row.directory_name,
      kind: row.kind,
      version: 0,
    };
    await api.saveLocalSource(4, {
      ...input,
      contents: 'must remain local',
      handle: 'not serializable',
    });
    assert.deepEqual(JSON.parse(seen[0][1].body), input);
    assert.equal(seen[0][0], '/api/projects/4/local-code');
    global.fetch = async () => new Response(JSON.stringify([{ ...row, project_id: 99 }]));
    await assert.rejects(api.listLocalSources(4), /invalid_response/);
    assert.notEqual(api.bindingKey(2, 4, row.client_id), api.bindingKey(3, 4, row.client_id));
  } finally {
    global.fetch = original;
  }
});

test('IndexedDB keeps immutable snapshots and commits one competing read; aborted write preserves history', async () => {
  const { indexedDB, IDBKeyRange, IDBObjectStore } = require('fake-indexeddb');
  const previousDB = global.indexedDB,
    previousRange = global.IDBKeyRange;
  global.indexedDB = indexedDB;
  global.IDBKeyRange = IDBKeyRange;
  const store = load('localCodeStore.ts');
  const key = 'local-test-' + crypto.randomUUID();
  try {
    // A cloneable stand-in tests IndexedDB persistence, not OS directory authorization.
    await store.bindDirectory(key, { kind: 'directory', name: 'test-only' }, ['/']);
    const binding = await store.loadBinding(key);
    const baseline = {
      files: { 'a.ts': { content: 'before', hash: 'a', size: 6, modifiedAt: 1 } },
      skipped: {},
    };
    const first = await store.appendSnapshot(binding, baseline, ['/'], '2026-09-14T00:00:00Z');
    assert.equal(first.name, load('snapshotTime.ts').snapshotTime(first.foundAt));
    assert.equal((await store.loadSnapshot(key, 1)).name, first.name);
    assert.equal((await store.readHistory(key))[0].name, first.name);
    baseline.files['a.ts'].content = 'mutated client object';
    assert.equal((await store.loadSnapshot(key, 1)).files['a.ts'].content, 'before');
    const sameBinding = await store.loadBinding(key);
    const changed = {
      files: { 'a.ts': { content: 'after', hash: 'b', size: 5, modifiedAt: 2 } },
      skipped: {},
    };
    const concurrent = await Promise.allSettled([
      store.appendSnapshot(sameBinding, changed, ['/'], '2026-09-14T00:01:00Z'),
      store.appendSnapshot(sameBinding, changed, ['/'], '2026-09-14T00:01:00Z'),
    ]);
    assert.equal(concurrent.filter((r) => r.status === 'fulfilled').length, 1);
    assert.equal(
      concurrent.find((r) => r.status === 'rejected').reason.message,
      'local_read_conflict',
    );
    assert.equal((await store.loadBinding(key)).sequence, 2);
    assert.equal((await store.loadSnapshot(key, 1)).files['a.ts'].content, 'before');
    assert.deepEqual(
      (await store.readHistory(key)).map((row) => row.sequence),
      [2, 1],
    );
    assert.deepEqual(await store.readHistory('another-user:' + key), []);
    const originalAdd = IDBObjectStore.prototype.add;
    IDBObjectStore.prototype.add = function (...args) {
      const request = originalAdd.apply(this, args);
      if (this.name === 'snapshots') this.transaction.abort();
      return request;
    };
    try {
      await assert.rejects(
        store.appendSnapshot(await store.loadBinding(key), changed, ['/'], first.startedAt),
        /local_storage_full/,
      );
    } finally {
      IDBObjectStore.prototype.add = originalAdd;
    }
    assert.equal((await store.loadBinding(key)).sequence, 2);
    assert.equal(await store.loadSnapshot(key, 3), undefined);
  } finally {
    global.indexedDB = previousDB;
    global.IDBKeyRange = previousRange;
  }
});

test('file changed while reading aborts instead of recording a misleading snapshot', async () => {
  let reads = 0;
  const unstable = {
    kind: 'file',
    name: 'a.ts',
    async getFile() {
      return new File(['data'], 'a.ts', { lastModified: ++reads });
    },
  };
  const tree = await files.scanDirectory(directory('code', [unstable]), signal());
  await assert.rejects(files.readSelection(tree, ['/'], signal()), /local_file_changed/);
});

test('reads more than old count and size limits without truncation', async () => {
  const entries = Array.from({ length: 10001 }, (_, i) => file(i + '.ts', 'text'));
  const tree = await files.scanDirectory(directory('large', entries), signal());
  assert.equal(tree.files.length, 10001);
  const result = await files.readSelection(tree, ['/'], signal());
  assert.equal(Object.keys(result.files).length, 10001);
  const content = 'x'.repeat(11 * 1024 * 1024);
  const big = await files.readSelection(
    await files.scanDirectory(directory('large', [file('big.ts', content)]), signal()),
    ['/'],
    signal(),
  );
  assert.equal(big.files['big.ts'].content, content);
  assert.equal(Object.keys(big.skipped).length, 0);
});
