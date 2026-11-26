import { blankDesign, DESIGN_FIELDS, CASE_COLUMNS } from './caseApi';
import type { Design, CaseRow } from './caseApi';

export const generationKinds = {
  NEW: '新增',
  REUSE: '复用',
  UPDATE: '修改',
  RETIRE: '停用',
} as const;
export type GenerationKind = keyof typeof generationKinds;
export const GENERATION_PAGE_SIZE = 20;
export type GenerationMaterial = {
  connectionId?: number;
  sourceId: string;
  documentId?: number;
  name: string;
  purpose: string;
  kind: string;
  version: string;
  versionName?: string;
  beforeName?: string;
  side?: string;
  before: string;
  update: string;
  paths: string[];
  beforePaths?: string[];
  readState: string;
  segments: { id: string; location: string; text: string }[];
};
export type GenerationEvidence = {
  source: string;
  segment: string;
  side: string;
  quote: string;
  verifiedQuote?: boolean;
  quoteWarning?: string;
};
export type GenerationSuggestion = {
  nativeResultId?: string;
  functionRef?: string;
  key: string;
  kind: GenerationKind;
  function: string;
  design: Design;
  before?: Design;
  generated?: Design;
  caseId: number | null;
  baseVersion: number | null;
  reason: string;
  blocked: boolean;
  evidence: GenerationEvidence[];
};
export function generationGroups(rows: GenerationSuggestion[]) {
  const groups = new Map<string, GenerationSuggestion[]>();
  for (const row of rows) {
    if (!groups.has(row.function)) groups.set(row.function, []);
    groups.get(row.function)!.push(row);
  }
  return groups;
}
export type GenerationQuestion = {
  nativeResultId?: string;
  functionRef?: string;
  key: string;
  function: string;
  title: string;
  text: string;
  evidence: string;
};
export type GenerationHandling = {
  editedFields?: (keyof Design)[];
  categoryId?: number;
  status: '待审阅' | '已忽略' | '需人工确认' | '已应用' | '已复用';
  draft: Design;
  note: string;
  actor: string;
  time: string;
  revision: number;
  evidenceChecked: boolean;
  resolved: boolean;
  reviewedTarget?: { id: number; version: number; design: Design };
};
export type GenerationDecision = {
  key: string;
  questionKey: string;
  conclusion: string;
  basis: string;
  affected: string;
  function: string;
  actor: string;
  time: string;
  version: number;
};
export type GenerationCandidateIssue = {
  nativeResultId?: string;
  key: string;
  issueId: string;
  batchId: number;
  kind: 'case' | 'note' | 'response';
  ordinal: number;
  status: 'PENDING' | 'RESOLVED' | 'IGNORED';
  reason: string;
  rawJson: string;
  correctedJson: string;
  duplicates: { path: string; values: string[] }[];
  note: string;
  canEdit: boolean;
};
export type GenerationBatch = {
  nativeResultId?: string;
  terminalAvailable?: boolean;
  startedAt?: string | null;
  progressAt?: string | null;
  diagnostics?: Record<string, string | number>;
  id?: number;
  inputBytes?: number;
  candidateAvailable?: boolean;
  key: string;
  function: string;
  status: string;
  attempts: number;
  reason: string;
};
export type GenerationFailure = {
  key: string;
  caseId: number | null;
  version: number | null;
  reason: string;
  time: string;
  categoryId?: number | null;
  categoryMode?: 'KEEP' | 'SET' | 'CLEAR';
};
export type GenerationRecord = {
  nativeRounds?: {
    id: string;
    batchId: number;
    batchRef: string;
    timestamp: string;
    caseCount: number;
    status: string;
  }[];
  candidateIssues?: GenerationCandidateIssue[];
  timings?: { startedAt: string | null; finishedAt: string | null }[];
  riskReportIds?: number[];
  id: string;
  projectId: number;
  ownerId: number;
  title: string;
  createdAt: string;
  mode: 'INITIAL' | 'UPDATE';
  origin: 'DRAFT' | 'PREVIEW' | 'SERVER';
  status?: string;
  serverRevision?: number;
  canCancel?: boolean;
  skillVersion?: string;
  planNote?: string;
  ai_config?: unknown;
  aiPreview?: {
    name: string;
    model: string;
    version: number;
    call_mode?: 'RESPONSES_API' | 'CODEX_EXEC';
    preference_version?: number;
  } | null;
  rawReports?: Record<string, unknown>[];
  applications?: {
    id: number;
    requestId?: string;
    status: string;
    items: Record<string, unknown>[];
    error: string;
  }[];
  cancelled: boolean;
  scope: string;
  focus: string;
  materials: GenerationMaterial[];
  cases: CaseRow[];
  caseScope: string;
  libraryRevision: number | null;
  baselineId: string;
  suggestions: GenerationSuggestion[];
  questions: GenerationQuestion[];
  handling: Record<string, GenerationHandling[]>;
  decisions: GenerationDecision[];
  failures: GenerationFailure[];
  failureHistory?: GenerationFailure[];
  chatDrafts: Record<string, string>;
  actionDrafts?: Record<string, { action: string; targetId: number | null; reason: string }>;
  batches: GenerationBatch[];
  limitations: string[];
  outcome: string;
  inputText?: string;
  reportText?: string;
  parentId?: string;
  decisionKey?: string;
};

