import { parseCallMetadata } from './aiConfiguration';
import { deletionErrors } from './analysisDeletionApi';
import { aiErrors } from './aiErrors';
import { apiErrorMessage, apiRequest } from './api/http';

export const codeTargets = {
  BUG: '代码 Bug',
  REQUIREMENT_DEVIATION: '需求符合性',
  FRONTEND_BACKEND_MISMATCH: '前后端一致性',
} as const;
export type CodeTarget = keyof typeof codeTargets;
export const codeKinds = {
  BACKEND: '后端',
  WEB: '前端',
  FLUTTER: '移动端',
  PROTOTYPE: '原型',
  OTHER: '其他',
} as const;
export type CodeKind = keyof typeof codeKinds;
export const codeStates = {
  QUEUED: '排队中',
  RUNNING: '分析中',
  COMPLETED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
} as const;
export const codeOutcomes = {
  COMPLETE: '分析完成',
  PARTIAL: '部分完成',
  BLOCKED: '依据不足',
} as const;
export const codeLevels = { HIGH: '高', MEDIUM: '中', LOW: '低', UNASSESSED: '待评估' } as const;
export const codeEvidenceStates = {
  STATIC_SUPPORTED: '静态证据充分',
  INSUFFICIENT: '证据不足',
} as const;
export const codeHandlingStates = {
  PENDING: '待处理',
  CONFIRMED: '已确认',
  RESOLVED: '已处理',
  FALSE_POSITIVE: '误报',
  NEEDS_EVIDENCE: '需补充证据',
} as const;
export type CodeHandlingState = keyof typeof codeHandlingStates;
export const CODE_FILE_LIMIT = 16 * 1024 * 1024;

function invalid(): never {
  throw new Error('code_response_invalid');
}
function obj(v: unknown): Record<string, unknown> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return invalid();
  return v as Record<string, unknown>;
}
function str(v: unknown): string {
  return typeof v === 'string' ? v : invalid();
}
function num(v: unknown): number {
  return typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 ? v : invalid();
}
function bool(v: unknown): boolean {
  return typeof v === 'boolean' ? v : invalid();
}
function arr<T>(v: unknown, parse: (item: unknown) => T): T[] {
  return Array.isArray(v) ? v.map(parse) : invalid();
}
function choice<T extends string>(v: unknown, values: Record<T, unknown>): T {
  const s = str(v);
  if (!Object.hasOwn(values, s)) return invalid();
  return s as T;
}
const strings = (v: unknown) => arr(v, str);
const target = (v: unknown) => choice(v, codeTargets);
const mode = (v: unknown) => choice(v, { GITHUB: '', LOCAL: '' });
const nullableNum = (v: unknown) => (v === null || v === undefined ? null : num(v));

export function parseCodeInput(value: unknown) {
  const v = obj(value);
  if (v.contract_version !== 2 || v.analysis_type !== 'CODE_REVIEW') return invalid();
  return {
    contract_version: 2 as const,
    analysis_type: 'CODE_REVIEW' as const,
    request_id: str(v.request_id),
    source_mode: mode(v.source_mode),
    targets: arr(v.targets, target),
    focus: str(v.focus),
    input_limitations: strings(v.input_limitations),
    sources: arr(v.sources, (item) => {
      const s = obj(item);
      return {
        source_id: str(s.source_id),
        source_kind: mode(s.source_kind),
        repository_kind: choice(s.repository_kind, codeKinds),
        name: str(s.name),
        snapshot_ref: str(s.snapshot_ref),
        commit: str(s.commit),
        files: arr(s.files, (item) => {
          const f = obj(item);
          return {
            file_id: str(f.file_id),
            path: str(f.path),
            read_state: str(f.read_state),
            read_note: str(f.read_note),
            segments: arr(f.segments, (item) => {
              const p = obj(item);
              return {
                segment_id: str(p.segment_id),
                start_line: num(p.start_line),
                text: str(p.text),
              };
            }),
          };
        }),
      };
    }),
    materials: arr(v.materials, (item) => {
      const m = obj(item);
      return {
        source_id: str(m.source_id),
        name: str(m.name),
        origin: str(m.origin),
        snapshot_ref: str(m.snapshot_ref),
        read_state: str(m.read_state),
        read_note: str(m.read_note),
        segments: arr(m.segments, (item) => {
          const p = obj(item);
          return {
            segment_id: str(p.segment_id),
            location: str(p.location),
            text: str(p.text),
            image_ref: str(p.image_ref),
          };
        }),
      };
    }),
  };
}
export type CodeInput = ReturnType<typeof parseCodeInput>;

