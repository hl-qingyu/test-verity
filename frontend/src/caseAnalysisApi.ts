import { deletionErrors } from './analysisDeletionApi';
import { codeErrors } from './codeAnalysisApi';
import { apiRequest, apiErrorMessage } from './api/http';
import { CASE_COLUMNS, parseCaseList } from './caseApi';
import type { CaseRow, Design } from './caseApi';

export const reviewKinds = {
  MISMATCH: '不符合需求',
  MISSING: '缺失场景',
  QUALITY: '设计不完善',
  SETUP: '执行准备待补',
  QUESTION: '业务待澄清',
};
export const reviewStates = ['待确认', '已确认待处理', '已解决', '不适用'];
const reviewFieldLabels: Record<string, string> = {
  ...Object.fromEntries(CASE_COLUMNS),
  data_requirements: '测试数据要求',
  cleanup: '清理要求',
};
export const reviewFieldName = (field: string) =>
  Object.hasOwn(reviewFieldLabels, field) ? reviewFieldLabels[field] : '相关内容';
// Translate platform field labels for readers; stored reports and source quotes stay intact.
export function reviewText(text: string) {
  return text.replace(
    /(?<![A-Za-z0-9_/.:\\-])\b(module|structure|case_type|priority|description|title|preconditions|steps|expected|remark|data_requirements|cleanup)\b(?![A-Za-z0-9_]|[./:\\-][A-Za-z0-9_])/gi,
    (field) => reviewFieldName(field.toLowerCase()),
  );
}
export const taskStates: Record<string, string> = {
  PREPARED: '待开始',
  QUEUED: '排队中',
  RUNNING: '分析中',
  COMPLETED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
};
export type ReviewFinding = {
  key: string;
  kind: keyof typeof reviewKinds;
  title: string;
  severity: string;
  reason: string;
  description: string;
  impact: string;
  suggestion: string;
  case_ids: number[];
  fields: string[];
  evidence: { source: string; quote: string; observation?: string }[];
};
export type ReviewReport = {
  findings: ReviewFinding[];
  notes: ReviewFinding[];
  checked_case_ids: number[];
  complete: boolean;
};
export type ReviewMaterial = {
  source_id: string;
  name: string;
  version: string;
  read_note: string;
  segments: { text: string; location: string }[];
};
export type ReviewHandling = {
  state?: string;
  comment?: string;
  draft?: Design;
  draft_revision?: number;
  category_id?: number | null;
  target?: CaseRow;
  applied?: { case_id: number; version: number };
  history?: { state: string; comment: string; time: string; actor_id: number }[];
};
export type ReviewSummary = {
  id: number;
  project_id: number;
  title: string;
  mode: 'COMPARE' | 'QUALITY';
  actor_id: number;
  parent_id: number | null;
  status: string;
  outcome: string | null;
  revision: number;
  error_code: string;
  created_at: string;
  updated_at: string;
};
export type ReviewRecord = ReviewSummary & {
  terminal_available?: boolean;
  input: {
    type: string;
    request_id: string;
    materials: ReviewMaterial[];
    cases: CaseRow[];
    focus: string;
    scope: unknown;
  };
  report: ReviewReport | Record<string, never>;
  handling: Record<string, ReviewHandling>;
  manual: ReviewFinding[];
  personal_ai: {
    name: string;
    model: string;
    version: number;
    call_mode?: 'RESPONSES_API' | 'CODEX_EXEC';
    preference_version?: number;
  } | null;
  notice: string;
  ai_config: unknown;
  attempts: unknown[];
  chat: {
    id: number;
    actor_id: number;
    function_key: string;
    finding_key: string;
    question: string;
    answer: string;
    status: string;
    error_code: string;
  }[];
  applications: {
    id: number;
    status: string;
    error_code: string;
    items: {
      key: string;
      status: string;
      error_code?: string;
      mapping?: { case_id: number; version: number; kind: string };
    }[];
  }[];
};
export type ReviewPreview = {
  key: string;
  draft_revision: number;
  design: Design;
  category_id: number | null;
  target: CaseRow | null;
  matches: CaseRow[];
};
function obj(v: unknown): Record<string, unknown> {
  if (!v || typeof v !== 'object' || Array.isArray(v))
    throw Error('case_analysis_response_invalid');
  return v as Record<string, unknown>;
}
function arr(v: unknown): unknown[] {
  if (!Array.isArray(v) || v.length > 20000) throw Error('case_analysis_response_invalid');
  return v;
}
export function parseReviewSummary(v: unknown): ReviewSummary {
  const o = obj(v);
  for (const k of ['id', 'project_id', 'actor_id', 'revision'])
    if (!Number.isSafeInteger(o[k]) || Number(o[k]) < 1)
      throw Error('case_analysis_response_invalid');
  for (const k of ['title', 'status', 'created_at', 'updated_at', 'error_code'])
    if (typeof o[k] !== 'string') throw Error('case_analysis_response_invalid');
  if (!['COMPARE', 'QUALITY'].includes(String(o.mode)) || !taskStates[String(o.status)])
    throw Error('case_analysis_response_invalid');
  return o as ReviewSummary;
}
export function parseReviewFinding(v: unknown): ReviewFinding {
  const o = obj(v);
  if (!reviewKinds[o.kind as keyof typeof reviewKinds])
    throw Error('case_analysis_response_invalid');
  for (const k of ['key', 'title', 'severity', 'reason', 'description', 'impact', 'suggestion'])
    if (typeof o[k] !== 'string') throw Error('case_analysis_response_invalid');
  arr(o.case_ids).forEach((id) => {
    if (!Number.isSafeInteger(id) || Number(id) < 1) throw Error('case_analysis_response_invalid');
  });
  arr(o.fields).forEach((s) => {
    if (typeof s !== 'string') throw Error('case_analysis_response_invalid');
  });
  arr(o.evidence).forEach((v) => {
    const e = obj(v);
    if (typeof e.source !== 'string' || typeof e.quote !== 'string')
      throw Error('case_analysis_response_invalid');
  });
  return o as ReviewFinding;
}
export function parseReview(v: unknown): ReviewRecord {
  const o = obj(v);
  parseReviewSummary(o);
  if (o.terminal_available !== undefined && typeof o.terminal_available !== 'boolean')
    throw Error('case_analysis_response_invalid');
  const input = obj(o.input);
  if (input.type !== 'CASE_REVIEW') throw Error('case_analysis_response_invalid');
  const cases = parseCaseList({
    revision: 1,
    next_number: 1,
    categories: [],
    items: input.cases,
    total: arr(input.cases).length,
    page: 1,
    page_size: 100,
  }).items;
  input.cases = cases;
  arr(input.materials).forEach((v) => {
    const m = obj(v);
    for (const k of ['source_id', 'name', 'version', 'read_note'])
      if (typeof m[k] !== 'string') throw Error('case_analysis_response_invalid');
    arr(m.segments).forEach((v) => {
      const s = obj(v);
      if (typeof s.text !== 'string' || typeof s.location !== 'string')
        throw Error('case_analysis_response_invalid');
    });
  });
  const report = obj(o.report);
  if (o.status === 'COMPLETED') {
    arr(report.findings).forEach(parseReviewFinding);
    arr(report.notes).forEach(parseReviewFinding);
    arr(report.checked_case_ids);
    if (typeof report.complete !== 'boolean') throw Error('case_analysis_response_invalid');
  }
  obj(o.handling);
  arr(o.chat);
  arr(o.applications);
  arr(o.attempts);
  if (typeof o.notice !== 'string') throw Error('case_analysis_response_invalid');
  return o as ReviewRecord;
}
export const reviewBase = (project: number) => `/api/projects/${project}/case-analysis`;
export async function reviewRequest<T>(
  project: number,
  path: string,
  parse: (v: unknown) => T,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const value = await apiRequest<unknown>(reviewBase(project) + path, {
    method: body === undefined ? 'GET' : 'POST',
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal,
  });
  const parsed = parse(value);
  const result = obj(parsed);
  if (result.project_id !== undefined && result.project_id !== project)
    throw Error('case_analysis_response_invalid');
  if (Array.isArray(result.items))
    for (const item of result.items) {
      const r = obj(item);
      if (r.project_id !== undefined && r.project_id !== project)
        throw Error('case_analysis_response_invalid');
    }
  return parsed;
}
export const allReviewFindings = (r: ReviewRecord) => [
  ...('findings' in r.report ? r.report.findings : []),
  ...('notes' in r.report ? r.report.notes : []),
  ...(r.manual || []),
];

