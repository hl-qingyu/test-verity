import { createGuards } from './api/guards';
import { deletionErrors } from './analysisDeletionApi';
import { aiErrors } from './aiErrors';
import { apiErrorMessage, apiRequest } from './api/http';
import { parseVersion } from './documentApi';
import type { DocumentVersion } from './documentApi';

export const riskLevels = { HIGH: '高', MEDIUM: '中', LOW: '低' } as const;
export const riskStates = {
  PENDING: '待确认',
  NEEDS_INFO: '已确认待补充',
  RESOLVED: '已解决',
  NOT_APPLICABLE: '不适用',
} as const;
export const riskTypes = {
  FLOW_GAP: '流程缺失',
  RULE_GAP: '规则不完整',
  PERMISSION_GAP: '角色权限不清',
  AMBIGUITY: '表达歧义',
  SOURCE_DIFFERENCE: '资料不一致',
  DATA_GAP: '数据关系不清',
  NOT_VERIFIABLE: '无法验收',
} as const;
export const outcomes = { COMPLETE: '分析完成', PARTIAL: '部分完成', BLOCKED: '材料不足' } as const;
export type RiskState = keyof typeof riskStates;
export type Evidence = {
  source_id: string;
  segment_id: string;
  location: string;
  excerpt: string;
  observation: string;
};
export type Input = {
  contract_version: 3 | 4;
  request_id: string;
  focus: string;
  materials: {
    source_id: string;
    name: string;
    origin: 'REQUIREMENT' | 'PROTOTYPE';
    kind: string;
    snapshot_ref: string;
    read_state: string;
    read_note: string;
    segments: { segment_id: string; location: string; text: string; image_ref: string }[];
  }[];
};
export type Improvement = {
  proposal: string;
  rationale: string;
  tradeoffs: string;
  requires_confirmation: true;
};
export type Risk = {
  key: string;
  function_keys: string[];
  title: string;
  type: keyof typeof riskTypes;
  severity: keyof typeof riskLevels;
  severity_reason: string;
  basis: string;
  description: string;
  evidence: Evidence[];
  checked_scope: { source_id: string; segment_ids: string[] }[];
  impact: string;
  questions: string[];
  improvement: Improvement;
  source_comparison: {
    relation: string;
    sides: { statement: string; evidence: Evidence[] }[];
    known_facts: string;
    unknowns: string;
  } | null;
};
type RiskCandidateBody = {
  request_id: string;
  summary: { assessment: string; conclusion: string; priority_risk_keys: string[] };
  functions: {
    key: string;
    module: string;
    name: string;
    scope: string;
    evidence: Evidence[];
    risk_keys: string[];
  }[];
  risks: Risk[];
  optional_suggestions: (Improvement & { key: string; function_keys: string[]; title: string })[];
  limitations: { kind: string; source_ids: string[]; detail: string; effect: string }[];
};
type SegmentReferences = { segment_id: string; function_keys: string[]; risk_keys: string[] };
type ReferencedSegment = SegmentReferences & { disposition: 'REFERENCED' | 'UNREFERENCED' };
type LegacySegment = SegmentReferences & { disposition: string; reason: string };
type Coverage<T> = { source_id: string; segments: T[]; limitation: string };
export type RiskReport = RiskCandidateBody & { outcome: keyof typeof outcomes } & (
    | { contract_version: 3; coverage: Coverage<LegacySegment>[] }
    | { contract_version: 4; coverage: Coverage<ReferencedSegment>[] }
  );
