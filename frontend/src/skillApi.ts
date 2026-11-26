import { createGuards } from './api/guards';
import { parseCallMetadata } from './aiConfiguration';
import { apiRequest, apiErrorMessage } from './api/http';
import { aiErrors } from './aiErrors';

export type SkillSummary = {
  key: string;
  name: string;
  version: string;
  icon: string;
  token: string;
  file_count: number;
};
export type SkillFile = {
  id: string;
  path: string;
  type: string;
  sha256: string;
  usage: 'current' | 'legacy' | 'reference';
  editable: boolean;
};
export type SkillPackage = SkillSummary & { files: SkillFile[] };
export type SkillContent = SkillFile & { key: string; token: string; text: string; body: string };
export type SkillBundle = SkillPackage & { contents: SkillContent[] };
export type SkillTurn = {
  id: number;
  skill_key: string;
  question: string;
  answer: string;
  candidate_body: string;
  base_body: string;
  base_token: string;
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  error_code: string;
  created_at: string;
  references: string[];
  ai: {
    name: string;
    model: string;
    version: number;
    call_mode?: 'RESPONSES_API' | 'CODEX_EXEC';
    preference_version?: number;
  };
};
export type SkillHistory = { items: SkillTurn[]; has_more: boolean };
export const skillErrors: Record<string, string> = {
  ...aiErrors,
  admin_required: '当前操作需要有效的平台管理员权限。',
  skill_not_found: '此Skill不存在。',
  skill_file_unavailable: 'Skill文件不可用，请管理员检查目录和读取权限。',
  skill_resources_invalid: 'Skill调用清单或必需规则文件无效，请管理员检查文件路径、内容和顺序。',
  skill_file_not_found: '此文件已不存在，请重新加载文件目录。',
  skill_file_busy_or_unwritable: '文件正在使用或后端没有读写权限，请稍后重试或联系管理员。',
  skill_content_changed: 'Skill文件已变化。草稿仍保留，请重新加载并核对后再操作。',
  skill_request_conflict: '此请求标识对应的内容已变化，请重新打开编辑并核对。',
  skill_body_invalid: '正文不能为空，且不能超过200000字符。',
  skill_reference_invalid: '参考文件已变化或不在当前范围内，请重新选择。',
  skill_package_too_large: 'Skill文件数量或大小超出平台限制，请管理员核对。',
  skill_chat_busy: '本Skill对话仍有排队或执行中的回复，请等待或取消后再发送。',
  skill_chat_history_changed: '对话已更新，请重新核对最新消息后再发送。',
  skill_chat_context_too_large: '对话与参考内容过大，请取消携带历史对话或减少参考文件。',
  skill_chat_not_found: '此对话不存在或不属于当前账号。',
  skill_ai_answer_invalid: 'AI回复格式不符合修改建议要求；原响应已保留，正文未修改。',
  skill_worker_interrupted: '后台执行中断，未自动重试；可核对后手动重新发送。',
  skill_chat_internal_error: '后台处理失败，正文未修改；可核对后手动重新发送。',
  skill_snapshot_missing: '历史任务未保存当时的Skill指令，请明确新建分析，不能用当前文件冒充重试。',
  ai_personal_required: '请先在平台设置中配置本人的AI服务。',
  ai_configuration_changed: '本人AI配置已变化，请核对后重新发送。',
  ai_connection_failed: '无法连接本人AI服务，请核对配置与网络。',
  ai_timeout: 'AI等待超时，服务可能已处理并计费，请核对后再决定是否重新发送。',
  ai_incomplete_response: 'AI未完成完整回复，未生成可应用建议。',
  ai_auth_failed: '本人AI密钥无效或过期，请核对配置。',
  ai_quota_or_rate_limit: 'AI额度不足或请求过于频繁，请核对本人服务。',
};
export function skillError(error: unknown, onSessionEnd: () => void) {
  return apiErrorMessage(error, onSessionEnd, skillErrors);
}
const guards = createGuards('invalid_response');
const object = guards.obj,
  str = guards.str,
  int = (value: unknown) => guards.int(value, 0),
  arr = guards.array,
  bool = guards.bool;

