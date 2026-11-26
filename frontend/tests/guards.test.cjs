const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { load } = require('./helpers/load.cjs');

test('shared payload guards keep module errors, integer bounds and array limits', () => {
  const { createGuards } = load(path.resolve(__dirname, '../src/api/guards.ts'));
  const { obj, int, str, bool, nullable, list, choice, hash64 } = createGuards('fixture_invalid');
  assert.deepEqual(obj({ id: 1 }), { id: 1 });
  assert.throws(() => obj([]), /fixture_invalid/);
  assert.throws(() => int(0), /fixture_invalid/);
  assert.equal(int(0, 0), 0);
  assert.throws(() => int(Number.MAX_SAFE_INTEGER + 1), /fixture_invalid/);
  assert.throws(() => bool('true'), /fixture_invalid/);
  assert.equal(nullable(undefined, str), null);
  assert.deepEqual(list(['a'], str, 1), ['a']);
  assert.throws(() => list(['a', 'b'], str, 1), /fixture_invalid/);
  assert.throws(() => choice('__proto__', { accepted: true }), /fixture_invalid/);
  assert.equal(hash64('a'.repeat(64)), 'a'.repeat(64));
});