export type Binding = {
  source_id: string;
  document_id: number;
  name: string;
  kind: string;
  purpose: string;
  deleted: boolean;
  version: DocumentVersion | null;
  url: string | null;
  branch: string | null;
  commit: string | null;
};
export type Handling = {
  risk_key: string;
  status: RiskState;
  note: string;
  history: {
    from: RiskState;
    to: RiskState;
    note: string;
    actor: string;
    actor_id: number;
    time: string;
  }[];
};
export type RiskDetail = {
  id: number;
  project_id: number;
  title: string;
  revision: number;
  terminal_task_id?: number | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  input: Input;
  report: RiskReport;
  review_warnings: ReviewWarning[];
  bindings: Binding[];
  handling: Handling[];
  manual_risks: ManualRisk[];
  duplicate: boolean;
};
export type ReviewWarning = {
  path: string;
  code: string;
  source_id: string;
  segment_id: string;
  risk_key: string;
};
export type ManualRisk = {
  id: number;
  report_id: number;
  function_key: string;
  message_turn_id: number;
  request_id: string;
  title: string;
  severity: keyof typeof riskLevels;
  type: keyof typeof riskTypes;
  description: string;
  evidence: Evidence[];
  impact: string;
  questions: string[];
  improvement: Improvement;
  status: RiskState;
  note: string;
  history: Handling['history'];
  revision: number;
  created_by: string;
  created_at: string;
  updated_at: string;
};
export type RiskAnalysisTask = {
  ai?: unknown;
  terminal_available?: boolean;
  can_delete?: boolean;
  id: number;
  project_id: number;
  request_id: string;
  retry_of: number | null;
  title: string;
  focus: string;
  selections: (Pick<SourceBinding, 'document_id' | 'version_id'> & {
    paths: string[];
    snapshot: string;
    url: string | null;
  })[];
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  error_code: string;
  report_id: number | null;
  created_by: string;
  can_cancel: boolean;
  candidate_available: boolean;
  can_revalidate: boolean;
  function_risk_corrections: { function_key: string; before: string[]; after: string[] }[];
  created_at: string;
  updated_at: string;
};
export type CatalogItem = {
  id: string;
  source_kind: 'ANALYSIS' | 'MANUAL';
  manual_id?: number;
  message_turn_id?: number;
  report_id: number;
  report_title: string;
  risk_key: string;
  risk: Pick<
    Risk,
    | 'key'
    | 'function_keys'
    | 'title'
    | 'type'
    | 'severity'
    | 'description'
    | 'evidence'
    | 'impact'
    | 'questions'
    | 'improvement'
  >;
  review_warnings: ReviewWarning[];
  functions: { key: string; module: string; name: string }[];
  status: RiskState;
  note: string;
  history: Handling['history'];
  revision: number;
  created_at: string;
};
export type RiskCatalog = {
  overview: {
    reports: number;
    functions: number;
    risks: number;
    high: number;
    medium: number;
    low: number;
    pending: number;
  };
  reports: {
    can_delete?: boolean;
    id: number;
    title: string;
    created_at: string;
    created_by: string;
    outcome: keyof typeof outcomes;
    functions: number;
    risks: number;
    review_warning_count: number;
    materials: { name: string; version: string }[];
  }[];
  functions: {
    id: string;
    report_id: number;
    key: string;
    module: string;
    name: string;
    risk_count: number;
  }[];
  total: number;
  page: number;
  pages: number;
  items: CatalogItem[];
};
export type ReportItem = {
  id: number;
  title: string;
  outcome: keyof typeof outcomes;
  functions: number;
  risks: number;
  created_by: string;
  created_at: string;
};
export type MaterialOption = {
  id: number;
  name: string;
  kind: string;
  url: string | null;
  purpose: string;
  versions: DocumentVersion[];
};
export type SourceBinding = { source_id: string; document_id: number; version_id: number | null };

function invalid(): never {
  throw new Error('risk_response_invalid');
}
const guards = createGuards('risk_response_invalid');
const obj = guards.obj,
  array = guards.array,
  string = guards.str,
  number = guards.int,
  boolean = guards.bool;

