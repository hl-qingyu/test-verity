const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const code = ts.transpileModule(
  fs.readFileSync(path.resolve(__dirname, '../src/useMaterialDrag.ts'), 'utf8'),
  {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  },
).outputText;
function harness(disabled = false) {
  let view,
    captured = false,
    target = { dataset: { materialProject: '1', materialGroup: '7' } };
  const moves = [],
    exports = {};
  new Function('exports', 'require', code)(exports, () => ({
    useState: () => [
      null,
      (v) => {
        view = v;
      },
    ],
    useRef: (value) => ({ current: value }),
    useEffect: () => {},
  }));
  const hook = exports.useMaterialDrag({
    projectId: 1,
    disabled,
    onMove: (id, group) => moves.push({ id, group }),
  });
  const row = {
    setPointerCapture: () => {
      captured = true;
    },
    hasPointerCapture: () => captured,
    releasePointerCapture: () => {
      captured = false;
    },
  };
  const event = (x, blocked = false) => ({
    button: 0,
    pointerId: 2,
    clientX: x,
    clientY: 10,
    currentTarget: row,
    target: { closest: () => (blocked ? {} : null) },
  });
  const source = { id: 3, name: '原型', group_id: 5 };
  return {
    hook,
    moves,
    event,
    source,
    view: () => view,
    captured: () => captured,
    point: () => (target ? { closest: () => target } : null),
    target: (group, project = '1') => {
      target =
        group === undefined
          ? null
          : {
              dataset: {
                materialProject: project,
                materialGroup: group === null ? 'none' : String(group),
              },
            };
    },
  };
}
test('dragging across groups captures the pointer and submits once without treating a click as a move', () => {
  const h = harness(),
    previous = global.document;
  global.document = { elementFromPoint: h.point };
  try {
    h.hook.pointerDown(h.event(10), h.source);
    h.hook.pointerMove(h.event(13));
    h.hook.pointerUp(h.event(13));
    assert.equal(h.moves.length, 0);
    assert.equal(h.hook.suppressClick.current, false);
    h.hook.pointerDown(h.event(10), h.source);
    h.hook.pointerMove(h.event(40));
    assert.equal(h.captured(), true);
    assert.equal(h.view().target, 7);
    h.hook.pointerUp(h.event(40));
    h.hook.pointerUp(h.event(40));
    assert.deepEqual(h.moves, [{ id: 3, group: 7 }]);
    assert.equal(h.source.group_id, 5);
    assert.equal(h.view(), null);
    assert.equal(h.captured(), false);
    assert.equal(h.hook.suppressClick.current, true);
  } finally {
    global.document = previous;
  }
});
test('same group, outside area, cancelled, foreign-project and disabled drags do not submit; ungrouped accepts drops', () => {
  const previous = global.document;
  try {
    for (const [group, project, cancel, blocked, disabled] of [
      [5, '1'],
      [undefined, '1'],
      [7, '2'],
      [7, '1', true],
      [7, '1', false, true],
      [7, '1', false, false, true],
    ]) {
      const h = harness(disabled);
      global.document = { elementFromPoint: h.point };
      h.target(group, project);
      h.hook.pointerDown(h.event(10, blocked), h.source);
      h.hook.pointerMove(h.event(40));
      if (cancel) h.hook.cancel();
      h.hook.pointerUp(h.event(40));
      assert.equal(h.moves.length, 0);
    }
    const h = harness();
    global.document = { elementFromPoint: h.point };
    h.target(null);
    h.hook.pointerDown(h.event(10), h.source);
    h.hook.pointerMove(h.event(40));
    h.hook.pointerUp(h.event(40));
    assert.deepEqual(h.moves, [{ id: 3, group: null }]);
  } finally {
    global.document = previous;
  }
});
