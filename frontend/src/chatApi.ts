import { parseCallMetadata } from './aiConfiguration';
import { apiErrorMessage, apiRequest } from './api/http';
import { aiErrors } from './aiErrors';

export type ChatTurn = {
  id: number;
  report_id: number;
  function_key: string;
  risk_key: string;
  request_id: string;
  question: string;
  answer: string;
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  error_code: string;
  actor: string;
  can_cancel: boolean;
  created_at: string;
  ai: {
    name: string;
    model: string;
    version: number;
    call_mode?: 'RESPONSES_API' | 'CODEX_EXEC';
    preference_version?: number;
  };
};
export const chatStates = {
  QUEUED: '排队中',
  RUNNING: '正在回答',
  COMPLETED: '已完成',
  FAILED: '失败',
  CANCELLED: '已停止',
};
const errors: Record<string, string> = {
  ...aiErrors,
  chat_busy: '当前对话还有请求正在处理，请等待或停止后再发送。',
  chat_history_changed: '其他成员已更新对话，请刷新历史后重新发送。',
  chat_request_conflict: '重复请求内容不一致，请重新加载。',
  chat_cancel_owner_only: '只有本轮发起人可以停止回答。',
  chat_worker_interrupted: '服务重启中断了回答，未自动重试；可能已计费，请确认后手动重试。',
  chat_internal_error: '对话处理失败，原消息已保存，请重试或联系管理员。',
  project_access_denied: '已无权限访问此项目。',
  project_not_found: '项目不存在或已无访问权限。',
  risk_report_not_found: '找不到关联分析结果。',
  risk_function_not_found: '找不到关联功能，请返回需求分析页重新进入。',
  risk_reference_invalid: '风险引用与当前功能不匹配，请重新进入。',
  chat_access_lost: '执行时账号或项目权限已失效。',
};
export const chatFailure = (code: string) =>
  errors[code] || '本轮处理失败，请刷新核对或联系管理员。';
export const chatError = (reason: unknown, end: () => void) => apiErrorMessage(reason, end, errors);

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('invalid_chat_response');
  return value as Record<string, unknown>;
}
export function parseChatTurn(value: unknown, reportId: number): ChatTurn {
  const v = record(value),
    ai = record(v.ai);
  if (
    !Number.isSafeInteger(v.id) ||
    Number(v.id) <= 0 ||
    v.report_id !== reportId ||
    typeof v.status !== 'string' ||
    !Object.hasOwn(chatStates, v.status) ||
    [
      'function_key',
      'risk_key',
      'request_id',
      'question',
      'answer',
      'error_code',
      'actor',
      'created_at',
    ].some((k) => typeof v[k] !== 'string') ||
    typeof v.can_cancel !== 'boolean' ||
    !parseCallMetadata(ai as Record<string, unknown>) ||
    typeof ai.name !== 'string' ||
    typeof ai.model !== 'string' ||
    !Number.isSafeInteger(ai.version)
  )
    throw new Error('invalid_chat_response');
  return v as ChatTurn;
}
export async function chatHistory(
  base: string,
  reportId: number,
  signal: AbortSignal,
  before?: number,
  functionKey = '',
) {
  const query = new URLSearchParams();
  if (before) query.set('before', String(before));
  if (functionKey) query.set('function_key', functionKey);
  const v = record(
    await apiRequest<unknown>(base + (query.size ? `?${query}` : ''), {
      signal,
      timeoutMs: 15000,
    }),
  );
  if (v.report_id !== reportId || !Array.isArray(v.items) || typeof v.has_more !== 'boolean')
    throw new Error('invalid_chat_response');
  return { items: v.items.map((item) => parseChatTurn(item, reportId)), has_more: v.has_more };
}
export async function chatSend(
  base: string,
  reportId: number,
  payload: { request_id: string; question: string; last_turn_id: number; risk_key?: string },
  signal: AbortSignal,
  functionKey = '',
) {
  return parseChatTurn(
    await apiRequest(
      base + (functionKey ? `?function_key=${encodeURIComponent(functionKey)}` : ''),
      {
        method: 'POST',
        body: JSON.stringify(payload),
        signal,
        timeoutMs: 20000,
      },
    ),
    reportId,
  );
}
