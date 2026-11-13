const { test } = require('node:test'),
  assert = require('node:assert/strict'),
  fs = require('node:fs'),
  path = require('node:path'),
  ts = require('typescript');
function text(node) {
  if (Array.isArray(node)) return node.map(text).join('');
  if (!node || typeof node !== 'object')
    return typeof node === 'string' || typeof node === 'number' ? String(node) : '';
  return node.props?.['aria-label'] || text(node.props?.children);
}
function harness(count = 35, customize = () => {}, component = 'GenerationReview') {
  const cache = new Map(),
    hooks = [],
    pendingEffects = [],
    submitted = [];
  let cursor = 0;
  const react = {
    useId: () => 'generation-resolution-form',
    useState(initial) {
      const n = cursor++;
      if (!hooks[n]) hooks[n] = { value: typeof initial === 'function' ? initial() : initial };
      return [
        hooks[n].value,
        (v) => {
          hooks[n].value = typeof v === 'function' ? v(hooks[n].value) : v;
        },
      ];
    },
    useRef(initial) {
      return (hooks[cursor++] ||= { current: initial });
    },
    useEffect(fn, deps) {
      const n = cursor++,
        old = hooks[n];
      if (!old || deps.some((d, i) => !Object.is(d, old.deps[i]))) {
        hooks[n] = { deps };
        pendingEffects.push(fn);
      }
    },
  };
  function load(file) {
    if (cache.has(file)) return cache.get(file);
    const exports = {};
    cache.set(file, exports);
    const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    new Function('exports', 'require', code)(exports, (dep) => {
      if (dep === 'react') return react;
      if (dep === './CaseDialog') return { CaseDialog: 'dialog' };
      if (dep === './FormSelect') return { FormSelect: 'select' };
      if (dep === './CaseGenerationDialogs') return { GenerationDetail: 'edit-detail' };
      if (!dep.startsWith('.')) return require(dep);
      const base = path.resolve(path.dirname(file), dep);
      return load(base + (fs.existsSync(base + '.ts') ? '.ts' : '.tsx'));
    });
    return exports;
  }
  const blank = load(path.resolve(__dirname, '../src/caseApi.ts')).blankDesign,
    Review = load(
      path.resolve(
        __dirname,
        component === 'GenerationReview'
          ? '../src/GenerationReview.tsx'
          : '../src/GenerationBatchReview.tsx',
      ),
    )[component],
    Single = load(path.resolve(__dirname, '../src/GenerationReview.tsx')).GenerationSingleReview,
    Result = load(
      path.resolve(__dirname, '../src/GenerationReview.tsx'),
    ).GenerationApplicationResult,
    items = Array.from({ length: count }, (_, n) => ({
      key: 'C' + (n + 1),
      kind: 'NEW',
      design: {
        ...blank(),
        title: '用例' + (n + 1),
        preconditions: '账号有权限',
        steps: '1.打开订单\n2.取消订单',
        expected: '订单已取消',
      },
      revision: 0,
      problem: '',
      matches: [],
      categoryId: null,
    })),
    record = {
      id: '1',
      serverRevision: 1,
      handling: {},
      failures: [],
      suggestions: items.map((i) => ({
        ...i,
        function: '订单',
        reason: '固定需求',
        blocked: false,
        caseId: null,
        baseVersion: null,
        evidence: [{ source: 'M1', segment: 'S1', quote: '订单已取消' }],
      })),
    },
    props = {
      record,
      items,
      categories: [
        { id: 7, name: '订单 / 取消' },
        { id: 8, name: '订单 / 提交' },
      ],
      actor: '审阅者',
      busy: false,
      error: '',
      onClose() {},
      onSubmit: (items) => submitted.push(items),
      onSave: async () => true,
      choices: {},
    };
  customize(props);
  function render() {
    cursor = 0;
    const nodes = [];
    function walk(node) {
      if (Array.isArray(node)) return node.forEach(walk);
      if (!node || typeof node !== 'object') return;
      nodes.push(node);
      walk(node.props?.children);
      walk(node.props?.footer);
    }
    walk(Review(props));
    while (pendingEffects.length) pendingEffects.shift()();
    return nodes;
  }
  const button = (label) => render().find((n) => n.type === 'button' && text(n) === label),
    select = (label) => render().find((n) => n.type === 'select' && n.props.label === label),
    check = (label, value) => {
      const nodes = render(),
        node = nodes.find(
          (n) =>
            n.type === 'input' &&
            (n.props['aria-label'] === label ||
              (n.props.type === 'checkbox' &&
                text(
                  nodes.find((p) => p.type === 'label' && p.props.children?.includes?.(n)),
                ).includes(label))),
        );
      assert.ok(node, label);
      node.props.onChange({ target: { checked: value } });
    };
  return {
    props,
    render,
    button,
    select,
    check,
    submitted,
    renderSingle(singleProps) {
      cursor = 0;
      const nodes = [];
      function walk(node) {
        if (Array.isArray(node)) return node.forEach(walk);
        if (!node || typeof node !== 'object') return;
        nodes.push(node);
        walk(node.props?.children);
        walk(node.props?.footer);
      }
      walk(Single(singleProps));
      while (pendingEffects.length) pendingEffects.shift()();
      return nodes;
    },
    renderResult(resultProps) {
      cursor = 0;
      const nodes = [];
      function walk(node) {
        if (Array.isArray(node)) return node.forEach(walk);
        if (!node || typeof node !== 'object') return;
        nodes.push(node);
        walk(node.props?.children);
        walk(node.props?.footer);
      }
      walk(Result(resultProps));
      return nodes;
    },
  };
}

