const { load: loadModule } = require('./helpers/load.cjs');
const { test } = require('node:test'),
  assert = require('node:assert/strict'),
  path = require('node:path');
function load(transport = {}) {
  return loadModule(path.resolve(__dirname, '../src/analysisCandidateApi.ts'), {
    './api/http': transport,
  });
}
function candidate() {
  return {
    candidateJson: '{"risks":[{"priority":"P2","priority":"P1"}]}',
    sha256: 'a'.repeat(64),
    items: [
      {
        group: 'risks',
        ordinal: 1,
        title: '冲突候选',
        rawJson: '{"priority":"P2","priority":"P1"}',
        conflicts: [{ path: 'priority', values: ['"P2"', '"P1"'] }],
      },
    ],
    conflicts: [{ path: 'risks[0].priority', values: ['"P2"', '"P1"'] }],
    parseError: false,
    errorCode: 'risk_json_invalid',
    canEdit: true,
    published: false,
    history: [],
  };
}
test('candidate parsing keeps conflicting values and rejects malformed permission, audit and identity tokens', () => {
  const api = load(),
    value = candidate(),
    before = JSON.stringify(value);
  assert.equal(api.parseAnalysisCandidate(value).items.length, 1);
  assert.equal(JSON.stringify(value), before);
  for (const patch of [
    { sha256: 'invalid' },
    { canEdit: 'true' },
    { published: 'yes' },
    { items: [null] },
    { conflicts: [{ path: 'p', values: [1] }] },
    { history: [{ reason: 'lost audit' }] },
    { parseError: null },
  ])
    assert.throws(() => api.parseAnalysisCandidate({ ...value, ...patch }));
});
test('candidate GET and manual POST use common transport, preserve cancellation and never retry a failed request', async () => {
  const calls = [],
    controller = new AbortController(),
    response = candidate();
  let failed = false;
  const api = load({
    apiRequest: async (url, options) => {
      calls.push([url, options]);
      if (failed) throw Error('candidate_review_changed');
      return response;
    },
  });
  await api.candidateReviewRequest('/api/projects/3/code-analysis/1/candidate-review', {
    signal: controller.signal,
  });
  const body = JSON.stringify({
    request_id: 'fixed-id',
    base_sha256: response.sha256,
    candidate_json: '{}',
    reason: '保留P1',
    confirmed: true,
  });
  await api.candidateReviewRequest(calls[0][0], { method: 'POST', body });
  assert.equal(calls[0][1].signal, controller.signal);
  assert.equal(calls[1][1].body, body);
  failed = true;
  await assert.rejects(
    api.candidateReviewRequest(calls[0][0], { method: 'POST', body }),
    /candidate_review_changed/,
  );
  assert.equal(calls.length, 3);
});