function strings(v: unknown): string[] {
  return array(v).map(string);
}
function nullable(v: unknown): string | null {
  return v === null ? null : string(v);
}
const choice = guards.choice;
function parseEvidence(v: unknown): Evidence {
  const o = obj(v);
  return {
    source_id: string(o.source_id),
    segment_id: string(o.segment_id),
    location: string(o.location),
    excerpt: string(o.excerpt),
    observation: string(o.observation),
  };
}
function parseReviewWarnings(value: unknown): ReviewWarning[] {
  return array(value === undefined ? [] : value).map((item) => {
    const warning = obj(item);
    return {
      path: string(warning.path),
      code: string(warning.code),
      source_id: string(warning.source_id),
      segment_id: string(warning.segment_id),
      risk_key: string(warning.risk_key),
    };
  });
}
function improvement(v: unknown): Improvement {
  const o = obj(v);
  if (o.requires_confirmation !== true) return invalid();
  return {
    proposal: string(o.proposal),
    rationale: string(o.rationale),
    tradeoffs: string(o.tradeoffs),
    requires_confirmation: true,
  };
}
export function parseRiskInput(v: unknown): Input {
  const o = obj(v);
  if (o.contract_version !== 3 && o.contract_version !== 4)
    throw new Error('risk_version_unsupported');
  return {
    contract_version: o.contract_version,
    request_id: string(o.request_id),
    focus: string(o.focus),
    materials: array(o.materials).map((v) => {
      const m = obj(v);
      return {
        source_id: string(m.source_id),
        name: string(m.name),
        origin: choice(m.origin, { REQUIREMENT: '', PROTOTYPE: '' }),
        kind: string(m.kind),
        snapshot_ref: string(m.snapshot_ref),
        read_state: string(m.read_state),
        read_note: string(m.read_note),
        segments: array(m.segments).map((v) => {
          const s = obj(v);
          return {
            segment_id: string(s.segment_id),
            location: string(s.location),
            text: string(s.text),
            image_ref: string(s.image_ref),
          };
        }),
      };
    }),
  };
}
function parseRiskCandidateBody(o: Record<string, unknown>): RiskCandidateBody {
  const summary = obj(o.summary);
  return {
    request_id: string(o.request_id),
    summary: {
      assessment: string(summary.assessment),
      conclusion: string(summary.conclusion),
      priority_risk_keys: strings(summary.priority_risk_keys),
    },
    functions: array(o.functions).map((v) => {
      const f = obj(v);
      return {
        key: string(f.key),
        module: string(f.module),
        name: string(f.name),
        scope: string(f.scope),
        evidence: array(f.evidence).map(parseEvidence),
        risk_keys: strings(f.risk_keys),
      };
    }),
    risks: array(o.risks).map((v) => {
      const r = obj(v),
        comparison = r.source_comparison === null ? null : obj(r.source_comparison);
      return {
        key: string(r.key),
        function_keys: strings(r.function_keys),
        title: string(r.title),
        type: choice(r.type, riskTypes),
        severity: choice(r.severity, riskLevels),
        severity_reason: string(r.severity_reason),
        basis: string(r.basis),
        description: string(r.description),
        evidence: array(r.evidence).map(parseEvidence),
        checked_scope: array(r.checked_scope).map((v) => {
          const s = obj(v);
          return { source_id: string(s.source_id), segment_ids: strings(s.segment_ids) };
        }),
        impact: string(r.impact),
        questions: strings(r.questions),
        improvement: improvement(r.improvement),
        source_comparison: comparison && {
          relation: string(comparison.relation),
          known_facts: string(comparison.known_facts),
          unknowns: string(comparison.unknowns),
          sides: array(comparison.sides).map((v) => {
            const s = obj(v);
            return {
              statement: string(s.statement),
              evidence: array(s.evidence).map(parseEvidence),
            };
          }),
        },
      };
    }),
    optional_suggestions: array(o.optional_suggestions).map((v) => {
      const s = obj(v);
      return {
        ...improvement(s),
        key: string(s.key),
        title: string(s.title),
        function_keys: strings(s.function_keys),
      };
    }),
    limitations: array(o.limitations).map((v) => {
      const l = obj(v);
      return {
        kind: string(l.kind),
        source_ids: strings(l.source_ids),
        detail: string(l.detail),
        effect: string(l.effect),
      };
    }),
  };
}

export function parseRiskImportReport(v: unknown): RiskCandidateBody & { contract_version: 3 | 4 } {
  const o = obj(v);
  if (o.contract_version === 4 && !('coverage' in o) && !('outcome' in o)) {
    return { ...parseRiskCandidateBody(o), contract_version: 4 };
  }
  return parseRiskReport(o);
}

