import { parseCallMetadata } from './aiConfiguration';
import { apiErrorMessage, apiRequest } from './api/http';
import { codeErrors } from './codeAnalysisApi';
import { connectionErrors } from './githubApi';
import { generationDesign, generationKinds } from './generationPage';
import { parseCaseList, DESIGN_FIELDS } from './caseApi';
import type { GenerationPreviewItem } from './generationPage';
import type {
  GenerationRecord,
  GenerationHandling,
  GenerationMaterial,
  GenerationSuggestion,
  GenerationDecision,
  GenerationBatch,
  GenerationSummary,
} from './generationPage';

function object(v: unknown): Record<string, unknown> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw Error('generation_response_invalid');
  return v as Record<string, unknown>;
}
function text(v: unknown): string {
  if (typeof v !== 'string' || v.includes('\0')) throw Error('generation_response_invalid');
  return v;
}
function num(v: unknown, zero = false): number {
  if (typeof v !== 'number' || !Number.isSafeInteger(v) || v < (zero ? 0 : 1))
    throw Error('generation_response_invalid');
  return v;
}
function bool(v: unknown): boolean {
  if (typeof v !== 'boolean') throw Error('generation_response_invalid');
  return v;
}
function nativeId(v: unknown): string | undefined {
  if (v === undefined) return undefined;
  const value = text(v);
  if (!/^[0-9a-f]{64}$/.test(value)) throw Error('generation_response_invalid');
  return value;
}
function list<T>(v: unknown, parse: (v: unknown) => T): T[] {
  if (!Array.isArray(v) || v.length > 20000) throw Error('generation_response_invalid');
  return v.map(parse);
}
function progressTime(v: unknown): string | null {
  if (v === undefined || v === null) return null;
  const value = text(v);
  if (!Number.isFinite(Date.parse(value))) throw Error('generation_response_invalid');
  return value;
}
function timings(v: unknown): GenerationRecord['timings'] {
  if (v === undefined) return [];
  return list(v, (value) => {
    const t = object(value);
    return { startedAt: progressTime(t.startedAt), finishedAt: progressTime(t.finishedAt) };
  });
}
function diagnostics(v: unknown): Record<string, string | number> {
  if (v === undefined) return {};
  const result: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(object(v))) {
    if (
      [
        'elapsed_seconds',
        'received_bytes',
        'output_characters',
        'heartbeats',
        'http_status',
        'upstream_http_status',
        'reported_timeout_seconds',
        'first_byte_seconds',
        'headers_seconds',
        'last_activity_seconds',
        'cli_event_count',
      ].includes(key)
    ) {
      if (typeof value !== 'number' || !Number.isFinite(value) || value < 0)
        throw Error('generation_response_invalid');
      result[key] = value;
    } else if (
      [
        'phase',
        'request_id',
        'response_id',
        'error_category',
        'termination',
        'upstream_code',
        'upstream_type',
        'incomplete_reason',
        'outcome',
        'call_mode',
      ].includes(key)
    ) {
      result[key] = text(value);
    }
  }
  return result;
}
export function parseGenerationRecord(v: unknown, projectId: number): GenerationRecord {
  const o = object(v);
  if (
    o.projectId !== projectId ||
    o.origin !== 'SERVER' ||
    !['INITIAL', 'UPDATE'].includes(String(o.mode))
  )
    throw Error('generation_response_invalid');
  const id = text(o.id);
  if (!/^[1-9]\d*$/.test(id)) throw Error('generation_response_invalid');
  const suggestions = list(o.suggestions, (v): GenerationSuggestion => {
    const s = object(v),
      kind = text(s.kind);
    if (!Object.hasOwn(generationKinds, kind)) throw Error('generation_response_invalid');
    return {
      key: text(s.key),
      nativeResultId: nativeId(s.nativeResultId),
      kind: kind as GenerationSuggestion['kind'],
      function: text(s.function),
      functionRef: text(s.functionRef),
      design: generationDesign(s.design),
      before: s.before ? generationDesign(s.before) : undefined,
      generated: s.generated ? generationDesign(s.generated) : undefined,
      caseId: s.caseId === null ? null : num(s.caseId),
      baseVersion: s.baseVersion === null ? null : num(s.baseVersion),
      reason: text(s.reason),
      blocked: bool(s.blocked),
      evidence: list(s.evidence, (v) => {
        const e = object(v);
        return {
          source: text(e.source),
          segment: text(e.segment),
          side: text(e.side),
          quote: text(e.quote),
          verifiedQuote: e.verifiedQuote === undefined ? undefined : bool(e.verifiedQuote),
          quoteWarning: e.quoteWarning === undefined ? undefined : text(e.quoteWarning),
        };
      }),
    };
  });
  if (new Set(suggestions.map((s) => s.key)).size !== suggestions.length)
    throw Error('generation_response_invalid');
  const handling: Record<string, GenerationHandling[]> = {};
  for (const [key, values] of Object.entries(object(o.handling))) {
    if (['__proto__', 'constructor', 'prototype'].includes(key))
      throw Error('generation_response_invalid');
    handling[key] = list(values, (v): GenerationHandling => {
      const h = object(v),
        status = text(h.status);
      if (!['待审阅', '已忽略', '需人工确认', '已应用', '已复用'].includes(status))
        throw Error('generation_response_invalid');
      let reviewedTarget: GenerationHandling['reviewedTarget'];
      if (h.reviewedTarget) {
        const t = object(h.reviewedTarget);
        reviewedTarget = {
          id: num(t.id),
          version: num(t.version),
          design: generationDesign(t.design),
        };
      }
      return {
        status: status as GenerationHandling['status'],
        draft: generationDesign(h.draft),
        note: text(h.note),
        actor: text(h.actor),
        time: text(h.time),
        revision: num(h.revision),
        evidenceChecked: bool(h.evidenceChecked),
        resolved: bool(h.resolved),
        reviewedTarget,
        categoryId: h.categoryId === undefined ? undefined : num(h.categoryId, true),
        editedFields:
          h.editedFields === undefined
            ? undefined
            : list(h.editedFields, (v) => {
                const f = text(v);
                if (!DESIGN_FIELDS.includes(f as keyof import('./caseApi').Design))
                  throw Error('generation_response_invalid');
                return f as keyof import('./caseApi').Design;
              }),
      };
    });
  }
  const material = (v: unknown): GenerationMaterial => {
    const m = object(v);
    return {
      sourceId: text(m.sourceId),
      documentId:
        m.documentId === undefined || m.documentId === null ? undefined : num(m.documentId),
      name: text(m.name),
      purpose: text(m.purpose),
      kind: text(m.kind),
      version: text(m.version),
      versionName: text(m.versionName),
      side: text(m.side),
      before: text(m.before),
      update: text(m.update),
      paths: list(m.paths, text),
      readState: text(m.readState),
      segments: list(m.segments, (v) => {
        const s = object(v);
        return { id: text(s.id), location: text(s.location), text: text(s.text) };
      }),
    };
  };
  const failure = (v: unknown) => {
    const f = object(v);
    if (f.categoryMode !== undefined && !['KEEP', 'SET', 'CLEAR'].includes(String(f.categoryMode)))
      throw Error('generation_response_invalid');
    return {
      key: text(f.key),
      caseId: f.caseId === null ? null : num(f.caseId),
      version: f.version === null ? null : num(f.version),
      reason: text(f.reason),
      time: text(f.time),
      categoryId:
        f.categoryId === undefined || f.categoryId === null ? null : num(f.categoryId, true),
      categoryMode: f.categoryMode as 'KEEP' | 'SET' | 'CLEAR' | undefined,
    };
  };
  return {
    id,
    nativeRounds:
      o.nativeRounds === undefined
        ? []
        : list(o.nativeRounds, (value) => {
            const r = object(value),
              rid = nativeId(r.id),
              stamp = text(r.timestamp);
            if (!rid || !Number.isFinite(Date.parse(stamp)))
              throw Error('generation_response_invalid');
            return {
              id: rid,
              batchId: num(r.batchId),
              batchRef: text(r.batchRef),
              timestamp: stamp,
              caseCount: num(r.caseCount, true),
              status: text(r.status),
            };
          }),
    projectId,
    ownerId: num(o.ownerId),
    title: text(o.title),
    createdAt: text(o.createdAt),
    timings: timings(o.timings),
    mode: o.mode as GenerationRecord['mode'],
    origin: 'SERVER',
    status: text(o.status),
    serverRevision: num(o.serverRevision),
    canCancel: bool(o.canCancel),
    cancelled: bool(o.cancelled),
    scope: text(o.scope),
    focus: text(o.focus),
    materials: list(o.materials, material),
    cases: [],
    caseScope: text(o.caseScope),
    libraryRevision: o.libraryRevision === null ? null : num(o.libraryRevision, true),
    baselineId: text(o.baselineId),
    suggestions,
    questions: list(o.questions, (v) => {
      const q = object(v);
      return {
        key: text(q.key),
        nativeResultId: nativeId(q.nativeResultId),
        function: text(q.function),
        functionRef: text(q.functionRef),
        title: text(q.title),
        text: text(q.text),
        evidence: text(q.evidence),
      };
    }),
    candidateIssues:
      o.candidateIssues === undefined
        ? []
        : list(o.candidateIssues, (value) => {
            const issue = object(value);
            const kind = text(issue.kind),
              status = text(issue.status);
            if (
              !['case', 'note', 'response'].includes(kind) ||
              !['PENDING', 'RESOLVED', 'IGNORED'].includes(status)
            )
              throw Error('generation_response_invalid');
            return {
              key: text(issue.key),
              nativeResultId: nativeId(issue.nativeResultId),
              issueId: text(issue.issueId),
              batchId: num(issue.batchId),
              kind: kind as 'case' | 'note' | 'response',
              ordinal: num(issue.ordinal, true),
              status: status as 'PENDING' | 'RESOLVED' | 'IGNORED',
              reason: text(issue.reason),
              rawJson: text(issue.rawJson),
              correctedJson: text(issue.correctedJson),
              note: text(issue.note),
              canEdit: bool(issue.canEdit),
              duplicates: list(issue.duplicates, (value) => {
                const duplicate = object(value);
                return { path: text(duplicate.path), values: list(duplicate.values, text) };
              }),
            };
          }),
    handling,
    decisions: list(o.decisions, (v): GenerationDecision => {
      const d = object(v);
      return {
        key: text(d.key),
        questionKey: text(d.questionKey),
        function: text(d.function),
        conclusion: text(d.conclusion),
        basis: text(d.basis),
        affected: text(d.affected),
        actor: text(d.actor),
        time: text(d.time),
        version: num(d.version),
      };
    }),
    failures: list(o.failures, failure),
    failureHistory: list(o.failureHistory, failure),
    chatDrafts: {},
    batches: list(o.batches, (v): GenerationBatch => {
      const b = object(v);
      return {
        terminalAvailable: b.terminalAvailable === undefined ? false : bool(b.terminalAvailable),
        nativeResultId: nativeId(b.nativeResultId),
        id: num(b.id),
        key: text(b.key),
        function: text(b.function),
        status: text(b.status),
        attempts: num(b.attempts, true),
        reason: text(b.reason),
        inputBytes: num(b.inputBytes, true),
        candidateAvailable: bool(b.candidateAvailable),
        startedAt: progressTime(b.startedAt),
        progressAt: progressTime(b.progressAt),
        diagnostics: diagnostics(b.diagnostics),
      };
    }),
    limitations: list(o.limitations, text),
    outcome: text(o.outcome),
    inputText: text(o.inputText),
    reportText: text(o.reportText),
    rawReports: list(o.rawReports, object),
    applications: list(o.applications, (v) => {
      const a = object(v);
      return {
        id: num(a.id),
        requestId: a.requestId === undefined ? undefined : text(a.requestId),
        status: text(a.status),
        items: list(a.items, object),
        error: text(a.error),
      };
    }),
    ai_config: o.ai_config,
    aiPreview:
      o.aiPreview === null
        ? null
        : (() => {
            const a = object(o.aiPreview);
            return {
              ...parseCallMetadata(a),
              name: text(a.name),
              model: text(a.model),
              version: num(a.version),
            };
          })(),
    planNote: text(o.planNote),
    skillVersion: text(o.skillVersion),
  };
}
export const generationBase = (projectId: number) => `/api/projects/${projectId}/case-generation`;
export async function generationList(projectId: number, signal: AbortSignal, page = 1) {
  const o = object(
    await apiRequest<unknown>(`${generationBase(projectId)}?page=${page}`, { signal }),
  );
  return {
    items: list(o.items, (v) => parseGenerationRecord(v, projectId)),
    hasMore: bool(o.has_more),
  };
}
export async function generationSummaries(
  projectId: number,
  signal: AbortSignal,
  page = 1,
  runId?: string,
) {
  const o = object(
    await apiRequest<unknown>(
      `${generationBase(projectId)}?page=${page}&summary=true${runId ? `&run_id=${encodeURIComponent(runId)}` : ''}`,
      { signal },
    ),
  );
  return {
    items: list(o.items, (v): GenerationSummary => {
      const r = object(v),
        id = text(r.id),
        mode = text(r.mode),
        status = text(r.status),
        refreshKey = text(r.refreshKey),
        createdAt = text(r.createdAt);
      if (
        num(r.projectId) !== projectId ||
        !/^[1-9]\d*$/.test(id) ||
        !['INITIAL', 'UPDATE'].includes(mode) ||
        !['PREPARED', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED'].includes(status) ||
        !/^[a-f0-9]{64}$/.test(refreshKey) ||
        !Number.isFinite(Date.parse(createdAt))
      )
        throw Error('generation_response_invalid');
      return {
        id,
        projectId,
        ownerId: r.ownerId === undefined ? undefined : num(r.ownerId),
        title: text(r.title),
        createdAt,
        timings: timings(r.timings),
        mode: mode as GenerationSummary['mode'],
        status,
        serverRevision: num(r.serverRevision),
        hasMaterials: bool(r.hasMaterials),
        active: bool(r.active),
        refreshKey,
      };
    }),
    hasMore: bool(o.has_more),
  };
}
export async function generationDetail(projectId: number, runId: string, signal?: AbortSignal) {
  const row = parseGenerationRecord(
    await apiRequest<unknown>(`${generationBase(projectId)}/${runId}`, { signal }),
    projectId,
  );
  if (row.id !== runId) throw Error('generation_response_invalid');
  return row;
}
export async function generationAction(
  projectId: number,
  path: string,
  body?: unknown,
  signal?: AbortSignal,
) {
  let response: unknown;
  try {
    response = await apiRequest<unknown>(`${generationBase(projectId)}${path}`, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      timeoutMs:
        path === '/prepare' || /^\/[1-9]\d*\/applications$/.test(path) ? 600000 : undefined,
    });
  } catch (error) {
    if (path === '/prepare' && error instanceof Error && error.name === 'TimeoutError')
      throw Error('generation_prepare_timeout');
    throw error;
  }
  return parseGenerationRecord(response, projectId);
}
const generationErrors: Record<string, string> = {
  generation_native_results_unavailable: '原生CLI历史暂不可读取，请稍后重试；没有调用AI。',
  generation_native_result_not_found: '没有找到这轮生成JSON，请重新读取可选轮次。',
  generation_native_round_retry_forbidden:
    '候选轮次不单独调用AI；请在原CLI对话继续生成，或免费修正候选。',
  generation_native_result_migration_requires_review:
    '旧候选已有人工处理记录，需要保留并核对迁移，未覆盖已有结果。',
  generation_native_result_not_ready: '首次生成仍在处理中，完成后再保存对话结果。',
  ...connectionErrors,
  ...codeErrors,
  generation_prepare_timeout:
    '读取资料等待超时，后台可能仍在准备。请先刷新记录核对，避免重复新建；尚未自动调用AI。',
  change_source_storage_unavailable: '固定GitHub正文缓存暂不可用，请检查后端存储后重试。',
  generation_evidence_quote_mismatch:
    'AI摘录与固定资料原文不一致，原始候选已保存；请下载核对，不能作为已验证依据。',
  generation_evidence_source_invalid: 'AI摘录引用了不属于本条用例的资料，请下载原始候选核对。',
  generation_response_invalid: '生成响应身份或结构无效，请刷新核对。',
  generation_contract_invalid: '候选契约或引用校验失败，原始响应保留供核对。',
  generation_business_basis_required: '候选缺少当前业务依据，不能保存为有效报告。',
  generation_changed: '记录或草稿已变化，请刷新重新核对。',
  generation_source_changed: '来源授权或原件内容已变化，不能继续。',
  generation_batch_context_too_large:
    '单批公共规则/用例上下文过大，请缩小功能或用例范围后重新准备。',
  generation_candidate_unavailable: '本次没有完整候选响应。',
  generation_candidate_fix_invalid:
    '修正后的候选仍未通过校验，请核对必需字段、来源引用和重复字段。',
  generation_candidate_review_unavailable: '候选处理记录暂不可读取，请稍后重试。',
  generation_candidate_issue_not_found: '此问题候选已变化，请刷新查看。',
  generation_candidate_already_resolved: '此候选已经修正，请刷新查看。',
  generation_candidate_prior_result_changed: '修正影响了已保存建议，未保存此次改动。',
  generation_owner_only: '该操作仅限发起人。',
  generation_cli_mode_required: '请先在 AI 服务设置中选择本人 Codex CLI 配置，再发送追问。',
  generation_terminal_closed: 'CLI 进程已结束，可继续同一会话；重新生成请使用人工重试。',
  generation_terminal_permission_required: '当前账号未启用 CLI 试用，请联系平台管理员。',
  generation_terminal_failed: '原生 CLI 进程启动或执行失败，请核对终端记录。',
  generation_terminal_not_started:
    '请选用 CLI 方式点击开始生成；终端只关联实际生成任务，不再另建独立会话。',
  generation_terminal_bound_to_batch:
    '此终端固定关联生成任务，请继续同一会话；重新生成请使用明确的人工重试。',
  generation_terminal_response_incomplete:
    'CLI 未完成本次生成或未交付完整结果，未作为有效报告保存。',
  generation_terminal_turn_failed: 'CLI 本轮分析失败，原始错误已保留，请查看终端记录。',
  generation_terminal_turn_interrupted: 'CLI 本轮分析已中断，未作为完整报告保存。',
  generation_terminal_command_blocked:
    '本机命令已被后端拒绝，未执行；当前 CLI 已退出，可继续会话恢复正常对话。',
  generation_terminal_windows_required: '原生终端需要后端运行在 Windows。',
  generation_cli_log_unavailable: 'CLI 执行记录暂不可读取，请重新读取或核对后端私有存储。',
  generation_chat_busy: '本记录的上一轮对话尚未结束，请等待或取消后继续。',
  generation_bindings_required: '请关联每份实际资料的项目原件和固定版本。',
  generation_binding_mismatch: '文件正文与绑定原件不匹配。',
  generation_decision_binding_required: '已确认结论必须绑定本项目实际人工确认记录。',
  generation_request_conflict: '同一请求身份已有不同内容，请核对。',
  generation_category_not_applicable: '复用、忽略或停用项保留原分类，请重新核对。',
  generation_application_busy: '本记录已有入库任务，完成后再提交。',
  generation_submission_interrupted: '本次入库未完成，请刷新核对已保存的结果，再提交未完成项。',
};
export function generationFailure(code: string) {
  return code ? generationErrors[code] || '生成未完成，请核对固定输入及原始候选。' : '';
}
export function generationError(e: unknown, onSessionEnd: () => void) {
  return apiErrorMessage(e, onSessionEnd, generationErrors);
}
export async function generationApplyPreview(
  projectId: number,
  runId: string,
  keys: string[],
  signal: AbortSignal,
) {
  const o = object(
    await apiRequest<unknown>(`${generationBase(projectId)}/${runId}/apply-preview`, {
      method: 'POST',
      body: JSON.stringify({ keys }),
      signal,
    }),
  );
  const caseRows = (rows: unknown) =>
    parseCaseList({
      revision: 0,
      next_number: 1,
      categories: [],
      items: rows,
      total: Array.isArray(rows) ? rows.length : 0,
      page: 1,
      page_size: 100,
    }).items;
  const items = list(o.items, (v): GenerationPreviewItem => {
    const i = object(v),
      kind = text(i.kind);
    if (!Object.hasOwn(generationKinds, kind)) throw Error('generation_response_invalid');
    return {
      key: text(i.key),
      kind: kind as GenerationPreviewItem['kind'],
      design: generationDesign(i.design),
      revision: num(i.revision, true),
      problem: text(i.problem),
      matches: caseRows(i.matches),
      target: i.target ? caseRows([i.target])[0] : undefined,
      categoryId:
        i.categoryId === undefined || i.categoryId === null ? null : num(i.categoryId, true),
    };
  });
  if (
    items.length !== keys.length ||
    new Set(items.map((i) => i.key)).size !== keys.length ||
    items.some((i) => !keys.includes(i.key))
  )
    throw Error('generation_response_invalid');
  return { items, keys: list(o.keys, text), revision: num(o.revision, true) };
}