test('single review is a small confirmation with cancel and confirm, freezing only this item', () => {
  const h = harness(1),
    sent = [];
  const longTitle = '很长的合成用例标题'.repeat(200);
  h.props.items[0].design.title = longTitle;
  let cancelled = 0;
  const props = {
    items: h.props.items,
    busy: false,
    error: '',
    onClose: () => cancelled++,
    onSubmit: (items) => sent.push(items),
  };
  let nodes = h.renderSingle(props);
  const dialog = nodes.find((n) => n.type === 'dialog');
  assert.equal(dialog.props.title, '确认入库');
  assert.equal(dialog.props.wide, undefined);
  assert.match(dialog.props.className, /generation-single-confirm/);
  assert.match(text(dialog), /确认将本条用例审核入库？/);
  assert.ok(!text(dialog).includes(longTitle));
  assert.deepEqual(nodes.filter((n) => n.type === 'button').map(text), ['取消', '确认']);
  assert.ok(!nodes.some((n) => ['input', 'select', 'textarea', 'nav'].includes(n.type)));
  nodes.find((n) => n.type === 'button' && text(n) === '取消').props.onClick();
  assert.equal(cancelled, 1);
  assert.equal(sent.length, 0);
  const confirm = nodes.find((n) => n.type === 'button' && text(n) === '确认');
  confirm.props.onClick();
  confirm.props.onClick();
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0], [
    {
      key: 'C1',
      draft_revision: 0,
      action: 'apply',
      target_id: null,
      target_version: null,
      reason: '',
      category_mode: 'KEEP',
      category_id: null,
    },
  ]);
  props.busy = true;
  nodes = h.renderSingle(props);
  assert.equal(
    nodes.find((n) => n.type === 'button' && text(n) === '正在入库…').props.disabled,
    true,
  );
  props.busy = false;
  props.error = '提交失败，请核对';
  nodes = h.renderSingle(props);
  assert.ok(nodes.some((n) => n.props?.role === 'alert' && text(n) === props.error));
  nodes.find((n) => n.type === 'button' && text(n) === '确认').props.onClick();
  assert.equal(sent.length, 2);
});

test('single review preserves reuse/version checks and blocks ambiguous, retired or changed items', () => {
  const h = harness(1),
    sent = [];
  const props = {
    items: h.props.items,
    busy: false,
    error: '',
    onClose() {},
    onSubmit: (items) => sent.push(items),
  };
  props.items[0].matches = [{ id: 9, version: 3, lifecycle: 'ACTIVE' }];
  let nodes = h.renderSingle(props);
  assert.ok(nodes.some((n) => text(n).includes('将关联复用')));
  nodes.find((n) => n.type === 'button' && text(n) === '确认').props.onClick();
  assert.equal(sent[0][0].action, 'reuse');
  assert.equal(sent[0][0].target_id, 9);
  assert.equal(sent[0][0].target_version, 3);
  for (const change of [
    () => props.items[0].matches.push({ id: 10, version: 2, lifecycle: 'ACTIVE' }),
    () => {
      props.items[0].matches = [{ id: 9, version: 3, lifecycle: 'RETIRED' }];
    },
    () => (props.items[0].problem = '目标设计已变化'),
  ]) {
    change();
    nodes = h.renderSingle(props);
    const confirm = nodes.find((n) => n.type === 'button' && text(n) === '确认');
    assert.equal(confirm.props.disabled, true);
    confirm.props.onClick();
    assert.equal(sent.length, 1);
    assert.ok(nodes.some((n) => n.props?.role === 'alert'));
  }
});