const hash = guards.hash64;
export function parseSkill(v: unknown): SkillSummary {
  const o = object(v);
  const key = str(o.key);
  if (
    ![
      'requirement-analysis',
      'case-generation',
      'case-analysis',
      'code-review',
      'change-impact',
    ].includes(key)
  )
    throw Error('invalid_response');
  return {
    key,
    name: str(o.name),
    version: str(o.version),
    icon: str(o.icon),
    token: hash(o.token),
    file_count: int(o.file_count),
  };
}
function parseFile(v: unknown): SkillFile {
  const o = object(v),
    path = str(o.path),
    usage = str(o.usage),
    id = str(o.id);
  if (
    !/^[0-9a-f]{24}$/.test(id) ||
    path.split('/').some((s) => s === '..' || !s) ||
    path.includes('\\') ||
    !['current', 'legacy', 'reference'].includes(usage) ||
    bool(o.editable) !== (path === 'SKILL.md')
  )
    throw Error('invalid_response');
  return {
    id,
    path,
    type: str(o.type),
    sha256: hash(o.sha256),
    usage: usage as SkillFile['usage'],
    editable: bool(o.editable),
  };
}
export function parsePackage(v: unknown): SkillPackage {
  const o = object(v),
    files = arr(o.files).map(parseFile);
  if (
    new Set(files.map((f) => f.id)).size !== files.length ||
    !files.some((f) => f.path === 'SKILL.md') ||
    files.length !== int(o.file_count)
  )
    throw Error('invalid_response');
  return { ...parseSkill(v), files };
}
export function parseContent(v: unknown): SkillContent {
  const o = object(v);
  return {
    ...parseFile(v),
    key: str(o.key),
    token: hash(o.token),
    text: str(o.text),
    body: str(o.body),
  };
}
export function parseTurn(v: unknown): SkillTurn {
  const o = object(v),
    ai = object(o.ai),
    status = str(o.status);
  if (!['QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED'].includes(status))
    throw Error('invalid_response');
  return {
    id: int(o.id),
    skill_key: str(o.skill_key),
    question: str(o.question),
    answer: str(o.answer),
    candidate_body: str(o.candidate_body),
    base_body: str(o.base_body),
    base_token: hash(o.base_token),
    status: status as SkillTurn['status'],
    error_code: str(o.error_code),
    created_at: str(o.created_at),
    references: arr(o.references).map(str),
    ai: {
      ...parseCallMetadata(ai),
      name: str(ai.name),
      model: str(ai.model),
      version: int(ai.version),
    },
  };
}
export function parseHistory(v: unknown): SkillHistory {
  const o = object(v);
  return { items: arr(o.items).map(parseTurn), has_more: bool(o.has_more) };
}
export async function skillList(signal?: AbortSignal) {
  const o = object(await apiRequest<unknown>('/api/skills', { signal }));
  return arr(o.items).map(parseSkill);
}
export async function skillPackage(key: string, signal?: AbortSignal) {
  const p = parsePackage(
    await apiRequest<unknown>(`/api/skills/${encodeURIComponent(key)}`, { signal }),
  );
  if (p.key !== key) throw Error('invalid_response');
  return p;
}
export async function skillBundle(
  key: string,
  previous?: SkillBundle,
  signal?: AbortSignal,
  refresh = false,
): Promise<SkillBundle> {
  const query = new URLSearchParams({ include_contents: 'true' });
  if (previous) query.set('known_token', previous.token);
  if (refresh) query.set('refresh', 'true');
  const raw = object(
    await apiRequest<unknown>(`/api/skills/${encodeURIComponent(key)}?${query}`, { signal }),
  );
  const p = parsePackage(raw);
  if (p.key !== key) throw Error('invalid_response');
  if (bool(raw.unchanged)) {
    if (arr(raw.contents).length) throw Error('invalid_response');
    if (!previous || previous.key !== key || previous.token !== p.token)
      throw Error('invalid_response');
    return previous;
  }
  const contents = arr(raw.contents).map(parseContent);
  if (
    contents.length !== p.files.length ||
    new Set(contents.map((f) => f.id)).size !== contents.length ||
    contents.some(
      (c) =>
        c.key !== key ||
        c.token !== p.token ||
        !p.files.some((f) => f.id === c.id && f.path === c.path && f.sha256 === c.sha256),
    )
  )
    throw Error('invalid_response');
  return { ...p, contents };
}
export async function skillSave(
  key: string,
  payload: { request_id: string; expected_token: string; body: string },
) {
  const result = parsePackage(
    await apiRequest<unknown>(`/api/skills/${key}/content`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  );
  if (result.key !== key) throw Error('invalid_response');
  return result;
}
export async function skillHistory(key: string, before?: number) {
  const h = parseHistory(
    await apiRequest<unknown>(`/api/skills/${key}/chat${before ? `?before=${before}` : ''}`),
  );
  if (h.items.some((t) => t.skill_key !== key)) throw Error('invalid_response');
  return h;
}
export type SkillChatInput = {
  request_id: string;
  expected_token: string;
  body: string;
  question: string;
  references: string[];
  last_turn_id: number;
  include_history: boolean;
};
export async function skillSend(key: string, payload: SkillChatInput) {
  const result = parseTurn(
    await apiRequest<unknown>(`/api/skills/${key}/chat`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  );
  if (result.skill_key !== key) throw Error('invalid_response');
  return result;
}
export async function skillCancel(key: string, id: number) {
  const result = parseTurn(
    await apiRequest<unknown>(`/api/skills/${key}/chat/${id}/cancel`, { method: 'POST' }),
  );
  if (result.skill_key !== key || result.id !== id) throw Error('invalid_response');
  return result;
}
export function resolveSkillLink(
  from: string,
  href: string,
  files: SkillFile[],
): SkillFile | undefined {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/|\\)/i.test(href)) return;
  let clean;
  try {
    clean = decodeURIComponent(href.split(/[?#]/)[0]);
  } catch {
    return;
  }
  if (clean.includes('\\') || clean.includes('\0')) return;
  const parts = from.split('/').slice(0, -1);
  for (const p of clean.split('/')) {
    if (!p || p === '.') continue;
    if (p === '..') {
      if (!parts.length) return;
      parts.pop();
    } else parts.push(p);
  }
  return files.find((f) => f.path === (clean ? parts.join('/') : from));
}
export function skillDifference(before: string, after: string) {
  let start = 0,
    end = 0;
  while (start < Math.min(before.length, after.length) && before[start] === after[start]) start++;
  while (
    end < Math.min(before.length, after.length) - start &&
    before.at(-end - 1) === after.at(-end - 1)
  )
    end++;
  return {
    removed: before.slice(start, end ? -end : undefined),
    added: after.slice(start, end ? -end : undefined),
  };
}