export function parseRiskReport(v: unknown): RiskReport {
  const o = obj(v);
  if (o.contract_version !== 3 && o.contract_version !== 4)
    throw new Error('risk_version_unsupported');
  const body = { ...parseRiskCandidateBody(o), outcome: choice(o.outcome, outcomes) };
  const coverage = array(o.coverage).map((value) => {
    const c = obj(value);
    return {
      source_id: string(c.source_id),
      limitation: string(c.limitation),
      segments: array(c.segments).map(obj),
    };
  });
  function references(s: Record<string, unknown>): SegmentReferences {
    return {
      segment_id: string(s.segment_id),
      function_keys: strings(s.function_keys),
      risk_keys: strings(s.risk_keys),
    };
  }
  if (o.contract_version === 4) {
    return {
      ...body,
      contract_version: 4,
      coverage: coverage.map((source) => ({
        ...source,
        segments: source.segments.map((s) => ({
          ...references(s),
          disposition: choice(s.disposition, { REFERENCED: '', UNREFERENCED: '' }),
        })),
      })),
    };
  }
  return {
    ...body,
    contract_version: 3,
    coverage: coverage.map((source) => ({
      ...source,
      segments: source.segments.map((s) => ({
        ...references(s),
        disposition: string(s.disposition),
        reason: string(s.reason),
      })),
    })),
  };
}
export function parseRiskDetail(v: unknown, project: number): RiskDetail {
  const o = obj(v);
  if (number(o.project_id) !== project) return invalid();
  const input = parseRiskInput(o.input),
    report = parseRiskReport(o.report);
  if (input.request_id !== report.request_id || input.contract_version !== report.contract_version)
    return invalid();
  return {
    id: number(o.id),
    project_id: project,
    title: string(o.title),
    revision: number(o.revision),
    terminal_task_id: o.terminal_task_id == null ? null : number(o.terminal_task_id),
    created_by: string(o.created_by),
    created_at: string(o.created_at),
    updated_at: string(o.updated_at),
    input,
    report,
    review_warnings: parseReviewWarnings(o.review_warnings),
    duplicate: boolean(o.duplicate),
    bindings: array(o.bindings).map((v) => {
      const b = obj(v),
        version = b.version === null ? null : parseVersion(b.version),
        document_id = number(b.document_id);
      if (version && version.document_id !== document_id) return invalid();
      return {
        source_id: string(b.source_id),
        document_id,
        name: string(b.name),
        kind: string(b.kind),
        purpose: string(b.purpose),
        deleted: boolean(b.deleted),
        version,
        url: nullable(b.url),
        branch: nullable(b.branch),
        commit: nullable(b.commit),
      };
    }),
    manual_risks: array(o.manual_risks).map(parseManualRisk),
    handling: array(o.handling).map((v) => {
      const h = obj(v);
      if (!report.risks.some((r) => r.key === h.risk_key)) return invalid();
      return {
        risk_key: string(h.risk_key),
        status: choice(h.status, riskStates),
        note: string(h.note),
        history: array(h.history).map((v) => {
          const a = obj(v);
          return {
            from: choice(a.from, riskStates),
            to: choice(a.to, riskStates),
            note: string(a.note),
            actor: string(a.actor),
            actor_id: number(a.actor_id),
            time: string(a.time),
          };
        }),
      };
    }),
  };
}

function parseHistory(v: unknown): Handling['history'] {
  return array(v).map((v) => {
    const item = obj(v);
    return {
      from: choice(item.from, riskStates),
      to: choice(item.to, riskStates),
      note: string(item.note),
      actor: string(item.actor),
      actor_id: number(item.actor_id),
      time: string(item.time),
    };
  });
}

export function parseManualRisk(v: unknown): ManualRisk {
  const o = obj(v);
  return {
    id: number(o.id),
    report_id: number(o.report_id),
    function_key: string(o.function_key),
    message_turn_id: number(o.message_turn_id),
    request_id: string(o.request_id),
    title: string(o.title),
    severity: choice(o.severity, riskLevels),
    type: choice(o.type, riskTypes),
    description: string(o.description),
    evidence: array(o.evidence).map(parseEvidence),
    impact: string(o.impact),
    questions: strings(o.questions),
    improvement: improvement(obj(o.improvement)),
    status: choice(o.status, riskStates),
    note: string(o.note),
    history: parseHistory(o.history),
    revision: number(o.revision),
    created_by: string(o.created_by),
    created_at: string(o.created_at),
    updated_at: string(o.updated_at),
  };
}