test('batch review shows content and immediately classifies only selected cross-page items, with per-item overrides', () => {
  const h = harness(35, (p) => {
    p.items[34].problem = '依据待核对';
  });
  assert.ok(h.render().some((n) => text(n).includes('1.打开订单\n2.取消订单')));
  assert.ok(h.render().some((n) => text(n).includes('订单已取消')));
  h.check('入库 C1', false);
  h.select('统一分类').props.onChange('7');
  assert.equal(h.button('确认入库（33条）').props.disabled, true);
  for (let n = 0; n < 3; n++) h.button('下一页').props.onClick();
  h.button('用例31C31 · 新增 · 订单 / 取消').props.onClick();
  h.select('这条用例的分类').props.onChange('8');
  h.check('我已审核', true);
  const confirm = h.button('确认入库（33条）');
  confirm.props.onClick();
  confirm.props.onClick();
  assert.equal(h.submitted.length, 1);
  const result = h.submitted[0];
  assert.equal(result.length, 33);
  assert.ok(!result.some((i) => ['C1', 'C35'].includes(i.key)));
  assert.equal(result.find((i) => i.key === 'C31').category_id, 8);
  assert.equal(result.find((i) => i.key === 'C34').category_id, 7);
  assert.equal(h.props.record.handling.C31, undefined);
});

test('reuse preserves target content/category, while ambiguous or retired targets require explicit handling', () => {
  const h = harness(3, (p) => {
    const target = {
      ...p.items[0].design,
      id: 90,
      number: '原编号',
      version: 4,
      category_id: 8,
      lifecycle: 'ACTIVE',
    };
    p.items[0].matches = [target];
    p.items[1].matches = [target, { ...target, id: 91 }];
    p.items[2].matches = [{ ...target, id: 92, lifecycle: 'RETIRED' }];
  });
  assert.equal(h.select('统一分类').props.disabled, true);
  assert.ok(h.render().some((n) => text(n).includes('保留分类：订单 / 提交')));
  h.check('我已审核', true);
  h.button('确认入库（1条）').props.onClick();
  assert.deepEqual(h.submitted[0][0], {
    key: 'C1',
    draft_revision: 0,
    action: 'reuse',
    target_id: 90,
    target_version: 4,
    reason: '',
    category_mode: 'KEEP',
    category_id: null,
  });
});

test('editing returns to batch with category choices and selection retained; save failure keeps the editor open', async () => {
  const h = harness(2);
  let succeed = false;
  h.props.onSave = async () => succeed;
  h.select('统一分类').props.onChange('7');
  h.check('入库 C2', false);
  h.check('我已审核', true);
  h.button('修改内容').props.onClick();
  let editor = h.render().find((n) => n.type === 'edit-detail');
  assert.equal(editor.props.reviewMode, true);
  editor.props.onSave({ draft: h.props.items[0].design }, 0);
  await Promise.resolve();
  await Promise.resolve();
  assert.ok(h.render().some((n) => n.type === 'edit-detail'));
  succeed = true;
  editor.props.onSave({ draft: h.props.items[0].design }, 0);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(h.button('确认入库（1条）').props.disabled, true);
  h.check('我已审核', true);
  h.button('确认入库（1条）').props.onClick();
  assert.equal(h.submitted[0][0].category_id, 7);
  assert.equal(h.submitted[0].length, 1);
});

