const { load } = require('./helpers/load.cjs');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { MemoryRouter, Routes, Route } = require('react-router-dom');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const api = load(path.resolve(__dirname, '../src/chatApi.ts'));
const turn = {
  id: 7,
  report_id: 4,
  function_key: '',
  risk_key: '',
  request_id: 'uuid',
  question: '继续检查',
  answer: '',
  status: 'QUEUED',
  error_code: '',
  actor: '发起人',
  can_cancel: true,
  created_at: '2026-09-17T00:00:00Z',
  ai: { name: '本人AI', model: 'model', version: 1 },
};

test('chat response validates conversation identity, state and required fields', () => {
  assert.equal(api.parseChatTurn(turn, 4).id, 7);
  for (const bad of [
    { ...turn, report_id: 5 },
    { ...turn, status: 'success' },
    { ...turn, answer: null },
    { ...turn, ai: { name: 'other' } },
  ]) {
    assert.throws(() => api.parseChatTurn(bad, 4));
  }
});

test('chat sends stable request identity via shared HTTP and retains cancellation and error semantics', async () => {
  const original = global.fetch;
  const controller = new AbortController();
  const payload = { request_id: 'same-request', question: '继续检查', last_turn_id: 6 };
  try {
    global.fetch = async (url, options) => {
      assert.equal(url, '/api/projects/2/requirements/risk-reports/4/chat');
      assert.equal(options.method, 'POST');
      assert.deepEqual(JSON.parse(options.body), payload);
      assert.ok(!options.headers.has('Authorization'));
      assert.ok(options.signal);
      return new Response(JSON.stringify(turn), { status: 202 });
    };
    assert.equal(
      (
        await api.chatSend(
          '/api/projects/2/requirements/risk-reports/4/chat',
          4,
          payload,
          controller.signal,
        )
      ).id,
      7,
    );
    global.fetch = async () =>
      new Response(JSON.stringify({ detail: 'chat_history_changed' }), { status: 409 });
    await assert.rejects(
      api.chatSend(
        '/api/projects/2/requirements/risk-reports/4/chat',
        4,
        payload,
        controller.signal,
      ),
      /chat_history_changed/,
    );
    global.fetch = async () => new Response('{}', { status: 401 });
    await assert.rejects(
      api.chatHistory('/api/projects/2/requirements/risk-reports/4/chat', 4, controller.signal),
      /not_authenticated/,
    );
    global.fetch = async (url, options) => {
      options.signal.throwIfAborted();
      throw Error('unexpected');
    };
    controller.abort();
    await assert.rejects(
      api.chatSend(
        '/api/projects/2/requirements/risk-reports/4/chat',
        4,
        payload,
        controller.signal,
      ),
      { name: 'AbortError' },
    );
  } finally {
    global.fetch = original;
  }
});

test('function conversations keep their own history query and risk reference', async () => {
  const original = global.fetch;
  const controller = new AbortController();
  try {
    global.fetch = async (url, options) => {
      assert.equal(url, '/chat?function_key=F1');
      assert.equal(JSON.parse(options.body).risk_key, 'R1');
      return new Response(JSON.stringify({ ...turn, function_key: 'F1', risk_key: 'R1' }), {
        status: 202,
      });
    };
    const result = await api.chatSend(
      '/chat',
      4,
      { request_id: 'scoped', question: '追问', last_turn_id: 0, risk_key: 'R1' },
      controller.signal,
      'F1',
    );
    assert.equal(result.function_key, 'F1');
    global.fetch = async (url) => {
      assert.equal(url, '/chat?before=7&function_key=F1');
      return new Response(
        JSON.stringify({ report_id: 4, items: [{ ...turn, function_key: 'F1' }], has_more: false }),
      );
    };
    assert.equal((await api.chatHistory('/chat', 4, controller.signal, 7, 'F1')).items.length, 1);
  } finally {
    global.fetch = original;
  }
});

test('conversation layout keeps prototype columns, message bubbles and visible side scrollbars', () => {
  const css = fs.readFileSync(path.resolve(__dirname, '../src/requirement-chat.css'), 'utf8');
  assert.match(css, /grid-template-columns:\s*230px minmax\(0, 1fr\) 280px/);
  assert.match(
    css,
    /\.chat-sidebar,[\s\S]*?\.chat-context[\s\S]*?overflow-y:\s*scroll\s*!important/,
  );
  assert.match(css, /scrollbar-color:/);
  const { RequirementChat } = load(path.resolve(__dirname, '../src/RequirementChat.tsx'));
  const element = React.createElement(
    MemoryRouter,
    { initialEntries: ['/requirements/chat/4?function=orders&risk=R1'] },
    React.createElement(
      Routes,
      null,
      React.createElement(Route, {
        path: '/requirements/chat/:reportId',
        element: React.createElement(RequirementChat, { project: { id: 1 }, onSessionEnd() {} }),
      }),
    ),
  );
  const markup = renderToStaticMarkup(element);
  assert.match(markup, /切换需求分析对话/);
  assert.match(markup, /本轮追问引用风险：R1/);
  assert.match(markup, /关联风险引用/);
  assert.match(markup, /<textarea/);
  const shared = fs.readFileSync(path.resolve(__dirname, '../src/requirement-ui.css'), 'utf8');
  assert.match(
    shared,
    /\.chat-history \.chat-history-item\[aria-current='page'\][\s\S]*?border-left-color:/,
  );
  assert.match(shared, /\.chat-history \.chat-history-title\s*\{\s*font-weight:/);
  assert.match(shared, /\.chat-history \.chat-history-item:focus-visible\s*\{\s*outline:/);
});