export function parseRiskAnalysisTask(v: unknown): RiskAnalysisTask {
  const o = obj(v);
  return {
    id: number(o.id),
    project_id: number(o.project_id),
    request_id: string(o.request_id),
    ai: o.ai,
    terminal_available: o.terminal_available === undefined ? false : boolean(o.terminal_available),
    retry_of: o.retry_of === null ? null : number(o.retry_of),
    title: string(o.title),
    focus: string(o.focus),
    selections: array(o.selections).map((v) => {
      const s = obj(v);
      return {
        document_id: number(s.document_id),
        version_id: s.version_id === null ? null : number(s.version_id),
        paths: s.paths === undefined ? [] : array(s.paths).map(string),
        snapshot: s.snapshot === undefined ? '' : string(s.snapshot),
        url: s.url === undefined || s.url === null ? null : string(s.url),
      };
    }),
    status: choice(o.status, {
      QUEUED: '',
      RUNNING: '',
      COMPLETED: '',
      FAILED: '',
      CANCELLED: '',
    }),
    error_code: string(o.error_code),
    report_id: o.report_id === null ? null : number(o.report_id),
    created_by: string(o.created_by),
    can_cancel: boolean(o.can_cancel),
    can_delete: o.can_delete === undefined ? undefined : boolean(o.can_delete),
    candidate_available: boolean(o.candidate_available),
    can_revalidate: boolean(o.can_revalidate),
    function_risk_corrections: array(o.function_risk_corrections).map((item) => {
      const correction = obj(item);
      return {
        function_key: string(correction.function_key),
        before: array(correction.before).map(string),
        after: array(correction.after).map(string),
      };
    }),
    created_at: string(o.created_at),
    updated_at: string(o.updated_at),
  };
}

export async function riskAnalyses(url: string, signal: AbortSignal): Promise<RiskAnalysisTask[]> {
  const root = obj(await apiRequest<unknown>(url, { signal }));
  return array(root.items).map(parseRiskAnalysisTask);
}

export async function riskCatalog(url: string, signal: AbortSignal): Promise<RiskCatalog> {
  const root = obj(await apiRequest<unknown>(url, { signal }));
  const overview = obj(root.overview);
  return {
    overview: {
      reports: number(overview.reports, 0),
      functions: number(overview.functions, 0),
      risks: number(overview.risks, 0),
      high: number(overview.high, 0),
      medium: number(overview.medium, 0),
      low: number(overview.low, 0),
      pending: number(overview.pending, 0),
    },
    reports: array(root.reports).map((v) => {
      const o = obj(v);
      return {
        id: number(o.id),
        can_delete: o.can_delete === undefined ? undefined : boolean(o.can_delete),
        title: string(o.title),
        created_at: string(o.created_at),
        created_by: string(o.created_by),
        outcome: choice(o.outcome, outcomes),
        functions: number(o.functions, 0),
        risks: number(o.risks, 0),
        review_warning_count: number(o.review_warning_count ?? 0, 0),
        materials: array(o.materials).map((v) => {
          const material = obj(v);
          return { name: string(material.name), version: string(material.version) };
        }),
      };
    }),
    functions: array(root.functions).map((v) => {
      const o = obj(v);
      return {
        id: string(o.id),
        report_id: number(o.report_id),
        key: string(o.key),
        module: string(o.module),
        name: string(o.name),
        risk_count: number(o.risk_count, 0),
      };
    }),
    total: number(root.total, 0),
    page: number(root.page),
    pages: number(root.pages),
    items: array(root.items).map((v) => {
      const o = obj(v),
        risk = obj(o.risk);
      return {
        id: string(o.id),
        source_kind: choice(o.source_kind, { ANALYSIS: '', MANUAL: '' }),
        manual_id: o.manual_id === undefined ? undefined : number(o.manual_id),
        message_turn_id: o.message_turn_id === undefined ? undefined : number(o.message_turn_id),
        report_id: number(o.report_id),
        report_title: string(o.report_title),
        risk_key: string(o.risk_key),
        risk: {
          key: string(risk.key),
          function_keys: strings(risk.function_keys),
          title: string(risk.title),
          type: choice(risk.type, riskTypes),
          severity: choice(risk.severity, riskLevels),
          description: string(risk.description),
          evidence: array(risk.evidence).map(parseEvidence),
          impact: string(risk.impact),
          questions: strings(risk.questions),
          improvement: improvement(obj(risk.improvement)),
        },
        review_warnings: parseReviewWarnings(o.review_warnings),
        functions: array(o.functions).map((v) => {
          const f = obj(v);
          return { key: string(f.key), module: string(f.module), name: string(f.name) };
        }),
        status: choice(o.status, riskStates),
        note: string(o.note),
        history: parseHistory(o.history),
        revision: number(o.revision),
        created_at: string(o.created_at),
      };
    }),
  };
}
export async function riskDetailRequest(url: string, project: number, options?: RequestInit) {
  return parseRiskDetail(await apiRequest<unknown>(url, options), project);
}
export async function riskListing(url: string, signal: AbortSignal) {
  const o = obj(await apiRequest<unknown>(url, { signal }));
  return {
    has_more: boolean(o.has_more),
    items: array(o.items).map((v) => {
      const r = obj(v);
      return {
        id: number(r.id),
        title: string(r.title),
        outcome: choice(r.outcome, outcomes),
        functions: number(r.functions, 0),
        risks: number(r.risks, 0),
        created_by: string(r.created_by),
        created_at: string(r.created_at),
      };
    }),
  };
}
export async function riskOptions(url: string, signal: AbortSignal): Promise<MaterialOption[]> {
  const o = obj(await apiRequest<unknown>(url, { signal }));
  return array(o.materials).map((v) => {
    const m = obj(v),
      id = number(m.id),
      versions = array(m.versions).map(parseVersion);
    if (versions.some((v) => v.document_id !== id)) return invalid();
    return {
      id,
      name: string(m.name),
      kind: string(m.kind),
      url: m.url === undefined || m.url === null ? null : string(m.url),
      purpose: string(m.purpose),
      versions,
    };
  });
}
export async function readRiskFile(file: File) {
  if (!file.name.toLowerCase().endsWith('.json') || !file.size)
    throw new Error('risk_json_invalid');
  if (file.size > 16 * 1024 * 1024) throw new Error('risk_file_too_large');
  const text = await file.text();
  try {
    return { filename: file.name, text, data: JSON.parse(text.replace(/^\uFEFF/, '')) as unknown };
  } catch {
    throw new Error('risk_json_invalid');
  }
}
const contractSnapshotMismatch = '分析契约版本不一致。若已保存候选，可重新校验。';

