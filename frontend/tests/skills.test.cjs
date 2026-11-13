const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load(file, overrides = {}) {
  const exports = {},
    name = path.resolve(__dirname, '../src', file);
  const code = ts.transpileModule(fs.readFileSync(name, 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  new Function('exports', 'require', code)(
    exports,
    (dep) =>
      overrides[dep] ||
      (dep.endsWith('.css')
        ? {}
        : dep.startsWith('.')
          ? load(
              path.relative(
                path.resolve(__dirname, '../src'),
                path.resolve(path.dirname(name), dep),
              ) + '.ts',
              overrides,
            )
          : require(dep)),
  );
  return exports;
}
function fixture() {
  const file = {
    id: 'b'.repeat(24),
    path: 'SKILL.md',
    type: 'md',
    sha256: 'c'.repeat(64),
    editable: true,
    usage: 'current',
  };
  const record = {
    key: 'case-generation',
    name: '用例生成',
    version: '2.0.4',
    icon: 'list',
    token: 'a'.repeat(64),
    file_count: 2,
    files: [file, { ...file, id: 'd'.repeat(24), path: 'contract.md', editable: false }],
  };
  const content = { ...file, key: record.key, token: record.token, text: '# 原文', body: '# 原文' };
  const turn = {
    id: 1,
    skill_key: record.key,
    question: '简化',
    answer: '请核对修改',
    candidate_body: '# 新正文',
    base_body: content.body,
    base_token: record.token,
    status: 'COMPLETED',
    error_code: '',
    created_at: '2026-10-14T10:00:00Z',
    references: ['SKILL.md', 'contract.md'],
    ai: { name: '本人', model: 'model', version: 1 },
  };
  return { record, content, turn };
}
test('Skill API rejects malformed permissions and cross-Skill responses; preserves original text and safe links', async () => {
  const { record, content, turn } = fixture();
  let result = record,
    seen;
  const api = load('skillApi.ts', {
    './api/http': {
      apiRequest: async (url, options) => {
        seen = { url, options };
        return result;
      },
    },
  });
  assert.equal(api.parseContent(content).text, '# 原文');
  assert.throws(() =>
    api.parsePackage({ ...record, files: [{ ...record.files[1], editable: true }] }),
  );
  assert.throws(() => api.parsePackage({ ...record, token: 'bad' }));
  assert.throws(() =>
    api.parseHistory({ items: [{ ...turn, status: 'SUCCESS' }], has_more: false }),
  );
  assert.equal(api.resolveSkillLink('SKILL.md', 'contract.md', record.files).path, 'contract.md');
  for (const href of [
    '../contract.md',
    'https://example.com',
    'javascript:alert(1)',
    '/contract.md',
    '%2e%2e/contract.md',
  ])
    assert.equal(api.resolveSkillLink('SKILL.md', href, record.files), undefined);
  assert.deepEqual(api.skillDifference('abc', 'adc'), { removed: 'b', added: 'd' });
  await api.skillPackage(record.key);
  assert.equal(seen.url, '/api/skills/case-generation');
  result = { ...record, key: 'code-review' };
  await assert.rejects(api.skillSave(record.key, { body: '# 新正文' }));
  result = { ...turn, skill_key: 'code-review' };
  await assert.rejects(api.skillSend(record.key, {}));
});
function nodeText(node) {
  if (Array.isArray(node)) return node.map(nodeText).join('');
  if (!node || typeof node !== 'object') return typeof node === 'string' ? node : '';
  return nodeText(node.props?.children);
}
function nodes(node) {
  return Array.isArray(node)
    ? node.flatMap(nodes)
    : node && typeof node === 'object'
      ? [node, ...nodes(node.props?.children)]
      : [];
}
function harness(custom = {}, workspace = false) {
  const { record, content, turn } = fixture(),
    hooks = [],
    effects = [],
    calls = [];
  let cursor = 0,
    closed = 0,
    saved = 0;
  const blocker = {
    state: 'unblocked',
    reset() {
      this.state = 'unblocked';
    },
    proceed() {
      this.state = 'proceeding';
    },
  };
  const react = {
    useState(initial) {
      const i = cursor++;
      hooks[i] ??= { value: typeof initial === 'function' ? initial() : initial };
      return [
        hooks[i].value,
        (v) => {
          hooks[i].value = typeof v === 'function' ? v(hooks[i].value) : v;
        },
      ];
    },
    useRef(initial) {
      const i = cursor++;
      return (hooks[i] ??= { current: initial });
    },
    useEffect(fn, deps) {
      const i = cursor++,
        old = hooks[i];
      if (!old || deps.some((d, j) => !Object.is(d, old.deps[j]))) {
        old?.cleanup?.();
        hooks[i] = { deps };
        effects.push(() => {
          hooks[i].cleanup = fn();
        });
      }
    },
    useCallback(fn, deps) {
      const i = cursor++,
        old = hooks[i];
      if (!old || deps.some((d, j) => !Object.is(d, old.deps[j]))) hooks[i] = { deps, fn };
      return hooks[i].fn;
    },
    useMemo(fn, deps) {
      const i = cursor++,
        old = hooks[i];
      if (!old || deps.some((d, j) => !Object.is(d, old.deps[j]))) hooks[i] = { deps, value: fn() };
      return hooks[i].value;
    },
  };
  const real = load('skillApi.ts');
  const makeBundle = (key) => ({
    ...record,
    key,
    name: key === 'requirement-analysis' ? '需求分析' : '用例生成',
    contents: record.files.map((f) => ({
      ...f,
      key,
      token: record.token,
      text: f.path === 'SKILL.md' ? '# 原文' : '# Contract',
      body: f.path === 'SKILL.md' ? '# 原文' : '# Contract',
    })),
  });
  const api = {
    ...real,
    skillList: async () => [makeBundle('requirement-analysis'), makeBundle('case-generation')],
    skillBundle: async (key, previous, signal, refresh) => {
      calls.push({ kind: 'bundle', key, known: previous?.token, signal, refresh });
      return makeBundle(key);
    },
    skillHistory: async () => ({ items: [turn], has_more: false }),
    skillPackage: async () => record,
    skillSave: async (key, payload) => {
      calls.push(payload);
      return record;
    },
    skillSend: async (key, payload) => {
      calls.push(payload);
      return { ...turn, id: 2, status: 'QUEUED' };
    },
    skillCancel: async () => ({ ...turn, status: 'CANCELLED' }),
    ...custom,
  };
  const module = load('Skills.tsx', {
    react,
    'react-router-dom': { useBlocker: () => blocker },
    './skillApi': api,
    './CaseDialog': { CaseDialog: 'dialog' },
    './Form': { Form: 'form' },
    './MarkdownPreview': { MarkdownPreview: 'markdown' },
    './Icon': { Icon: 'icon' },
    './api/http': {
      apiRequest: async () => ({
        personal: {
          name: '合成本人配置',
          base_url: 'https://example.com/v1',
          model: 'my-model',
          reasoning_effort: 'default',
          has_key: true,
          version: 1,
        },
        cli: null,
        call_mode: 'RESPONSES_API',
        preference_version: 0,
        cli_runtime: {
          status: 'unverified',
          version: '0.166.0',
          required_version: '0.166.0',
          available: false,
        },
      }),
    },
  });
  const editorProps = {
    record,
    content,
    onSessionEnd() {},
    onClose() {
      closed++;
    },
    onSaved() {
      saved++;
    },
  };
  const props = workspace
    ? {
        user: { id: 1, platform_role: 'ADMIN', display_name: '管理员', login_name: 'admin' },
        onSessionEnd() {},
      }
    : editorProps;
  const View = workspace ? module.Skills(props).type : module.SkillEditor;
  return {
    record,
    content,
    turn,
    calls,
    blocker,
    props,
    draw() {
      cursor = 0;
      return View(props);
    },
    button(tree, text) {
      const b = nodes([tree, tree.props.footer]).find(
        (n) =>
          n.type === 'button' &&
          (typeof text === 'string' ? nodeText(n) === text : text.test(nodeText(n))),
      );
      assert.ok(b, text);
      return b;
    },
    input(tree, id) {
      const n = nodes(tree).find((n) => n.props?.id === id);
      assert.ok(n, id);
      return n;
    },
    async effects() {
      while (effects.length) effects.shift()();
      await new Promise((r) => setImmediate(r));
    },
    get closed() {
      return closed;
    },
    get saved() {
      return saved;
    },
  };
}
const originalWindow = global.window;
test('Skill editor includes runtime rule files as fixed context and leaves other references optional', async () => {
  global.window = {
    addEventListener() {},
    removeEventListener() {},
    setInterval() {
      return 1;
    },
    clearInterval() {},
  };
  try {
    const h = harness();
    h.record.files.push(
      {
        ...h.record.files[1],
        id: 'e'.repeat(24),
        path: 'references/preparation.md',
        usage: 'current',
      },
      { ...h.record.files[1], id: 'f'.repeat(24), path: 'evaluation.md', usage: 'reference' },
    );
    let tree = h.draw();
    h.button(tree, 'AI辅助修改').props.onClick();
    await h.effects();
    tree = h.draw();
    const labels = nodes(tree).filter((n) => n.type === 'label');
    const runtime = labels.find((n) => nodeText(n) === 'references/preparation.md');
    const optional = labels.find((n) => nodeText(n) === 'evaluation.md');
    const runtimeInput = nodes(runtime).find((n) => n.type === 'input');
    const optionalInput = nodes(optional).find((n) => n.type === 'input');
    assert.equal(runtimeInput.props.checked, true);
    assert.equal(runtimeInput.props.disabled, true);
    assert.equal(optionalInput.props.checked, false);
    assert.equal(optionalInput.props.disabled, false);
  } finally {
    global.window = originalWindow;
  }
});

test('Skill editor keeps dirty drafts on cancel and failure, blocks navigation and reuses the save identity', async () => {
  global.window = {
    addEventListener() {},
    removeEventListener() {},
    setInterval() {
      return 1;
    },
    clearInterval() {},
  };
  try {
    const h = harness({
      skillSave: async (_, p) => {
        h.calls.push(p);
        throw Error('skill_content_changed');
      },
    });
    let tree = h.draw();
    h.input(tree, 'skEditor').props.onChange({ target: { value: '# 修改后的草稿' } });
    tree = h.draw();
    h.button(tree, '取消').props.onClick();
    tree = h.draw();
    assert.match(nodeText(tree), /确定放弃/);
    h.button(tree, '继续编辑').props.onClick();
    tree = h.draw();
    assert.equal(h.input(tree, 'skEditor').props.value, '# 修改后的草稿');
    h.blocker.state = 'blocked';
    await h.effects();
    tree = h.draw();
    await h.effects();
    tree = h.draw();
    assert.match(nodeText(tree), /确定放弃/);
    h.button(tree, '继续编辑').props.onClick();
    assert.equal(h.blocker.state, 'unblocked');
    tree = h.draw();
    h.button(tree, '保存修改').props.onClick();
    tree = h.draw();
    h.button(tree, '确认保存').props.onClick();
    await h.effects();
    tree = h.draw();
    assert.match(nodeText(tree), /草稿仍保留/);
    assert.equal(h.saved, 0);
    h.button(tree, '确认保存').props.onClick();
    await h.effects();
    assert.equal(h.calls.length, 2);
    assert.equal(h.calls[0].request_id, h.calls[1].request_id);
    assert.equal(h.calls[0].expected_token, h.content.token);
  } finally {
    global.window = originalWindow;
  }
});

test('Skill bundles validate unchanged replies, identities and complete file sets', async () => {
  const { record, content } = fixture();
  const contents = record.files.map((f) => ({ ...content, ...f }));
  let reply = { ...record, unchanged: false, contents },
    lastUrl = '';
  const api = load('skillApi.ts', {
    './api/http': {
      apiRequest: async (url) => {
        lastUrl = url;
        return reply;
      },
    },
  });
  const first = await api.skillBundle(record.key);
  assert.equal(first.contents.length, 2);
  assert.match(lastUrl, /include_contents=true/);
  reply = { ...record, unchanged: true, contents: [] };
  assert.equal(await api.skillBundle(record.key, first), first);
  assert.match(lastUrl, /known_token=/);
  await assert.rejects(api.skillBundle(record.key));
  reply = { ...record, unchanged: false, contents: [contents[0]] };
  await assert.rejects(api.skillBundle(record.key));
  reply = {
    ...record,
    unchanged: false,
    contents: [contents[0], { ...contents[1], key: 'code-review' }],
  };
  await assert.rejects(api.skillBundle(record.key));
});

test('Skill workspace switches loaded files immediately without another file request and revalidates cached modules', async () => {
  global.window = { addEventListener() {}, removeEventListener() {} };
  try {
    const h = harness({}, true);
    let tree = h.draw();
    await h.effects();
    tree = h.draw();
    assert.equal(h.calls.length, 1);
    h.button(tree, 'contract.md输出约定').props.onClick();
    tree = h.draw();
    assert.equal(nodes(tree).find((n) => n.type === 'markdown').props.text, '# Contract');
    h.button(tree, 'SKILL.md分析说明').props.onClick();
    tree = h.draw();
    assert.equal(nodes(tree).find((n) => n.type === 'markdown').props.text, '# 原文');
    assert.equal(h.calls.length, 1);
    h.button(tree, /^用例生成/).props.onClick();
    tree = h.draw();
    await h.effects();
    tree = h.draw();
    assert.equal(h.calls.length, 2);
    h.button(tree, /^需求分析/).props.onClick();
    tree = h.draw();
    assert.equal(nodes(tree).find((n) => n.type === 'markdown').props.text, '# 原文');
    assert.equal(h.calls.length, 2);
    await h.effects();
    tree = h.draw();
    assert.equal(h.calls.at(-1).known, h.record.token);
    h.button(tree, '重新加载').props.onClick();
    tree = h.draw();
    await h.effects();
    assert.equal(h.calls.at(-1).refresh, true);
    assert.equal(h.calls.at(-1).known, undefined);
  } finally {
    global.window = originalWindow;
  }
});

test('a late response from another Skill cannot overwrite the current preview', async () => {
  global.window = { addEventListener() {}, removeEventListener() {} };
  try {
    let resolveOld;
    const make = (key) => {
      const { record, content } = fixture();
      return {
        ...record,
        key,
        name: key,
        contents: record.files.map((f) => ({ ...content, ...f, key })),
      };
    };
    const h = harness(
      {
        skillBundle: async (key) =>
          key === 'case-generation'
            ? new Promise((resolve) => {
                resolveOld = resolve;
              })
            : make(key),
      },
      true,
    );
    let tree = h.draw();
    await h.effects();
    tree = h.draw();
    h.button(tree, /^用例生成/).props.onClick();
    tree = h.draw();
    await h.effects();
    h.button(tree, /^需求分析/).props.onClick();
    tree = h.draw();
    await h.effects();
    resolveOld(make('case-generation'));
    await new Promise((resolve) => setImmediate(resolve));
    tree = h.draw();
    assert.equal(
      nodes(tree).find((n) => n.type === 'p' && n.props.className === 'eyebrow').props.children,
      'requirement-analysis',
    );
  } finally {
    global.window = originalWindow;
  }
});
test('AI comparison only applies after a fresh file check and still needs an explicit save', async () => {
  global.window = {
    addEventListener() {},
    removeEventListener() {},
    setInterval() {
      return 1;
    },
    clearInterval() {},
  };
  try {
    const h = harness();
    let tree = h.draw();
    h.button(tree, 'AI辅助修改').props.onClick();
    tree = h.draw();
    await h.effects();
    tree = h.draw();
    assert.match(nodeText(tree), /my-model/);
    h.button(tree, '查看修改对照').props.onClick();
    tree = h.draw();
    assert.equal(h.input(tree, 'skEditor').props.value, '# 原文');
    await h.button(tree, '应用到草稿').props.onClick();
    tree = h.draw();
    assert.equal(h.input(tree, 'skEditor').props.value, '# 新正文');
    assert.equal(h.calls.length, 0);
    assert.match(nodeText(tree), /尚未保存/);
    h.button(tree, '保存修改').props.onClick();
    tree = h.draw();
    h.button(tree, '确认保存').props.onClick();
    await h.effects();
    assert.equal(h.saved, 1);
    assert.equal(h.calls[0].body, '# 新正文');
  } finally {
    global.window = originalWindow;
  }
});
test('AI application refuses a concurrently changed file without changing the local draft', async () => {
  global.window = {
    addEventListener() {},
    removeEventListener() {},
    setInterval() {
      return 1;
    },
    clearInterval() {},
  };
  try {
    const h = harness({
      skillPackage: async () => ({ ...fixture().record, token: 'f'.repeat(64) }),
    });
    let tree = h.draw();
    h.button(tree, 'AI辅助修改').props.onClick();
    tree = h.draw();
    await h.effects();
    tree = h.draw();
    h.button(tree, '查看修改对照').props.onClick();
    tree = h.draw();
    await h.button(tree, '应用到草稿').props.onClick();
    tree = h.draw();
    assert.equal(h.input(tree, 'skEditor').props.value, '# 原文');
    assert.match(nodeText(tree), /文件已变化/);
    assert.equal(h.calls.length, 0);
  } finally {
    global.window = originalWindow;
  }
});