test('category choices contain only unclassified and existing categories; failed requests can retry and content changes invalidate confirmation', () => {
  const h = harness(1);
  assert.deepEqual(
    h
      .select('统一分类')
      .props.options.filter((o) => !o.disabled)
      .map((o) => o.label),
    ['未分类', '订单 / 取消', '订单 / 提交'],
  );
  assert.deepEqual(
    h.select('这条用例的分类').props.options.map((o) => o.label),
    ['未分类', '订单 / 取消', '订单 / 提交'],
  );
  assert.equal(h.select('这条用例的分类').props.value, 'CLEAR');
  h.select('统一分类').props.onChange('CLEAR');
  h.check('我已审核', true);
  h.button('确认入库（1条）').props.onClick();
  assert.equal(h.submitted[0][0].category_mode, 'CLEAR');
  assert.equal(h.submitted[0][0].category_id, null);
  h.props.busy = true;
  h.render();
  assert.ok(h.button('正在入库…').props.disabled);
  assert.equal(h.button('取消').props.disabled, true);
  h.props.busy = false;
  h.render();
  h.select('统一分类').props.onChange('8');
  h.check('我已审核', true);
  h.button('确认入库（1条）').props.onClick();
  assert.equal(h.submitted[1][0].category_mode, 'SET');
  assert.equal(h.submitted[1][0].category_id, 8);
  h.props.items = structuredClone(h.props.items);
  h.render();
  assert.equal(h.button('确认入库（1条）').props.disabled, true);
});

test('application result follows queue and completion while remaining closable, with accurate failure counts', () => {
  const h = harness(),
    props = {
      application: {
        id: 10,
        status: 'QUEUED',
        error: '',
        items: [
          { key: 'C1', status: 'PENDING', category_mode: 'SET', category_id: 7 },
          { key: 'C2', status: 'COMPLETED', category_mode: 'KEEP' },
        ],
      },
      categories: h.props.categories,
      onClose() {},
      onFailures() {},
    };
  let nodes = h.renderResult(props);
  assert.equal(nodes.find((n) => n.type === 'dialog').props.busy, false);
  assert.ok(nodes.some((n) => text(n).includes('等待后台入库')));
  assert.ok(nodes.some((n) => text(n).includes('成功 1条')));
  assert.ok(nodes.some((n) => text(n).includes('待处理 1条')));
  assert.equal(
    nodes.find((n) => n.type === 'button' && text(n) === '关闭').props.disabled,
    undefined,
  );
  props.application.status = 'COMPLETED';
  props.application.items[0].status = 'FAILED';
  nodes = h.renderResult(props);
  assert.ok(nodes.some((n) => text(n).includes('失败 1条')));
  assert.ok(nodes.some((n) => text(n).includes('待处理 0条')));
  assert.ok(nodes.some((n) => n.type === 'button' && text(n) === '查看失败清单'));
  props.application.items[1].action = 'ignore';
  nodes = h.renderResult(props);
  assert.ok(nodes.some((n) => text(n).includes('成功 0条')));
  assert.ok(nodes.some((n) => text(n).includes('忽略 1条')));
  props.application.status = 'FAILED';
  nodes = h.renderResult(props);
  assert.ok(nodes.some((n) => text(n).includes('本次提交未完成，已成功的用例保留')));
});

test('batch confirmation shows only count and buttons, keeps categories and submits once after explicit confirmation', () => {
  let cancelled = 0;
  const h = harness(
    25,
    (p) => {
      p.onClose = () => cancelled++;
    },
    'GenerationBatchReview',
  );
  const before = JSON.stringify(h.props.items),
    nodes = h.render(),
    dialog = nodes.find((n) => n.type === 'dialog');
  assert.equal(dialog.props.title, '确认批量入库');
  assert.equal(dialog.props.wide, undefined);
  assert.match(text(dialog), /25 条用例/);
  assert.ok(!nodes.some((n) => ['input', 'select', 'textarea', 'table', 'nav'].includes(n.type)));
  assert.ok(!text(dialog).includes('用例1'));
  assert.equal(h.submitted.length, 0);
  h.button('取消').props.onClick();
  assert.equal(cancelled, 1);
  assert.equal(h.submitted.length, 0);
  const confirm = h.button('确认');
  assert.equal(confirm.props.disabled, false);
  confirm.props.onClick();
  confirm.props.onClick();
  assert.equal(h.submitted.length, 1);
  assert.equal(h.submitted[0].length, 25);
  assert.ok(h.submitted[0].every((i) => i.category_mode === 'KEEP' && i.category_id === null));
  assert.equal(JSON.stringify(h.props.items), before);
  h.props.busy = true;
  assert.equal(h.button('正在入库…').props.disabled, true);
  const single = harness(
    1,
    (p) => {
      p.single = true;
    },
    'GenerationBatchReview',
  );
  assert.match(
    single.render().find((n) => n.type === 'dialog').props.className,
    /generation-single-confirm/,
  );
});