export function riskError(e: unknown, onSessionEnd: () => void): string {
  if (e instanceof Error && e.message.startsWith('risk_report_invalid|')) {
    const [, path, reason] = e.message.split('|');
    const reasons: Record<string, string> = {
      request_mismatch: '两份文件的调用标识不一致',
      version_mismatch: '两份文件的契约版本不一致',
      derived_coverage_mismatch: '报告覆盖与固定输入及证据引用不一致',
      derived_outcome_mismatch: '报告总体状态与固定输入及分析边界不一致',
      project_mismatch: '输入属于其他项目',
      evidence_excerpt_mismatch: '摘录不在对应输入片段中',
      evidence_location_mismatch: '证据定位与输入不一致',
      unknown_reference: '引用的标识不存在',
      invalid_evidence: '证据引用了未审查或不存在的片段',
      inconsistent_reference: '功能与风险关联不一致',
      source_coverage_mismatch: '资料清单或来源关联不完整',
      segment_coverage_mismatch: '片段覆盖不完整',
      incomplete_coverage: '读取不完整，不能标为全部完成',
      duplicate_id: '标识重复',
      string_type: '应为文本，AI返回了列表或其他类型',
      string_too_short: '文本不能为空',
      string_too_long: '文本超过字段长度限制',
      extra_forbidden: '包含契约未定义的字段',
      missing: '缺少必填字段',
      literal_error: '版本或枚举值不正确',
    };
    return `校验未通过：${path} — ${reasons[reason] || '字段格式或关联关系不符合契约'}。`;
  }
  return apiErrorMessage(e, onSessionEnd, {
    ...aiErrors,
    risk_response_invalid: '文件或返回结果结构不完整，请核对对应版本的格式。',
    risk_version_unsupported: '支持需求风险契约 v3 和 v4，请核对输入与报告的版本。',
    risk_json_invalid: '请选择有效的完整 JSON，不要包含 Markdown 围栏或重复字段。',
    risk_file_too_large: '每份 JSON 最大 16 MB，请检查是否选错文件。',
    risk_source_unavailable: '来源不存在、已删除、类型不匹配或不属于当前项目。',
    prototype_link_selection_required: '请读取原型链接并选择具体页面。',
    prototype_link_unsupported: '未识别到支持的静态原型页面目录，请检查链接或目录格式。',
    prototype_link_unavailable: '原型链接读取失败，请稍后重试。',
    prototype_link_markdown_unsupported:
      '批注中的 Markdown 链接不属于当前原型目录或地址不受支持，请核对链接。',
    prototype_link_markdown_unavailable:
      '批注引用的 Markdown 文件读取失败或未取得有效正文，请核对文件后重试。',
    prototype_link_changed: '原型链接或目录已变化，请重新读取页面。',
    prototype_link_too_large: '所选原型内容超过限制，请缩小页面范围。',
    risk_version_required: '请关联已有文件的固定版本；图片/PDF不能只关联实时链接。',
    risk_report_not_found: '报告不存在或无权访问。',
    risk_report_changed: '报告已被其他成员更新，请重新打开风险后处理。',
    risk_binding_conflict: '相同输入与结果已经入库，但来源关联不同；请查看已有报告。',
    risk_item_not_found: '风险已不存在，请重新加载。',
    risk_function_not_found: '关联功能不存在，请重新加载分析记录。',
    risk_message_not_found: '来源AI回复不存在、未完成或不属于当前分析。',
    risk_manual_evidence_invalid: '原文依据与固定分析输入不一致，请重新选择并核对摘录。',
    risk_manual_request_conflict: '重复新增请求的内容不一致，请重新打开表单。',
    risk_analysis_request_conflict: '重复分析请求的内容不一致，请重新新建会话。',
    risk_analysis_retry_invalid: '只能重试本项目内失败或已停止的分析任务。',
    risk_analysis_contract_mismatch: contractSnapshotMismatch,
    skill_snapshot_missing:
      '历史任务未保存当时的Skill指令，不能用当前文件冒充重试；请明确新建分析。',
    risk_analysis_cancel_owner_only: '只有本次分析发起人可以停止任务。',
    risk_analysis_not_found: '分析任务不存在或已无访问权限。',
    risk_candidate_not_found: '该记录没有已保存的AI候选结果。',
    risk_candidate_storage_unavailable: 'AI候选结果存储不可用，报告未入库。',
    risk_revalidation_invalid: '该任务当前不能重新校验候选。',
    risk_revalidation_owner_only: '只有原发起人可以重新校验候选。',
    github_connection_required: '请先配置本人有权读取该仓库的GitHub连接。',
    risk_export_empty: '当前筛选没有可导出的风险。',
    invalid_request: '提交字段校验未通过，请刷新页面后重试。',
    project_not_found: '项目不存在或你已不在该项目中。',
    document_storage_unavailable: '关联的资料原件暂时不可读取。',
  });
}