export const reviewErrors: Record<string, string> = {
  ...deletionErrors,
  ...codeErrors,
  case_analysis_cases_required: '请选至少一条用例；对照需求的0条范围需明确确认。',
  case_analysis_materials_required: '对照需求至少选择一份实际资料。',
  case_analysis_target_changed: '用例范围或设计版本已变化，请重新读取并核对。',
  case_analysis_revision_conflict: '记录或草案已变化，请重新打开核对；当前输入保留。',
  case_analysis_invalid: '字段、范围或确认不完整，请核对当前表单。',
  case_analysis_request_conflict: '相同请求ID的范围不同，请重新准备。',
  case_analysis_input_too_large: '完整输入超过平台限制，请缩小范围。',
  case_analysis_quote_invalid: '摘录不在固定原文中，请核对来源。',
  case_analysis_evidence_required: '需求偏差或缺失场景需要真实原文依据。',
  case_analysis_fixed_input_required: '输入与本项目已准备的原件不匹配。',
  case_analysis_import_conflict: '本记录已有不同原报告，不能覆盖。',
  case_analysis_already_applied: '本条已成功应用，不重复写入。',
  case_analysis_duplicate_decision_required: '请核对重复用例，选择有效复用目标或说明仍新增的理由。',
  case_analysis_application_busy: '本记录已有审核申请处理中，请等待并核对结果。',
  case_analysis_chat_busy: '本对话已有请求处理中。',
  case_analysis_report_invalid: '模型结果结构不符合契约，原始响应已保留。',
  case_analysis_worker_interrupted: '后台执行中断，固定输入保留，请人工重试。',
  case_analysis_response_invalid: '服务响应不完整，未将其作为成功结果。',
  case_analysis_material_unreadable: '所选资料无法实际读取，请调整资料范围。',
};
export const reviewError = (e: unknown, onSessionEnd: () => void) =>
  apiErrorMessage(e, onSessionEnd, reviewErrors);

export function reviewDiagnostics(record: ReviewRecord) {
  const a = record.attempts.at(-1);
  if (!a || typeof a !== 'object') return null;
  const d = (a as Record<string, unknown>).diagnostics;
  if (!d || typeof d !== 'object') return null;
  const value = d as Record<string, unknown>;
  return {
    phase: typeof value.phase === 'string' ? value.phase : '',
    elapsed: typeof value.elapsed_seconds === 'number' ? value.elapsed_seconds : null,
    bytes: typeof value.received_bytes === 'number' ? value.received_bytes : null,
    characters: typeof value.output_characters === 'number' ? value.output_characters : null,
  };
}
