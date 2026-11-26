const { compileModule, evaluateModule } = require('./helpers/load.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(file) {
  const exports = {};
  const code = compileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  evaluateModule(
    code,
    (name) =>
      name.startsWith('.') ? load(path.resolve(path.dirname(file), name + '.ts')) : require(name),
    exports,
  );
  return exports;
}
const api = (file) => load(path.resolve(__dirname, '../src', file + '.ts'));
const risk = api('riskApi');
const chat = api('chatApi');
const handlers = [
  risk.riskError,
  api('codeAnalysisApi').codeError,
  api('changeAnalysisApi').changeError,
  api('generationApi').generationError,
  api('caseAnalysisApi').reviewError,
  chat.chatError,
];

test('all five analyses, their saved failures and chat show the same actionable AI errors', () => {
  const end = () => assert.fail('AI service failure must not end the platform session');
  for (const [code, expected] of [
    ['ai_call_busy', /额度.*占用.*未发送/],
    ['ai_cli_unverified', /运行环境尚未就绪/],
    ['ai_cli_execution_failed', /CLI 最终执行失败.*内部可能已尝试多次/],
    ['ai_preference_changed', /其他窗口切换/],
    ['ai_gateway_timeout', /AI中转.*超时.*504.*未取得完整结果.*未自动重试/],
    ['ai_gateway_error', /AI中转.*502/],
    ['ai_service_unavailable', /AI服务.*503/],
    ['ai_timeout', /AI请求超时.*计费.*未自动重试/],
    ['ai_connection_failed', /无法连接个人AI服务/],
    ['ai_auth_failed', /AI密钥失效/],
    ['ai_parameters_rejected', /AI服务拒绝本次请求.*模型参数.*输入容量/],
    ['ai_request_rejected', /400\/422.*原因尚未识别.*未自动重试/],
    ['ai_context_limit', /超出.*上下文容量.*未截断.*自动重试/],
    ['ai_input_too_large', /过长文本字段.*过大的请求.*400\/413\/422.*未截断.*自动重试/],
    ['ai_output_limit', /不接受.*输出Token配置.*未自动调整/],
    ['ai_quota_or_rate_limit', /AI额度不足或达到限流/],
    ['ai_incomplete_response', /AI回复未完整结束/],
  ]) {
    const messages = handlers.map((handler) => handler(new Error(code), end));
    messages.push(risk.riskTaskFailure(code), chat.chatFailure(code));
    for (const message of messages) assert.match(message, expected);
    assert.equal(new Set(messages).size, 1, code);
  }
});

test('shared AI messages retain session expiry, uncertain responses and module validation details', () => {
  for (const handler of handlers) {
    let expired = false;
    const end = () => (expired = true);
    assert.match(handler(new Error('unknown_ai_failure'), end), /操作结果尚未确认/);
    assert.equal(expired, false);
    assert.equal(handler(new Error('not_authenticated'), end), '登录状态已失效。');
    assert.equal(expired, true);
  }
  assert.match(
    risk.riskTaskFailure('risk_report_invalid|risks[1]|inconsistent_reference'),
    /risks\[1\].*功能与风险关联不一致/,
  );
  assert.equal(risk.riskTaskFailure(''), '');
  assert.match(risk.riskTaskFailure('unknown_failure'), /分析失败/);
});

test('Skill assistance recognizes shared request rejections without exposing remote text', () => {
  const { skillError } = api('skillApi');
  const end = () => assert.fail('AI rejection must not end the platform session');
  for (const [code, expected] of [
    ['ai_request_rejected', /400\/422.*原因尚未识别/],
    ['ai_context_limit', /超出.*上下文容量/],
    ['ai_input_too_large', /过长文本字段.*过大的请求/],
    ['ai_output_limit', /输出Token配置/],
  ])
    assert.match(skillError(new Error(code), end), expected);
});
