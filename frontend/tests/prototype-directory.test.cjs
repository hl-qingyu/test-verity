const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const React = require('react');
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
const src = (name) => path.resolve(__dirname, '../src', name);
const api = load(src('prototypeDirectory.ts'));
function file(relative, body = 'body') {
  const value = new File([body], relative.split('/').at(-1), { lastModified: 123 });
  Object.defineProperty(value, 'webkitRelativePath', { value: relative });
  return value;
}
function unpack(buffer) {
  const bytes = Buffer.from(buffer),
    members = [];
  let offset = 0;
  while (bytes[offset]) {
    const header = bytes.subarray(offset, offset + 512),
      name = header.subarray(0, 100).toString().split('\0')[0];
    const size = parseInt(header.subarray(124, 136).toString().replace(/\0/g, ''), 8);
    const checksum = parseInt(header.subarray(148, 156).toString().replace(/\0/g, ''), 8);
    assert.equal(
      [...header].reduce((n, b, i) => n + (i >= 148 && i < 156 ? 32 : b), 0),
      checksum,
    );
    offset += 512;
    members.push({ name, body: bytes.subarray(offset, offset + size) });
    offset += Math.ceil(size / 512) * 512;
  }
  assert.ok(bytes.subarray(offset).every((b) => b === 0));
  return members;
}
test('directory selection preserves relative paths and excludes unsupported and credential files', () => {
  const chosen = api.selectedDirectory([
    file('原型/模块一/同名.html'),
    file('原型/模块二/同名.html'),
    file('原型/assets/a.png'),
    file('原型/.env'),
    file('原型/node_modules/vendor.js'),
    file('原型/private.key'),
    file('原型/空.css', ''),
  ]);
  assert.equal(chosen.name, '原型');
  assert.equal(chosen.entries.length, 4);
  assert.equal(chosen.skipped.length, 3);
  assert.ok(chosen.entries.some((f) => f.path === '模块一/同名.html'));
  for (const p of [
    '/outside.html',
    '../x.html',
    'a/../x.html',
    'C:/x.html',
    'a\\x.html',
    '.ssh/x.json',
    'credentials.json',
  ])
    assert.equal(api.directoryPathAllowed(p), false, p);
  assert.throws(() => api.selectedDirectory([file('原型/a.html'), file('原型/a.html')]));
});
test('directory wire archive preserves UTF8 paths and exact text/binary bytes with deterministic framing', async () => {
  const entries = [
    { path: '页面/订单.html', file: file('原型/页面/订单.html', '<h1>中文</h1>') },
    { path: 'assets/a.png', file: file('原型/assets/a.png', new Uint8Array([0, 255, 13, 10])) },
  ];
  const metadata = {
    name: '目录原型',
    description: '说明',
    group_id: null,
    source_id: null,
    directory_name: '原型',
  };
  const one = api.directoryArchive(entries, metadata),
    two = api.directoryArchive(entries, metadata);
  const members = unpack(await one.arrayBuffer());
  assert.deepEqual(Buffer.from(await one.arrayBuffer()), Buffer.from(await two.arrayBuffer()));
  assert.deepEqual(
    members.map((m) => m.name),
    ['manifest.json', 'f0', 'f1'],
  );
  assert.equal(JSON.parse(members[0].body).files[0].path, '页面/订单.html');
  assert.deepEqual([...members[2].body], [0, 255, 13, 10]);
  const output = process.env.DIRECTORY_WIRE_SAMPLE;
  if (output) fs.writeFileSync(output, Buffer.from(await one.arrayBuffer()));
});
test('directory catalog checks version identity, path safety, hashes and duplicate files', async () => {
  let result = {
    document_id: 5,
    version_id: 7,
    sha256: 'a'.repeat(64),
    files: [{ path: '页面/a.html', size: 4, sha256: 'b'.repeat(64), extension: 'html' }],
  };
  const calls = [];
  const client = load(src('prototypeDirectory.ts'), {
    './api/http': {
      apiRequest: async (url, options) => {
        calls.push({ url, options });
        return result;
      },
    },
  });
  const c = new AbortController();
  assert.equal((await client.directoryCatalog(2, 5, 7, c.signal))[0].path, '页面/a.html');
  assert.equal(calls[0].options.signal, c.signal);
  assert.match(calls[0].url, /projects\/2\/prototypes\/directories\/5\/versions\/7\/files/);
  result = { ...result, version_id: 8 };
  await assert.rejects(client.directoryCatalog(2, 5, 7, c.signal));
  result = { ...result, version_id: 7, files: [{ ...result.files[0], path: '../a.html' }] };
  await assert.rejects(client.directoryCatalog(2, 5, 7, c.signal));
});

