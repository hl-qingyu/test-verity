const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function text(node) {
  if (Array.isArray(node)) return node.map(text).join('');
  if (node && typeof node === 'object')
    return node.props?.['aria-hidden']
      ? ''
      : node.props?.['aria-label'] || text(node.props?.children);
  return typeof node === 'string' || typeof node === 'number' ? String(node) : '';
}

function harness(options = {}) {
  const state = [],
    refs = [],
    saved = [],
    cache = new Map();
  let cursor = 0,
    refCursor = 0,
    previousCount = 0,
    nextCount = 0;
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial;
      return [
        state[index],
        (value) => {
          state[index] = typeof value === 'function' ? value(state[index]) : value;
        },
      ];
    },
    useRef(initial) {
      return (refs[refCursor++] ||= { current: initial });
    },
    useId: () => 'generation-detail-form',
    useEffect() {},
  };
  function load(name) {
    if (cache.has(name)) return cache.get(name);
    const exports = {};
    cache.set(name, exports);
    const code = ts.transpileModule(fs.readFileSync(name, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    new Function('exports', 'require', code)(exports, (dep) => {
      if (dep === 'react') return react;
      if (dep === './CaseDialog') return { CaseDialog: 'dialog' };
      if (dep === './Form') return { Form: 'form' };
      if (dep === './FormSelect') return { FormSelect: 'select' };
      if (dep === './FilePicker') return { FilePicker: 'file-picker' };
      if (['./api/http', './generationApi', './codeAnalysisApi'].includes(dep)) return {};
      if (!dep.startsWith('.')) return require(dep);
      const file = path.resolve(path.dirname(name), dep);
      return load(fs.existsSync(file + '.ts') ? file + '.ts' : file + '.tsx');
    });
    return exports;
  }
  const api = load(path.resolve(__dirname, '../src/caseApi.ts')),
    Detail = load(path.resolve(__dirname, '../src/CaseGenerationDialogs.tsx')).GenerationDetail,
    design = {
      ...api.blankDesign(),
      title: '订单提交',
      steps: '填写订单并提交',
      expected: '订单保存成功',
    },
    suggestion = {
      key: 'b1:C1',
      kind: 'NEW',
      function: '订单',
      design,
      caseId: null,
      baseVersion: null,
      reason: '依据固定需求',
      blocked: false,
      evidence: [{ source: 'M1', segment: 'page1', side: 'CURRENT', quote: '订单保存成功' }],
      ...options.suggestion,
    },
    record = {
      handling: options.handling ? { [suggestion.key]: [options.handling] } : {},
      failures: [],
    },
    props = {
      record,
      suggestion,
      actor: '审阅者',
      position: { index: options.first ? 0 : options.last ? 11 : 9, total: 12 },
      categories: [{ id: 7, name: '订单分类', count: 0 }],
      onClose() {},
      onAsk() {},
      onSave: (...args) => saved.push(args),
      onPrevious: options.first ? undefined : () => previousCount++,
      onNext: options.last ? undefined : () => nextCount++,
      currentCase: options.currentCase,
      busy: options.busy || false,
      applicationStatus: options.applicationStatus,
      reviewMode: options.reviewMode || false,
      serverError: '',
    };
  function render() {
    cursor = 0;
    refCursor = 0;
    const nodes = [];
    function walk(node) {
      if (Array.isArray(node)) return node.forEach(walk);
      if (!node || typeof node !== 'object') return;
      nodes.push(node);
      walk(node.props?.children);
      walk(node.props?.footer);
      walk(node.props?.sideControls);
    }
    walk(Detail(props));
    return nodes;
  }
  const button = (label) => render().find((node) => node.type === 'button' && text(node) === label);
  const field = (label, type) => {
    const row = render().find((node) => node.type === 'label' && text(node).includes(label));
    assert.ok(row, label);
    return row.props.children.flat().find((node) => node?.type === type);
  };
  function submit(intent = 'save') {
    render()
      .find((node) => node.type === 'form')
      .props.onSubmit({ preventDefault() {}, nativeEvent: { submitter: { value: intent } } });
  }
  const check = (label, checked = true) =>
    field(label, 'input').props.onChange({ target: { checked } });
  const edit = (label, value) => field(label, 'textarea').props.onChange({ target: { value } });
  const errors = () =>
    render()
      .filter((node) => node.props?.role === 'alert')
      .map(text);
  return {
    render,
    renderDialog: (dialogProps) =>
      load(path.resolve(__dirname, '../src/CaseDialog.tsx')).CaseDialog(dialogProps),
    props,
    button,
    field,
    submit,
    check,
    edit,
    errors,
    saved,
    previous: () => previousCount,
    next: () => nextCount,
  };
}

test('unmodified detail navigates without saving and identifies its cross-page position', () => {
  const h = harness(),
    next = h.button('下一条');
  assert.equal(next.props.type, 'button');
  assert.equal(next.props.disabled, false);
  next.props.onClick();
  assert.equal(h.next(), 1);
  assert.equal(h.saved.length, 0);
  assert.ok(h.render().some((node) => text(node).includes('当前筛选第10/12条')));
});

test('unmodified detail navigates to the previous suggestion without saving', () => {
  const h = harness(),
    previous = h.button('上一条');
  assert.equal(previous.props.type, 'button');
  assert.equal(previous.props.disabled, false);
  previous.props.onClick();
  assert.equal(h.previous(), 1);
  assert.equal(h.next(), 0);
  assert.equal(h.saved.length, 0);
});

test('editing saves a draft with previous intent without a separate evidence checkbox', () => {
  const h = harness();
  h.edit('验证用例子项', '返回前保存的订单提交');
  const previous = h.button('保存并上一条');
  assert.equal(previous.props.type, 'submit');
  assert.equal(previous.props.form, 'generation-detail-form');
  assert.equal(previous.props.value, 'previous');
  assert.equal(previous.props.onClick, undefined);
  h.submit('previous');
  const [draft, revision, intent] = h.saved[0];
  assert.equal(intent, 'previous');
  assert.equal(revision, 0);
  assert.equal(draft.draft.title, '返回前保存的订单提交');
  assert.equal(draft.evidenceChecked, false);
  assert.equal(h.previous(), 0);
  assert.equal(h.next(), 0);
});

test('previous and next occupy the dialog side controls while review and save stay in the footer', () => {
  const h = harness(),
    dialog = h.render().find((node) => node.type === 'dialog'),
    previous = h.button('上一条'),
    next = h.button('下一条');
  assert.ok(dialog.props.sideControls);
  assert.equal(previous.props['aria-label'], '上一条');
  assert.equal(next.props['aria-label'], '下一条');
  assert.match(previous.props.className, /(?:^|\s)generation-detail-nav(?:\s|$)/);
  assert.match(previous.props.className, /(?:^|\s)previous(?:\s|$)/);
  assert.match(next.props.className, /(?:^|\s)generation-detail-nav(?:\s|$)/);
  assert.match(next.props.className, /(?:^|\s)next(?:\s|$)/);
  assert.doesNotMatch(text(dialog.props.footer), /上一条|下一条/);
  assert.match(text(dialog.props.footer), /保存人工草稿/);
  assert.match(text(dialog.props.footer), /审核确认入库/);
  const nativeDialog = h.renderDialog(dialog.props);
  assert.equal(nativeDialog.type, 'dialog');
  assert.ok(nativeDialog.props.children.includes(dialog.props.sideControls));
  const surface = nativeDialog.props.children.find(
    (child) => child?.props?.className === 'case-dialog-surface',
  );
  assert.ok(surface);
  assert.ok(surface.props.children.props.children.includes(dialog.props.footer));
  assert.ok(!surface.props.children.props.children.includes(dialog.props.sideControls));
});

test('first suggestion disables previous navigation and keeps edits after a save failure', () => {
  const h = harness({ first: true });
  assert.equal(h.button('上一条').props.disabled, true);
  assert.ok(h.render().some((node) => text(node).includes('已到第一条。')));
  h.edit('验证用例子项', '第一条未成功保存的内容');
  h.props.serverError = '保存失败，请稍后重试';
  assert.equal(h.button('保存并上一条').props.disabled, true);
  assert.equal(h.button('保存并下一条').props.disabled, false);
  assert.equal(h.field('验证用例子项', 'textarea').props.value, '第一条未成功保存的内容');
  assert.ok(h.errors().includes('保存失败，请稍后重试'));
});

test('editing saves before next without affirming review and preserves the submitted draft and category', () => {
  const h = harness();
  h.edit('验证用例子项', '修改后的订单提交');
  h.render()
    .find((node) => node.type === 'select' && node.props.label === '用例分类')
    .props.onChange('7');
  const next = h.button('保存并下一条');
  assert.equal(next.props.type, 'submit');
  assert.equal(next.props.form, 'generation-detail-form');
  assert.equal(next.props.onClick, undefined);
  h.submit('next');
  const [draft, revision, intent] = h.saved[0];
  assert.equal(intent, 'next');
  assert.equal(revision, 0);
  assert.equal(draft.revision, 1);
  assert.equal(draft.draft.title, '修改后的订单提交');
  assert.deepEqual(draft.editedFields, ['title']);
  assert.equal(draft.categoryId, 7);
  assert.equal(draft.evidenceChecked, false);
  assert.equal(draft.resolved, false);
  assert.equal(h.next(), 0);
});

test('single review affirms evidence through the review action without an extra checkbox', () => {
  const h = harness();
  assert.equal(h.button('审核确认入库').props.value, 'review');
  assert.ok(!h.render().some((n) => n.type === 'label' && text(n).includes('已核对固定依据')));
  h.edit('预期结果', '订单已保存且状态正确');
  h.submit('review');
  assert.equal(h.saved.length, 1);
  assert.equal(h.saved[0][2], 'review');
  assert.equal(h.saved[0][0].draft.expected, '订单已保存且状态正确');
  assert.deepEqual(h.saved[0][0].editedFields, ['expected']);
  assert.equal(h.saved[0][0].status, '待审阅');
  assert.equal(h.saved[0][0].evidenceChecked, true);
  assert.equal(h.saved[0][0].resolved, true);
});

test('batch edit keeps its existing evidence check while ordinary single draft save is not review', () => {
  const batch = harness({ reviewMode: true });
  batch.submit('save');
  assert.equal(batch.saved.length, 0);
  batch.check('已核对固定依据');
  batch.submit('save');
  assert.equal(batch.saved[0][0].evidenceChecked, true);
  const single = harness();
  single.edit('预期结果', '新的待审阅草稿');
  single.submit('save');
  assert.equal(single.saved[0][0].evidenceChecked, false);
  assert.equal(single.saved[0][0].resolved, false);
});

test('manual handling and empty required fields get inline red error targets and clear after correction', () => {
  const h = harness({
    suggestion: { blocked: true, design: { ...harness().props.suggestion.design, expected: '' } },
  });
  const note = h.field('人工处理说明', 'textarea'),
    expected = h.field('预期结果', 'textarea');
  assert.equal(note.props['aria-invalid'], true);
  assert.equal(expected.props['aria-invalid'], true);
  assert.ok(note.props['aria-describedby']);
  assert.ok(expected.props['aria-describedby']);
  assert.ok(h.render().some((n) => n.type === 'span' && text(n).includes('本条需要人工处理')));
  h.submit('review');
  assert.equal(h.saved.length, 0);
  h.edit('人工处理说明', '已核对冲突并明确处理方式');
  h.edit('预期结果', '订单仅保存一次');
  assert.equal(h.field('人工处理说明', 'textarea').props['aria-invalid'], false);
  assert.equal(h.field('预期结果', 'textarea').props['aria-invalid'], false);
  h.submit('review');
  assert.equal(h.saved.length, 1);
});

test('changed current-version fields are marked individually until the target version is checked', () => {
  const base = harness().props.suggestion.design;
  const h = harness({
    suggestion: { before: base },
    handling: { status: '需人工确认', note: '已核对', revision: 1, evidenceChecked: false },
    currentCase: { ...base, id: 22, version: 4, expected: '库内预期已变化' },
  });
  assert.equal(h.field('预期结果', 'textarea').props['aria-invalid'], true);
  assert.equal(h.field('验证用例子项', 'textarea').props['aria-invalid'], false);
  h.check('已对照当前库v4');
  assert.equal(h.field('预期结果', 'textarea').props['aria-invalid'], false);
});

test('ignored suggestions cannot be reviewed and require a reason before an audit draft is saved', () => {
  const h = harness();
  h.check('忽略本建议');
  assert.equal(h.button('审核确认入库').props.disabled, true);
  h.submit('review');
  assert.equal(h.saved.length, 0);
  assert.ok(h.errors().includes('当前建议选择了忽略，不能审核入库。'));
  h.submit();
  assert.equal(h.saved.length, 0);
  h.edit('人工处理说明', '  不在本次范围内  ');
  h.submit();
  assert.equal(h.saved[0][2], 'save');
  assert.equal(h.saved[0][0].status, '已忽略');
  assert.equal(h.saved[0][0].note, '不在本次范围内');
  assert.equal(h.saved[0][0].resolved, false);
});

test('failed target review requires a reason and explicit current-version comparison', () => {
  const h = harness({
    handling: {
      status: '需人工确认',
      note: '',
      revision: 3,
      evidenceChecked: true,
      editedFields: [],
    },
    currentCase: { id: 22, version: 4, title: '库中设计', steps: '提交', expected: '成功' },
  });
  h.submit('review');
  assert.equal(h.saved.length, 0);
  assert.ok(h.errors().includes('忽略、解决冲突或处理失败项需要填写说明。'));
  h.edit('人工处理说明', '已对照当前版本');
  h.submit('review');
  assert.equal(h.saved.length, 0);
  assert.ok(h.errors().includes('请对照当前用例版本并确认，才能准备再次预览。'));
  h.check('已对照当前库v4');
  h.submit('review');
  assert.equal(h.saved[0][1], 3);
  assert.equal(h.saved[0][0].revision, 4);
  assert.equal(h.saved[0][0].reviewedTarget.id, 22);
  assert.equal(h.saved[0][0].reviewedTarget.version, 4);
  assert.equal(h.saved[0][2], 'review');
});

test('last suggestion disables navigation and retained server errors do not discard edits', () => {
  const h = harness({ last: true });
  assert.equal(h.button('下一条').props.disabled, true);
  assert.ok(h.render().some((node) => text(node).includes('已到最后一条。')));
  h.edit('验证用例子项', '保留未成功保存的内容');
  h.props.serverError = '保存失败，请稍后重试';
  assert.equal(h.button('保存并下一条').props.disabled, true);
  assert.equal(h.field('验证用例子项', 'textarea').props.value, '保留未成功保存的内容');
  assert.ok(h.errors().includes('保存失败，请稍后重试'));
});

test('applied and reused suggestions remain browsable but cannot replay save or review', () => {
  for (const status of ['已应用', '已复用']) {
    const h = harness({ handling: { status, evidenceChecked: true, revision: 2 } });
    assert.equal(h.button('保存人工草稿'), undefined);
    assert.equal(h.button('审核确认入库'), undefined);
    assert.equal(h.field('验证用例子项', 'textarea').props.disabled, true);
    assert.equal(h.field('验证用例子项', 'textarea').props.readOnly, true);
    h.submit('review');
    h.submit('save');
    assert.equal(h.saved.length, 0);
    h.button('下一条').props.onClick();
    assert.equal(h.next(), 1);
    h.button('上一条').props.onClick();
    assert.equal(h.previous(), 1);
  }
});

test('busy detail blocks submissions and disables navigation and review', () => {
  const h = harness({ busy: true });
  assert.equal(h.button('上一条').props.disabled, true);
  assert.equal(h.button('下一条').props.disabled, true);
  assert.equal(h.button('审核确认入库').props.disabled, true);
  h.submit('review');
  h.submit('next');
  h.submit('previous');
  assert.equal(h.saved.length, 0);
  assert.equal(h.previous(), 0);
  assert.equal(h.next(), 0);
});

test('queued and running applications lock editing but allow closing and browsing without resaving', () => {
  for (const applicationStatus of ['QUEUED', 'RUNNING']) {
    const h = harness({ applicationStatus });
    // A polling update can differ from the draft opened before confirmation.
    h.props.record.handling[h.props.suggestion.key] = [
      { status: '待审阅', revision: 2, evidenceChecked: true, note: '已保存修订' },
    ];
    let closed = false;
    h.props.onClose = () => (closed = true);
    assert.equal(h.button('关闭').props.disabled, false);
    h.button('关闭').props.onClick();
    assert.equal(closed, true);
    const dialog = h.render().find((node) => node.type === 'dialog');
    assert.equal(dialog.props.busy, false);
    for (const label of ['上一条', '下一条']) {
      assert.equal(h.button(label).props.disabled, false);
      assert.equal(h.button(label).props.type, 'button');
      h.button(label).props.onClick();
    }
    assert.equal(h.previous(), 1);
    assert.equal(h.next(), 1);
    assert.equal(h.button('保存人工草稿').props.disabled, true);
    assert.equal(h.button('审核确认入库').props.disabled, true);
    assert.equal(h.field('验证用例子项', 'textarea').props.disabled, true);
    h.submit('review');
    h.submit('save');
    assert.equal(h.saved.length, 0);
    assert.ok(h.render().some((node) => node.props?.role === 'status' && /后台/.test(text(node))));
    h.props.applicationStatus = 'COMPLETED';
    h.props.record.handling[h.props.suggestion.key] = [
      { status: '已应用', revision: 3, evidenceChecked: true },
    ];
    assert.equal(h.button('审核确认入库'), undefined);
    assert.equal(h.button('下一条').props.disabled, false);
  }
});

test('a failed application unlocks manual review while a request still blocks modal navigation', () => {
  const h = harness({ applicationStatus: 'FAILED' });
  assert.equal(h.button('审核确认入库').props.disabled, false);
  assert.equal(h.field('验证用例子项', 'textarea').props.disabled, false);
  h.props.busy = true;
  assert.equal(h.button('关闭').props.disabled, true);
  assert.equal(h.button('下一条').props.disabled, true);
  assert.equal(h.button('审核确认入库').props.disabled, true);
});
