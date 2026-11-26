const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = path.resolve(__dirname, '../src');
function load(file, react = React) {
  const code = compileModule(fs.readFileSync(path.join(root, file), 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const exports = {};
  evaluateModule(code, (name) => (name === 'react' ? react : require(name)), exports);
  return exports;
}

test('themed selects preserve form values, disabled choices and escaped labels without native menus', () => {
  const { Select, FormSelect, selectOptions } = load('FormSelect.tsx');
  const choices = [
    false,
    React.createElement('option', { value: '' }, '请选择'),
    React.createElement('option', { value: 7, disabled: true }, '<script>'),
    React.createElement(
      React.Fragment,
      null,
      React.createElement('option', { value: 'ADMIN' }, '管理员'),
    ),
  ];
  assert.deepEqual(
    selectOptions(choices).map((o) => [o.value, o.disabled]),
    [
      ['', undefined],
      ['7', true],
      ['ADMIN', undefined],
    ],
  );
  const html = renderToStaticMarkup(
    React.createElement(
      Select,
      { name: 'platform_role', defaultValue: 'ADMIN', required: true, 'aria-label': '角色' },
      choices,
    ),
  );
  assert.match(html, /name="platform_role" value="ADMIN"/);
  assert.match(html, /role="combobox"/);
  assert.match(html, /role="option"[^>]*disabled=""/);
  assert.match(html, /&lt;script&gt;/);
  assert.ok(!html.includes('✓') && !html.includes('⌄'));
  assert.match(html, /aria-selected="true"/);
  assert.ok(!/<select|<option|<datalist|<script>/.test(html));
  const editable = renderToStaticMarkup(
    React.createElement(FormSelect, {
      editable: true,
      value: '自定义业务流程',
      label: '类型',
      options: [{ value: '业务流程', label: '业务流程' }],
      onChange() {},
    }),
  );
  assert.match(editable, /value="自定义业务流程"/);
  assert.ok(!/list="|<datalist/.test(editable));
});

test('form validation blocks missing required selections with application text', () => {
  let message = '',
    submissions = 0,
    prevented = 0,
    focused = 0;
  const { Form } = load('Form.tsx', {
    useState: () => [
      '',
      (value) => {
        message = value;
      },
    ],
  });
  const form = Form({ onSubmit: () => submissions++, children: null });
  assert.equal(form.props.noValidate, true);
  const originalElement = global.HTMLElement;
  global.HTMLElement = class {};
  const originalInput = global.HTMLInputElement,
    originalText = global.HTMLTextAreaElement;
  global.HTMLInputElement = class {};
  global.HTMLTextAreaElement = class {};
  try {
    form.props.onSubmit({
      preventDefault: () => prevented++,
      currentTarget: { elements: [], querySelector: () => ({ focus: () => focused++ }) },
    });
    assert.equal(submissions, 0);
    assert.equal(prevented, 1);
    assert.equal(focused, 1);
    assert.match(message, /必填/);
    form.props.onSubmit({ currentTarget: { elements: [], querySelector: () => null } });
    assert.equal(submissions, 1);
  } finally {
    global.HTMLElement = originalElement;
    global.HTMLInputElement = originalInput;
    global.HTMLTextAreaElement = originalText;
  }
});

test('a form can customize invalid input feedback while preserving validation and focus', () => {
  let message = '',
    submissions = 0,
    focused = 0;
  const { Form } = load('Form.tsx', {
    useState: () => ['', (value) => (message = value)],
  });
  const originalElement = global.HTMLElement,
    originalInput = global.HTMLInputElement,
    originalText = global.HTMLTextAreaElement;
  global.HTMLElement = class {};
  global.HTMLInputElement = class extends global.HTMLElement {
    willValidate = true;
    validity = { valid: false, valueMissing: false };
    focus() {
      focused++;
    }
  };
  global.HTMLTextAreaElement = class extends global.HTMLElement {};
  try {
    const input = new global.HTMLInputElement();
    const form = Form({
      validationMessage: '登录校验提示',
      onSubmit: () => submissions++,
      children: null,
    });
    assert.equal(form.props.validationMessage, undefined, 'custom props must not reach the DOM');
    const event = {
      preventDefault() {},
      currentTarget: { elements: [input], querySelector: () => null },
    };
    form.props.onSubmit(event);
    assert.equal(message, '登录校验提示');
    assert.equal(submissions, 0);
    assert.equal(focused, 1);
    input.validity.valid = true;
    form.props.onSubmit(event);
    assert.equal(submissions, 1);
    assert.equal(message, '');
  } finally {
    global.HTMLElement = originalElement;
    global.HTMLInputElement = originalInput;
    global.HTMLTextAreaElement = originalText;
  }
});

test('dropdown keyboard navigation skips disabled choices and Escape preserves the parent dialog', () => {
  const refs = [],
    changes = [];
  const { FormSelect } = load('FormSelect.tsx', {
    useId: () => 'test-options',
    useRef: (value) => {
      const ref = { current: value };
      refs.push(ref);
      return ref;
    },
    useState: () => [false, () => {}],
    useEffect() {},
  });
  const tree = FormSelect({
    value: 'one',
    options: [
      { value: 'one', label: '一' },
      { value: 'blocked', label: '禁用', disabled: true },
      { value: 'two', label: '二' },
    ],
    onChange: (value) => changes.push(value),
  });
  let opened = true,
    focus = '',
    prevented = 0,
    stopped = 0;
  const options = [
    {
      focus: () => {
        focus = 'one';
      },
    },
    {
      focus: () => {
        focus = 'two';
      },
    },
  ];
  refs[0].current = {
    focus: () => {
      focus = 'trigger';
    },
  };
  refs[1].current = {
    matches: () => opened,
    hidePopover: () => {
      opened = false;
    },
    querySelectorAll: () => options,
  };
  const originalDocument = global.document;
  global.document = { activeElement: options[0] };
  try {
    tree.props.onKeyDown({ key: 'ArrowDown', preventDefault: () => prevented++ });
    assert.equal(focus, 'two');
    tree.props.onKeyDown({
      key: 'Escape',
      preventDefault: () => prevented++,
      stopPropagation: () => stopped++,
    });
    assert.equal(opened, false);
    assert.equal(focus, 'trigger');
    assert.equal(stopped, 1);
    assert.equal(prevented, 2);
    const optionPanel = React.Children.toArray(tree.props.children).find(
      (child) => child.props?.role === 'listbox',
    );
    React.Children.toArray(optionPanel.props.children)[1].props.onClick();
    assert.deepEqual(changes, []);
  } finally {
    global.document = originalDocument;
  }
});

test('UI conventions prevent new native dropdowns, business dialogs and validation bubbles', () => {
  for (const file of fs.readdirSync(root).filter((f) => /\.tsx?$/.test(f))) {
    const source = fs.readFileSync(path.join(root, file), 'utf8');
    const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    function visit(node) {
      if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
        const name = node.tagName.getText(ast);
        assert.ok(!['select', 'datalist'].includes(name), `${file}: use FormSelect/Select`);
        assert.ok(
          name !== 'form' || file === 'Form.tsx',
          `${file}: use Form for inline validation`,
        );
      }
      if (ts.isCallExpression(node)) {
        const call = node.expression.getText(ast);
        assert.ok(
          !/^(?:window\.|globalThis\.)?(alert|prompt)$|^(?:window\.|globalThis\.)confirm$|\.reportValidity$/.test(
            call,
          ),
          `${file}: browser business dialog`,
        );
      }
      ts.forEachChild(node, visit);
    }
    visit(ast);
  }
});