function side(value: unknown) {
  const v = obj(value);
  return { statement: str(v.statement), evidence_refs: strings(v.evidence_refs) };
}
function parseFinding(value: unknown) {
  const v = obj(value);
  return {
    key: str(v.key),
    target_refs: arr(v.target_refs, target),
    title: str(v.title),
    category: str(v.category),
    severity: choice(v.severity, codeLevels),
    severity_reason: str(v.severity_reason),
    evidence_state: choice(v.evidence_state, codeEvidenceStates),
    trigger: str(v.trigger),
    actual: str(v.actual),
    impact: str(v.impact),
    evidence_refs: strings(v.evidence_refs),
    chain_refs: strings(v.chain_refs),
    fix_suggestion: str(v.fix_suggestion),
    verification_suggestion: str(v.verification_suggestion),
    missing_evidence: arr(v.missing_evidence, (item) => {
      const m = obj(item);
      return { needed: str(m.needed), reason: str(m.reason), effect: str(m.effect) };
    }),
    target_views: arr(v.target_views, (item) => {
      const t = obj(item);
      return {
        target: target(t.target),
        evidence_state: choice(t.evidence_state, codeEvidenceStates),
        expected: str(t.expected),
        basis: str(t.basis),
        basis_refs: strings(t.basis_refs),
        explanation: str(t.explanation),
        evidence_refs: strings(t.evidence_refs),
        comparison_rows: arr(t.comparison_rows, (item) => {
          const r = obj(item);
          return { label: str(r.label), left: side(r.left), right: side(r.right) };
        }),
      };
    }),
  };
}
export type CodeFinding = ReturnType<typeof parseFinding>;
export type CodeEvidence = {
  key: string;
  kind: 'CODE' | 'MATERIAL';
  source_id: string;
  file_id?: string;
  segment_id: string;
  start_line?: number;
  end_line?: number;
  excerpt: string;
  observation: string;
};
function parseEvidence(value: unknown): CodeEvidence {
  const e = obj(value),
    kind = choice(e.kind, { CODE: '', MATERIAL: '' });
  return {
    key: str(e.key),
    kind,
    source_id: str(e.source_id),
    segment_id: str(e.segment_id),
    excerpt: str(e.excerpt),
    observation: str(e.observation),
    ...(kind === 'CODE'
      ? { file_id: str(e.file_id), start_line: num(e.start_line), end_line: num(e.end_line) }
      : {}),
  };
}
export function parseCodeReport(value: unknown) {
  const v = obj(value),
    summary = obj(v.summary);
  if (v.contract_version !== 2 || v.analysis_type !== 'CODE_REVIEW') return invalid();
  return {
    contract_version: 2 as const,
    request_id: str(v.request_id),
    outcome: choice(v.outcome, codeOutcomes),
    summary: {
      conclusion: str(summary.conclusion),
      priority_finding_keys: strings(summary.priority_finding_keys),
    },
    findings: arr(v.findings, parseFinding),
    evidence: arr(v.evidence, parseEvidence),
    target_results: arr(v.target_results, (item) => {
      const t = obj(item);
      return {
        target: target(t.target),
        status: choice(t.status, codeOutcomes),
        scope: str(t.scope),
        finding_refs: strings(t.finding_refs),
        limitation_refs: strings(t.limitation_refs),
        checks: arr(t.checks, (item) => {
          const c = obj(item);
          return {
            key: str(c.key),
            subject: str(c.subject),
            assessment: str(c.assessment),
            evidence_refs: strings(c.evidence_refs),
            finding_refs: strings(c.finding_refs),
            note: str(c.note),
          };
        }),
      };
    }),
    chains: arr(v.chains, (item) => {
      const c = obj(item);
      return {
        key: str(c.key),
        nodes: arr(c.nodes, (item) => {
          const n = obj(item);
          return {
            key: str(n.key),
            label: str(n.label),
            observation: str(n.observation),
            inputs: str(n.inputs),
            outputs: str(n.outputs),
            evidence_refs: strings(n.evidence_refs),
          };
        }),
        edges: arr(c.edges, (item) => {
          const e = obj(item);
          return {
            from: str(e.from),
            to: str(e.to),
            relation: str(e.relation),
            evidence_refs: strings(e.evidence_refs),
            note: str(e.note),
          };
        }),
      };
    }),
    limitations: arr(v.limitations, (item) => {
      const l = obj(item);
      return {
        key: str(l.key),
        detail: str(l.detail),
        effect: str(l.effect),
        target_refs: arr(l.target_refs, target),
      };
    }),
  };
}
export type CodeReport = ReturnType<typeof parseCodeReport>;
function ai(value: unknown) {
  const v = obj(value);
  return {
    ...parseCallMetadata(v),
    name: v.name === undefined ? '' : str(v.name),
    model: v.model === undefined ? '' : str(v.model),
    version: nullableNum(v.version),
    error_code: v.error_code === undefined ? '' : str(v.error_code),
  };
}
export function parseCodeRecord(value: unknown) {
  const v = obj(value);
  return {
    id: num(v.id),
    project_id: num(v.project_id),
    actor_id: v.actor_id === undefined ? undefined : num(v.actor_id),
    title: str(v.title),
    focus: str(v.focus),
    targets: arr(v.targets, target),
    status: choice(v.status, codeStates),
    error_code: str(v.error_code),
    retry_of: nullableNum(v.retry_of),
    created_at: str(v.created_at),
    updated_at: str(v.updated_at),
    revision: num(v.revision),
    origin: str(v.origin),
    ai: ai(v.ai),
    can_cancel: bool(v.can_cancel),
    can_retry: bool(v.can_retry),
    findings_count: num(v.findings_count),
    outcome: v.outcome ? choice(v.outcome, codeOutcomes) : null,
    contract_version: nullableNum(v.contract_version),
  };
}
export type CodeRecord = ReturnType<typeof parseCodeRecord>;
function parseHandling(value: unknown) {
  const v = obj(value);
  return {
    status: choice(v.status, codeHandlingStates),
    note: str(v.note),
    actor_name: str(v.actor_name),
    at: str(v.at),
    history: arr(v.history, (item) => {
      const h = obj(item);
      return {
        status: choice(h.status, codeHandlingStates),
        note: str(h.note),
        actor_name: str(h.actor_name),
        at: str(h.at),
      };
    }),
  };
}
export function parseCodeDetail(value: unknown) {
  const v = obj(value),
    report = obj(v.report),
    input = obj(v.input),
    handling = obj(v.handling);
  return {
    ...parseCodeRecord(v),
    input: input.contract_version === 2 ? parseCodeInput(input) : null,
    report: report.contract_version === 2 ? parseCodeReport(report) : null,
    handling: Object.fromEntries(
      Object.entries(handling).map(([key, value]) => [key, parseHandling(value)]),
    ),
    candidate_available: v.candidate_available === undefined ? false : bool(v.candidate_available),
    can_revalidate: v.can_revalidate === undefined ? false : bool(v.can_revalidate),
    evidence_corrections:
      v.evidence_corrections === undefined
        ? []
        : arr(v.evidence_corrections, (item) => {
            const correction = obj(item);
            return {
              evidence_key: str(correction.evidence_key),
              original_start_line: num(correction.original_start_line),
              original_end_line: num(correction.original_end_line),
              start_line: num(correction.start_line),
              end_line: num(correction.end_line),
              removed_trailing_lf: bool(correction.removed_trailing_lf),
            };
          }),
    duplicate: v.duplicate === true,
  };
}
export type CodeDetail = ReturnType<typeof parseCodeDetail>;
export function parseCodeOptions(value: unknown) {
  const v = obj(value);
  return {
    ai: ai(v.ai),
    file_limit: num(v.file_limit),
    repositories: arr(v.repositories, (item) => {
      const r = obj(item);
      return {
        id: num(r.id),
        full_name: str(r.full_name),
        kind: choice(r.kind, codeKinds),
        version: num(r.version),
        default_branch: str(r.default_branch),
      };
    }),
    connections: arr(v.connections, (item) => {
      const c = obj(item);
      return { id: num(c.id), name: str(c.name) };
    }),
    local_sources: arr(v.local_sources, (item) => {
      const l = obj(item);
      return {
        id: num(l.id),
        client_id: str(l.client_id),
        name: str(l.name),
        directory_name: str(l.directory_name),
        kind: choice(l.kind, codeKinds),
        version: num(l.version),
      };
    }),
    materials: arr(v.materials, (item) => {
      const m = obj(item);
      return {
        id: num(m.id),
        name: str(m.name),
        purpose: str(m.purpose),
        kind: str(m.kind),
        url: str(m.url ?? ''),
        commit: str(m.commit),
        files: arr(m.files, (item) => {
          const f = obj(item);
          return { path: str(f.path), sha: str(f.sha), size: num(f.size) };
        }),
        versions: arr(m.versions, (item) => {
          const r = obj(item);
          return {
            id: num(r.id),
            number: num(r.number),
            filename: str(r.filename),
            extension: str(r.extension),
          };
        }),
      };
    }),
  };
}
export type CodeOptions = ReturnType<typeof parseCodeOptions>;
export function parseCodeScope(value: unknown) {
  const v = obj(value);
  return {
    commit: str(v.commit),
    full_name: str(v.full_name),
    repository_kind: choice(v.repository_kind, codeKinds),
    source_version: num(v.source_version),
    files: arr(v.files, (item) => {
      const f = obj(item);
      return { path: str(f.path), sha: str(f.sha), size: num(f.size) };
    }),
  };
}
export function parseCodeTurn(value: unknown) {
  const v = obj(value);
  return {
    id: num(v.id),
    task_id: num(v.task_id),
    actor_id: num(v.actor_id),
    finding_key: str(v.finding_key),
    question: str(v.question),
    answer: str(v.answer),
    status: choice(v.status, codeStates),
    error_code: str(v.error_code),
    ai: ai(v.ai),
    created_at: str(v.created_at),
    can_cancel: bool(v.can_cancel),
  };
}
export type CodeTurn = ReturnType<typeof parseCodeTurn>;
export function parseCodePreview(value: unknown) {
  const v = obj(value);
  return { path: str(v.path), content: str(v.content), commit: str(v.commit) };
}