export function riskTaskFailure(code: string): string {
  if (code.startsWith('risk_report_invalid|')) return riskError(new Error(code), () => {});
  const messages: Record<string, string> = {
    ...deletionErrors,
    ...aiErrors,
    risk_analysis_contract_mismatch: contractSnapshotMismatch,
    risk_analysis_worker_interrupted: '服务重启中断，未自动重试；请确认后人工重试。',
    risk_analysis_internal_error: '分析处理失败，请人工重试或联系管理员。',
    risk_source_unavailable: '所选资料已不可用。',
    prototype_link_unavailable: '原型链接读取失败，请检查后人工重试。',
    prototype_link_markdown_unsupported:
      '批注中的 Markdown 链接不属于当前原型目录或地址不受支持，请核对链接后新建分析。',
    prototype_link_markdown_unavailable:
      '批注引用的 Markdown 文件读取失败或未取得有效正文，请核对文件后新建分析。',
    prototype_link_changed: '原型链接或目录已变化，请重新选择页面并新建分析。',
    prototype_link_too_large: '原型内容超过限制，请缩小页面范围后新建分析。',
    document_storage_unavailable: '资料原件暂时不可读取。',
    github_connection_required: '发起人的GitHub连接无法读取所选原型。',
    risk_candidate_storage_unavailable: 'AI已返回，但候选文件保存失败；报告未入库。',
  };
  return messages[code] || (code ? '分析失败，请检查个人配置和资料后人工重试。' : '');
}