test('batch confirmation blocks known errors and ambiguous reuse, validates saved versions and preserves failure retries', () => {
  const h = harness(
    2,
    (p) => {
      p.items[1].problem = '当前版本已变化';
    },
    'GenerationBatchReview',
  );
  assert.equal(h.button('确认').props.disabled, true);
  h.button('确认').props.onClick();
  assert.equal(h.submitted.length, 0);
  assert.ok(h.render().some((n) => text(n).includes('当前版本已变化')));
  h.props.items[1].problem = '';
  h.props.items[0].matches = [
    { id: 7, version: 2, lifecycle: 'ACTIVE' },
    { id: 8, version: 3, lifecycle: 'ACTIVE' },
  ];
  assert.equal(h.button('确认').props.disabled, true);
  h.props.choices.C1 = {
    key: 'C1',
    draft_revision: 0,
    action: 'reuse',
    target_id: 8,
    target_version: 3,
    reason: '',
    category_mode: 'KEEP',
    category_id: null,
  };
  assert.equal(h.button('确认').props.disabled, false);
  h.button('确认').props.onClick();
  assert.equal(h.submitted[0][0].target_id, 8);
  assert.equal(h.submitted[0][0].target_version, 3);
  h.props.busy = true;
  h.render();
  h.props.busy = false;
  h.props.error = '请求失败，请核对后重试';
  h.render();
  h.button('确认').props.onClick();
  assert.equal(h.submitted.length, 2);
  h.props.items[0].matches[1].version = 4;
  assert.equal(h.button('确认').props.disabled, true);
  h.props.items = [];
  assert.equal(h.button('确认').props.disabled, true);
});

test('duplicate resolution saves an explicit choice without applying and requires a reason for adding a duplicate', () => {
  const saved = [];
  const h = harness(
    1,
    (p) => {
      p.item = p.items[0];
      p.item.matches = [
        { id: 7, number: '原编号7', version: 4, lifecycle: 'ACTIVE' },
        { id: 8, number: '原编号8', version: 2, lifecycle: 'RETIRED' },
      ];
      p.onSave = (value) => saved.push(value);
    },
    'GenerationDuplicateResolution',
  );
  h.select('如何处理').props.onChange('include');
  let form = h.render().find((n) => n.props.id === 'generation-resolution-form');
  form.props.onSubmit({ preventDefault() {} });
  assert.equal(saved.length, 0);
  const reason = h.render().find((n) => n.type === 'textarea');
  assert.equal(reason.props.required, true);
  reason.props.onChange({ target: { value: '人工确认需要独立的场景编号' } });
  form = h.render().find((n) => n.props.id === 'generation-resolution-form');
  form.props.onSubmit({ preventDefault() {} });
  assert.equal(saved.length, 1);
  assert.equal(saved[0].action, 'include');
  assert.equal(saved[0].category_mode, 'KEEP');
  assert.equal(h.submitted.length, 0);
});

test('an explicit ignore choice is confirmed and reported as ignored, not as a case write', () => {
  const h = harness(
    1,
    (p) => {
      p.choices.C1 = {
        key: 'C1',
        draft_revision: 0,
        action: 'ignore',
        target_id: null,
        target_version: null,
        reason: '人工核对为不适用',
        category_mode: 'KEEP',
        category_id: null,
      };
    },
    'GenerationBatchReview',
  );
  const dialog = h.render().find((n) => n.type === 'dialog');
  assert.equal(dialog.props.title, '确认忽略建议');
  assert.match(text(dialog), /确认忽略所选的.*1.*条用例建议/);
  assert.ok(!text(dialog).includes('审核入库'));
  h.button('确认').props.onClick();
  assert.equal(h.submitted[0][0].action, 'ignore');
  assert.equal(h.submitted[0][0].reason, '人工核对为不适用');
});