export async function codeList(path: string, signal: AbortSignal) {
  const v = obj(await apiRequest<unknown>(path, { signal }));
  return { items: arr(v.items, parseCodeRecord), has_more: bool(v.has_more) };
}
export async function codeTurns(path: string, signal: AbortSignal) {
  const v = obj(await apiRequest<unknown>(path, { signal }));
  return { items: arr(v.items, parseCodeTurn), has_more: bool(v.has_more) };
}
export async function codeRequest<T>(
  path: string,
  parser: (v: unknown) => T,
  options: RequestInit = {},
) {
  return parser(await apiRequest<unknown>(path, options));
}
export async function readCodeJSON(file: File) {
  if (file.size > CODE_FILE_LIMIT || !file.name.toLowerCase().endsWith('.json'))
    throw new Error('code_import_file_invalid');
  const text = await file.text();
  try {
    return { filename: file.name, text, data: JSON.parse(text.replace(/^\uFEFF/, '')) as unknown };
  } catch {
    throw new Error('code_json_invalid');
  }
}
export const codeErrors: Record<string, string> = {
  ...deletionErrors,
  ...aiErrors,
  code_response_invalid: '服务返回结构不符合代码分析协议，请重新加载。',
  code_contract_invalid: '输入或结果不符合Skill v2契约，请检查字段、目标和引用关系。',
  code_request_mismatch: '输入和结果的request_id不一致。',
  code_evidence_invalid: '证据位置或原文不匹配，报告未保存。',
  code_candidate_not_found: '当前记录没有可下载的AI候选结果。',
  code_revalidation_invalid: '当前记录不能重新校验候选结果。',
  code_analysis_revalidate_owner_only: '只有原分析发起人可以重新校验候选结果。',
  code_candidate_storage_unavailable:
    'AI结果已返回，但本地候选文件保存失败；请检查服务器存储空间和权限。',
  code_both_sides_required: '前后端一致性必须同时选择后端与前端／移动端代码文件。',
  code_material_required: '需求符合性需要固定版本需求或原型依据。',
  code_source_unavailable: '代码来源不可用或没有读取权限。',
  code_source_changed: '来源类型或版本已变化，请重新选择。',
  code_material_unavailable: '资料已删除或不属于当前项目。',
  code_material_changed: 'GitHub资料版本已变化，请重新选择。',
  code_material_version_required: '请选择资料固定版本。',
  code_material_files_required: 'GitHub资料需选择具体文件。',
  prototype_link_unsupported: '未识别到支持的静态原型页面目录，请检查链接或目录格式。',
  prototype_link_unavailable: '原型链接读取失败，请检查地址后重试。',
  prototype_link_markdown_unsupported:
    '批注中的 Markdown 链接不属于当前原型目录或地址不受支持，请核对链接。',
  prototype_link_markdown_unavailable:
    '批注引用的 Markdown 文件读取失败或未取得有效正文，请核对文件后重试。',
  prototype_link_changed: '原型目录或链接已变化，请重新读取并选择页面。',
  prototype_link_too_large: '所选原型内容超过限制，请缩小页面范围。',
  code_material_unreadable: '资料未取得可分析正文。',
  code_material_bindings_required: '请为每份输入资料关联系统已有资料。',
  code_material_binding_mismatch: '资料关联或版本不匹配。',
  code_attachment_mismatch: '图片／PDF附件与固定输入不匹配。',
  code_path_excluded: '所选路径包含凭据、构建产物或越界文件，不能分析。',
  code_content_changed: '本地文件内容校验不一致，请重新读取。',
  code_text_required: '所选文件不是可分析的文本。',
  code_private_key_content: '源码含私钥标记或疑似密钥内容，已停止发送；请核对敏感内容后重试。',
  code_file_unavailable: '固定提交中没有所选文件或文件过大。',
  code_input_too_large: '分析范围超过16MB，请缩小范围；不会静默截断。',
  code_import_file_invalid: '请选择不超过16MB的JSON文件。',
  code_json_invalid: 'JSON文件无效，不能导入。',
  code_analysis_request_conflict: '请求标识已用于不同内容，请重新打开后提交。',
  code_handling_changed: '处理状态已被其他成员修改，请重新加载。',
  code_handling_note_required: '请填写人工处理说明。',
  code_report_not_ready: '分析尚未完成或不是v2报告。',
  code_worker_interrupted: 'Worker中断，未自动重试；可人工重新发起。',
  code_analysis_internal_error: '分析失败，请核对输入和个人AI配置后人工重试。',
  code_analysis_cancel_owner_only: '只有发起人可以取消。',
  code_legacy_not_supported: '历史v1任务不能作为v2继续执行，请新建分析。',
  code_chat_busy: '当前记录已有对话正在处理，请等待或由发起人取消。',
  code_chat_context_too_large: '对话上下文超过限制，未截断或发送。',
  code_access_lost: '项目或来源权限已失效。',
  github_repository_not_allowed: '当前GitHub连接未授权该仓库。',
  github_connection_required: '请选择本人GitHub连接。',
  github_connection_changed: 'GitHub连接已变化，请重新读取。',
  project_not_found: '项目不存在或已无访问权限。',
  risk_json_invalid: 'JSON格式无效或含重复字段。',
  responses_incomplete: 'AI响应不完整，报告未保存。',
  code_ref_invalid: '请选择有效分支或完整提交SHA。',
  code_title_required: '请填写分析名称。',
  code_finding_unavailable: '该发现不属于当前完成报告。',
  code_analysis_retry_invalid: '该任务当前不能重试。',
  code_question_required: '请输入代码分析问题。',
};
export function codeError(reason: unknown, onSessionEnd: () => void) {
  return apiErrorMessage(reason, onSessionEnd, codeErrors);
}