export function generationRoundRecord(
  record: GenerationRecord | null,
  id: string,
): GenerationRecord | null {
  if (!record || !id) return record;
  const rounds = record.nativeRounds || [],
    round = rounds.find((r) => r.id === id),
    refs = new Set(rounds.map((r) => r.batchRef));
  const match = (value: { nativeResultId?: string }) =>
    id === '__initial__' ? !value.nativeResultId : value.nativeResultId === id;
  return {
    ...record,
    suggestions: record.suggestions.filter(match),
    questions: record.questions.filter(match),
    candidateIssues: record.candidateIssues?.filter(match),
    rawReports: record.rawReports?.filter((r) =>
      id === '__initial__' ? !refs.has(String(r.batch_ref)) : r.batch_ref === round?.batchRef,
    ),
  };
}
export type GenerationSummary = Pick<
  GenerationRecord,
  'id' | 'projectId' | 'title' | 'createdAt' | 'mode' | 'timings'
> & {
  ownerId?: number;
  status: string;
  serverRevision: number;
  hasMaterials: boolean;
  active: boolean;
  refreshKey: string;
};
export function generationDuration(timings: GenerationRecord['timings'], now: number): string {
  if (!timings?.length || !timings.some((t) => t.startedAt)) return '—';
  let milliseconds = 0;
  for (const timing of timings) {
    if (!timing.startedAt) return '—';
    const start = Date.parse(timing.startedAt),
      end = timing.finishedAt ? Date.parse(timing.finishedAt) : now;
    if (!Number.isFinite(start) || !Number.isFinite(end)) return '—';
    milliseconds += Math.max(0, end - start);
  }
  const seconds = Math.floor(milliseconds / 1000);
  return [Math.floor(seconds / 3600), Math.floor((seconds % 3600) / 60), seconds % 60]
    .map((n) => String(n).padStart(2, '0'))
    .join(':');
}
export const generationTabs = {
  suggestions: '用例建议',
  questions: '冲突与待澄清',
  report: '完整报告',
} as const;
export type GenerationTab = keyof typeof generationTabs;
const object = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw Error('JSON对象结构无效。');
  return v as Record<string, unknown>;
};
function text(v: unknown, fallback?: string): string {
  if (v === undefined && fallback !== undefined) return fallback;
  if (typeof v !== 'string' || v.length > 1000000 || v.includes('\0'))
    throw Error('文本无效或过长。');
  return v;
}
export function generationDesign(v: unknown): Design {
  const o = object(v),
    result = blankDesign();
  const aliases: Record<string, string> = {
    type: 'case_type',
    pre: 'preconditions',
    data: 'data_requirements',
  };
  for (const field of Object.keys(o))
    if (!DESIGN_FIELDS.includes(field as keyof Design) && !Object.hasOwn(aliases, field))
      throw Error('设计包含编号、测试结果或其他非法字段。');
  for (const field of DESIGN_FIELDS) {
    const alias = Object.keys(aliases).find((a) => aliases[a] === field);
    if (alias && o[field] !== undefined && o[alias] !== undefined && o[field] !== o[alias])
      throw Error('设计字段别名相互冲突。');
    result[field] = text(o[field] ?? (alias ? o[alias] : undefined), '');
  }
  const limits: Record<keyof Design, number> = {
    module: 500,
    structure: 1000,
    case_type: 200,
    priority: 2,
    description: 4000,
    title: 4000,
    preconditions: 30000,
    steps: 30000,
    expected: 30000,
    remark: 10000,
    data_requirements: 10000,
    cleanup: 10000,
  };
  if (DESIGN_FIELDS.some((f) => result[f].length > limits[f]))
    throw Error('用例设计字段超过安全长度。');
  if (result.priority && !['P0', 'P1', 'P2', 'P3', 'P4'].includes(result.priority))
    throw Error('优先级必须为P0–P4或空。');
  return result;
}
export function currentHandling(record: GenerationRecord, suggestion: GenerationSuggestion) {
  return record.handling[suggestion.key]?.at(-1);
}
export function generationAdoption(record: GenerationRecord) {
  const candidates = record.suggestions.filter(
      (s) => ['NEW', 'UPDATE'].includes(s.kind) && !s.key.startsWith('manual:'),
    ),
    adopted = candidates.filter((s) => currentHandling(record, s)?.status === '已应用').length,
    total = candidates.length;
  return { adopted, total, rate: total ? `${((adopted / total) * 100).toFixed(1)}%` : '—' };
}
export function generationReady(record: GenerationRecord, s: GenerationSuggestion) {
  const h = currentHandling(record, s),
    d = h?.draft || s.design;
  return (
    (h?.status || '待审阅') === '待审阅' &&
    (!s.blocked || !!h?.resolved) &&
    (!['NEW', 'UPDATE'].includes(s.kind) ||
      ['title', 'steps', 'expected'].every((f) => d[f as keyof Design].trim())) &&
    s.evidence.length > 0
  );
}
export function generationSelection(
  record: GenerationRecord,
  rows: GenerationSuggestion[],
  selected: string[],
) {
  return [
    ...new Set([
      ...selected,
      ...rows.filter((s) => s.kind !== 'RETIRE' && generationReady(record, s)).map((s) => s.key),
    ]),
  ];
}
// The HTML prototype's display format, not a production Skill or server-side validator.
export type GenerationPreviewItem = {
  key: string;
  kind: GenerationKind;
  design: Design;
  revision: number;
  problem: string;
  matches: CaseRow[];
  target?: CaseRow;
  categoryId?: number | null;
};
export function generationMarkdown(record: GenerationRecord) {
  return (
    `# ${record.title}\n\n> ${record.origin === 'SERVER' ? '项目固定生成记录；分析与人工应用状态分开，不代表测试通过。' : '页面草稿或历史预览；未进行AI分析、正式入库或执行测试。'}\n\n范围：${record.scope}\n${record.materials.map((m) => `${m.name} / ${m.versionName || m.version} / ${m.beforeName || m.before} / ${m.side || ''} / ${m.update}\n${m.paths.join('\n')}`).join('\n')}\n\n` +
    record.suggestions
      .map((s) => {
        const h = currentHandling(record, s),
          d = h?.draft || s.design;
        return `## ${s.key} ${generationKinds[s.kind]} · ${d.title}\n${s.reason}\n功能：${s.function}\n目标：${s.caseId || '新增'} / v${s.baseVersion || '—'}\n${DESIGN_FIELDS.map((f) => `${CASE_COLUMNS.find((c) => c[0] === f)?.[1] || f}：${d[f]}`).join('\n')}\n${s.evidence.map((e) => `${e.side} ${e.source}/${e.segment}：${e.quote}`).join('\n')}\n人工草稿：${h?.status || '待审阅'} ${h?.note || ''}\n${(record.handling[s.key] || []).map((h) => `${h.time} / ${h.actor} / ${h.status} / ${h.note}`).join('\n')}\n`;
      })
      .join('\n') +
    `\n## 问题与澄清\n${record.questions.map((q) => `${q.key} ${q.title}\n${q.text}`).join('\n')}\n${record.decisions.map((d) => `${d.key} / ${d.affected}\n${d.conclusion}\n依据：${d.basis}\n${d.actor} / ${d.time}`).join('\n')}\n## 应用失败与待核对清单\n${record.failures.map((f) => `${f.key} / ${f.caseId || '新增'} / v${f.version || '—'} / ${f.reason}`).join('\n')}\n## 核对历史\n${(record.failureHistory || []).map((f) => `${f.time} / ${f.key} / ${f.reason}`).join('\n')}\n## 处理意向\n${Object.entries(
      record.actionDrafts || {},
    )
      .map(([key, d]) => `${key} / ${d.action} / ${d.targetId || '—'} / ${d.reason}`)
      .join(
        '\n',
      )}\n## 分批信息\n${record.batches.map((b) => `${b.key} / ${b.function} / ${b.status} / ${b.reason}`).join('\n')}\n## 限制\n${record.limitations.join('\n')}\n${record.origin === 'SERVER' ? `## 原始生成报告\n${JSON.stringify(record.rawReports, null, 2)}\n## 应用审计\n${JSON.stringify(record.applications, null, 2)}` : ''}\n`
  );
}