test('case review submits only chosen directory files, retains its display name and clears files on a version change', async () => {
  const values = [],
    refs = [];
  let state = 0,
    ref = 0,
    submitted;
  const react = {
    ...React,
    useState(initial) {
      const i = state++;
      if (!(i in values)) values[i] = initial;
      return [values[i], (v) => (values[i] = typeof v === 'function' ? v(values[i]) : v)];
    },
    useRef(initial) {
      const i = ref++;
      return (refs[i] ||= { current: initial });
    },
  };
  const { CaseAnalysisNew } = load(src('CaseAnalysisNew.tsx'), {
    react,
    './CaseDialog': { CaseDialog: 'dialog' },
    './Form': { Form: 'form' },
    './FormSelect': { FormSelect: 'select-theme' },
    './PrototypeDirectoryFiles': { PrototypeDirectoryFiles: 'directory-files' },
    './CaseGenerationNew': { GithubMaterial: 'github-files' },
  });
  const props = {
    projectId: 3,
    options: {
      materials: [
        {
          id: 9,
          name: '自定义目录名称',
          kind: 'DIRECTORY',
          purpose: 'PROTOTYPE',
          versions: [
            { id: 100, number: 1, filename: '原型.tar' },
            { id: 101, number: 2, filename: '原型.tar' },
          ],
        },
      ],
      connections: [],
    },
    prototypes: [],
    snapshot: {
      revision: 1,
      categories: [],
      items: [
        {
          id: 5,
          version: 2,
          title: '合成用例',
          number: 1,
          module: '订单',
          expected: '成功',
          category_id: null,
        },
      ],
    },
    busy: false,
    error: '',
    onSessionEnd() {},
    onClose() {},
    onPrepare: async (value) => (submitted = value),
  };
  const render = () => {
    state = 0;
    ref = 0;
    return CaseAnalysisNew(props);
  };
  function find(tree, type, match = () => true) {
    if (Array.isArray(tree)) return tree.map((t) => find(t, type, match)).find(Boolean);
    if (!tree?.props) return null;
    if (tree.type === type && match(tree)) return tree;
    return find(tree.props.children, type, match);
  }
  let tree = render();
  find(tree, 'input', (n) => n.props.type === 'checkbox').props.onChange({
    target: { checked: true },
  });
  tree = render();
  assert.equal(
    find(tree, 'span', (n) => n.props.className === 'review-source-name').props.children,
    '自定义目录名称',
  );
  assert.equal(find(tree, 'directory-files').props.versionId, 101);
  find(tree, 'directory-files').props.onChange(['页面/订单.html']);
  tree = render();
  find(tree, 'form').props.onSubmit({ preventDefault() {} });
  await new Promise(setImmediate);
  assert.equal(submitted.materials[0].version, '101');
  assert.deepEqual(submitted.materials[0].paths, ['页面/订单.html']);
  find(tree, 'select-theme', (n) => n.props.label === '固定版本').props.onChange('100');
  tree = render();
  assert.equal(find(tree, 'directory-files').props.versionId, 100);
  assert.deepEqual(find(tree, 'directory-files').props.value, []);
});
test('directory editor sends only selected files, keeps project revision, blocks duplicate submits and retains UUID on manual retry', async () => {
  const values = [],
    refs = [];
  let state = 0,
    ref = 0,
    calls = [],
    release,
    fail = false;
  const react = {
    ...React,
    useState(initial) {
      const i = state++;
      if (!(i in values)) values[i] = initial;
      return [
        values[i],
        (v) => {
          values[i] = typeof v === 'function' ? v(values[i]) : v;
        },
      ];
    },
    useRef(initial) {
      const i = ref++;
      return (refs[i] ||= { current: initial });
    },
    useEffect() {},
  };
  const saved = [];
  const { PrototypeEditor } = load(src('PrototypeEditor.tsx'), {
    react,
    './CaseDialog': { CaseDialog: 'dialog' },
    './Form': { Form: 'form' },
    './FormSelect': { FormSelect: 'select-theme' },
    './FilePicker': { FilePicker: 'file-picker' },
    './CodeFileTree': { CodeFileTree: 'file-tree' },
    './prototypeApi': {
      prototypeError: (e) => e.message,
      prototypeRequest: async (url, options) => {
        calls.push({ url, options });
        await new Promise((r) => (release = r));
        if (fail) throw Error('network');
        return { revision: 5, groups: [], sources: [] };
      },
    },
  });
  const props = {
    base: '/api/projects/3/prototypes',
    kind: 'DIRECTORY',
    library: { revision: 4, groups: [], sources: [] },
    connections: [],
    onClose() {},
    onSessionEnd() {},
    onSaved: (v) => saved.push(v),
  };
  const render = () => {
    state = 0;
    ref = 0;
    return PrototypeEditor(props);
  };
  function find(tree, type) {
    if (Array.isArray(tree)) return tree.map((t) => find(t, type)).find(Boolean);
    if (!tree?.props) return null;
    if (tree.type === type) return tree;
    return find(tree.props.children, type);
  }
  let tree = render();
  find(tree, 'file-picker').props.onChange([file('原型/a.html', 'a'), file('原型/b.html', 'b')]);
  tree = render();
  find(tree, 'file-tree').props.onChange(['b.html']);
  tree = render();
  const submit = () => find(tree, 'form').props.onSubmit({ preventDefault() {} });
  fail = true;
  submit();
  submit();
  assert.equal(calls.length, 1);
  release();
  await new Promise(setImmediate);
  assert.equal(saved.length, 0);
  tree = render();
  fail = false;
  submit();
  assert.equal(calls.length, 2);
  assert.equal(
    new URL('http://test' + calls[0].url).searchParams.get('upload_id'),
    new URL('http://test' + calls[1].url).searchParams.get('upload_id'),
  );
  const members = unpack(await calls[1].options.body.arrayBuffer());
  assert.deepEqual(
    JSON.parse(members[0].body).files.map((f) => f.path),
    ['b.html'],
  );
  assert.equal(members[1].body.toString(), 'b');
  assert.equal(new URL('http://test' + calls[1].url).searchParams.get('revision'), '4');
  release();
  await new Promise(setImmediate);
  assert.equal(saved.length, 1);
});