export type SourceSelection = {
  kind: 'GITHUB' | 'LOCAL';
  source_id: number;
  source_version: number;
  connection_id?: number;
  commit: string;
  files: { path: string; content?: string; sha256?: string }[];
};
export type MaterialSelection = {
  document_id: number;
  version_id: number | null;
  commit: string;
  paths: string[];
  snapshot: string;
  url: string;
};
export type MaterialBinding = { source_id: string; document_id: number; version_id: number | null };
export function codePreflight(
  targets: CodeTarget[],
  sources: { kind: CodeKind; count: number }[],
  materialCount: number,
) {
  const chosen = sources.filter((s) => s.count > 0),
    hasCode = chosen.some((s) => s.kind !== 'PROTOTYPE'),
    hasClient = chosen.some((s) => s.kind === 'WEB' || s.kind === 'FLUTTER'),
    hasBackend = chosen.some((s) => s.kind === 'BACKEND');
  const goals = targets.map((target) => ({
    target,
    ready:
      target === 'FRONTEND_BACKEND_MISMATCH'
        ? hasClient && hasBackend
        : target === 'REQUIREMENT_DEVIATION'
          ? hasCode && materialCount > 0
          : hasCode,
    reason:
      target === 'FRONTEND_BACKEND_MISMATCH'
        ? !hasClient && !hasBackend
          ? '缺少客户端与后端文件。'
          : !hasClient
            ? '缺少前端或移动端文件。'
            : !hasBackend
              ? '缺少后端文件。'
              : '两端已选择，接口关联仍需分析核查。'
        : target === 'REQUIREMENT_DEVIATION'
          ? !hasCode
            ? '未选择实现代码。'
            : !materialCount
              ? '未选择固定需求／原型依据。'
              : '仅核对所选代码职责范围。'
          : hasCode
            ? '可检查单端代码，不要求另一端。'
            : '未选择代码文件。',
  }));
  const blocking = !targets.length
    ? '请至少选择一个检查目标。'
    : goals.some((g) => g.target === 'FRONTEND_BACKEND_MISMATCH' && !g.ready)
      ? codeErrors.code_both_sides_required
      : !goals.some((g) => g.ready)
        ? '所有目标均缺少必要依据，请补充代码或资料。'
        : '';
  return { goals, blocking };
}
