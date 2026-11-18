import { blankDesign, DESIGN_FIELDS, CASE_COLUMNS } from './caseApi';
import type { Design, CaseList, CaseRow } from './caseApi';

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
function key(v: unknown) {
  const s = text(v);
  if (!s.trim() || s.length > 200 || Object.hasOwn(Object.prototype, s))
    throw Error('编号为空或包含保留名称。');
  return s;
}
function array<T>(v: unknown, parse: (x: unknown) => T): T[] {
  if (!Array.isArray(v) || v.length > 20000) throw Error('列表无效或超过本页预览容量。');
  return v.map((item) => parse(item));
}
function id(v: unknown): number | null {
  if (v === undefined || v === null) return null;
  if (typeof v !== 'number' || !Number.isSafeInteger(v) || v <= 0)
    throw Error('用例身份/版本须是内部正整数，不能使用展示编号。');
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
export function parseGenerationPreview(inputText: string, reportText: string, projectId: number) {
  if (
    new TextEncoder().encode(inputText).length > 16 * 1024 * 1024 ||
    new TextEncoder().encode(reportText).length > 16 * 1024 * 1024
  )
    throw Error('每份JSON最大16MiB。');
  const input = object(JSON.parse(inputText.replace(/^\uFEFF/, ''))),
    report = object(JSON.parse(reportText.replace(/^\uFEFF/, '')));
  for (const value of [input, report]) {
    if (value.analysis_type !== 'CASE_GENERATION' || value.contract_version !== 1)
      throw Error('仅接受用例生成原型的双JSON展示格式。');
    if (
      value.project_id !== undefined &&
      value.project_id !== null &&
      value.project_id !== projectId
    )
      throw Error('文件项目与当前项目不一致。');
  }
  if (!key(input.request_id) || input.request_id !== report.request_id)
    throw Error('双文件request_id不一致。');
  if (
    !['INITIAL', 'UPDATE'].includes(String(input.mode)) ||
    !['COMPLETE', 'PARTIAL', 'BLOCKED'].includes(String(report.outcome))
  )
    throw Error('生成模式或完整性状态无效。');
  const materials = array(input.materials, (v): GenerationMaterial => {
    const m = object(v);
    return {
      sourceId: key(m.source_id),
      name: text(m.name),
      purpose: text(m.origin, ''),
      kind: text(m.kind, ''),
      version: text(m.version ?? m.snapshot_ref, ''),
      before: '',
      side: text(m.side, ''),
      update: '',
      paths: [],
      readState: text(m.read_state),
      segments: array(m.segments, (x) => {
        const p = object(x);
        return {
          id: key(p.id ?? p.segment_id),
          location: text(p.location, ''),
          text: text(p.text),
        };
      }),
    };
  });
  const sourceKeys = materials.map((m) => `${m.sourceId}:${m.side || ''}`);
  if (
    new Set(sourceKeys).size !== sourceKeys.length ||
    materials.some((m) => new Set(m.segments.map((s) => s.id)).size !== m.segments.length)
  )
    throw Error('资料或片段编号重复。');
  const suggestions = array(report.suggestions, (v): GenerationSuggestion => {
    const s = object(v),
      allowed = [
        'key',
        'kind',
        'function',
        'case_id',
        'base_version',
        'before',
        'generated',
        'design',
        'evidence',
        'reason',
        'blocked',
        'batch_key',
      ];
    if (Object.keys(s).some((f) => !allowed.includes(f)))
      throw Error('候选中不允许携带人工审核或应用状态。');
    if (!Object.hasOwn(generationKinds, text(s.kind))) throw Error('建议类型无效。');
    if (s.blocked !== undefined && typeof s.blocked !== 'boolean') throw Error('冲突标记无效。');
    const kind = s.kind as GenerationKind,
      caseId = id(s.case_id),
      baseVersion = id(s.base_version);
    if (kind !== 'NEW' && (!caseId || !baseVersion || !s.before))
      throw Error('修改、复用、停用必须定位内部ID及设计版本。');
    const evidence = array(s.evidence, (x): GenerationEvidence => {
      const e = object(x);
      return {
        source: key(e.source),
        segment: key(e.segment),
        side: text(e.side, ''),
        quote: text(e.quote),
      };
    });
    for (const e of evidence) {
      const sources = materials.filter(
          (m) => m.sourceId === e.source && (!m.side || m.side === e.side),
        ),
        candidates = sources.flatMap((m) =>
          m.segments.filter((p) => p.id === e.segment).map((p) => ({ m, p })),
        );
      if (
        candidates.length !== 1 ||
        !e.quote.trim() ||
        !['READ', 'READABLE', 'PARTIAL'].includes(candidates[0].m.readState) ||
        !candidates[0].p.text.includes(e.quote)
      )
        throw Error('证据引用无法在固定输入唯一定位。');
    }
    return {
      key: key(s.key),
      kind,
      function: text(s.function),
      design: generationDesign(s.design),
      before: s.before ? generationDesign(s.before) : undefined,
      generated: s.generated ? generationDesign(s.generated) : undefined,
      caseId,
      baseVersion,
      reason: text(s.reason),
      blocked: s.blocked === true,
      evidence,
    };
  });
  const questions = array(report.questions, (v): GenerationQuestion => {
    const q = object(v);
    if (q.handling !== undefined) throw Error('问题不可导入人工处理状态。');
    return {
      key: key(q.key),
      function: text(q.function, ''),
      title: text(q.title),
      text: text(q.text),
      evidence: text(q.evidence, ''),
    };
  });
  const keys = [...suggestions, ...questions].map((s) => s.key);
  if (new Set(keys).size !== keys.length) throw Error('候选/问题编号重复。');
  const batches =
    report.batches === undefined
      ? []
      : array(report.batches, (v): GenerationBatch => {
          const b = object(v);
          if (typeof b.attempts !== 'number' || !Number.isSafeInteger(b.attempts) || b.attempts < 0)
            throw Error('批次尝试次数无效。');
          return {
            key: key(b.key),
            function: text(b.function),
            status: text(b.status),
            attempts: b.attempts,
            reason: text(b.reason, ''),
          };
        });
  if (new Set(batches.map((b) => b.key)).size !== batches.length) throw Error('批次编号重复。');
  return {
    projectId,
    mode: input.mode as 'INITIAL' | 'UPDATE',
    origin: 'PREVIEW' as const,
    cancelled: false,
    scope: text(input.scope, ''),
    focus: text(input.focus, ''),
    materials,
    cases: [] as CaseRow[],
    caseScope: '用户导入的固定用例引用，尚未关联当前库',
    libraryRevision: null,
    baselineId: '',
    suggestions,
    questions,
    handling: {},
    decisions: [],
    failures: [],
    chatDrafts: {},
    batches,
    limitations: array(report.limitations, text),
    outcome: text(report.outcome),
    inputText,
    reportText,
  };
}
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
export function generationPreview(
  record: GenerationRecord,
  keys: string[],
  snapshot: CaseList,
): GenerationPreviewItem[] {
  if (
    !keys.length ||
    new Set(keys).size !== keys.length ||
    keys.some((k) => !record.suggestions.some((s) => s.key === k))
  )
    throw Error('候选选择无效或已变化。');
  const targets = new Set<number>();
  return keys.map((key) => {
    const s = record.suggestions.find((s) => s.key === key)!,
      h = currentHandling(record, s),
      design = h?.draft || s.design;
    const target = snapshot.items.find((c) => c.id === s.caseId),
      matches =
        s.kind === 'NEW'
          ? snapshot.items.filter((c) => DESIGN_FIELDS.every((f) => c[f] === design[f]))
          : [];
    let problem = generationReady(record, s)
      ? ''
      : '缺可执行预期/有效证据、已忽略或存在未解决冲突。';
    if (s.kind !== 'NEW') {
      const targetVersion = h?.reviewedTarget?.version ?? s.baseVersion;
      const targetDesign = h?.reviewedTarget?.design ?? s.before;
      if (
        !target ||
        target.version !== targetVersion ||
        !targetDesign ||
        (h?.reviewedTarget && h.reviewedTarget.id !== target.id) ||
        DESIGN_FIELDS.some((f) => target[f] !== targetDesign[f])
      )
        problem = '当前用例已变化或目标未找到，需人工核对原建议与当前版本。';
      if (s.caseId && targets.has(s.caseId)) problem = '本批存在同一用例的重复操作，需要人工处理。';
      if (s.caseId) targets.add(s.caseId);
      if (s.kind === 'REUSE' && target && DESIGN_FIELDS.some((f) => target[f] !== design[f]))
        problem = '已有用例设计存在差异，不能直接复用。';
    }
    return { key, kind: s.kind, design, revision: h?.revision || 0, problem, matches, target };
  });
}
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
