import { createGuards } from './api/guards';
import { apiErrorMessage, apiRequest } from './api/http';
import type { OverviewModule } from './overviewApi';

export type Judgment = {
  verdict: 'UNREVIEWED' | 'VALID' | 'INVALID' | 'DISMISSED' | 'NEEDS_REVIEW';
  reason: '' | 'FALSE_POSITIVE' | 'UNSUPPORTED' | 'DUPLICATE' | 'OUT_OF_SCOPE' | 'OTHER';
  evidence: 'UNREVIEWED' | 'SUFFICIENT' | 'INSUFFICIENT';
  usable: boolean | null;
  note: string;
};
export type Criterion = {
  id: string;
  title: string;
  basis: string;
  critical: boolean;
  baseline: boolean;
  result: 'UNREVIEWED' | 'COVERED' | 'MISSING';
  matched_key: string;
  scope_confirmed: true;
};
export type AcceptanceState = {
  items: Record<string, Judgment>;
  criteria: Criterion[];
  scope_reviewed: boolean;
  conclusion: 'UNREVIEWED' | 'ACCEPTED' | 'NEEDS_REVIEW' | 'REJECTED';
  note: string;
};
export const metricKeys = [
  'total',
  'valid',
  'invalid',
  'dismissed',
  'needs_review',
  'unreviewed',
  'evidence_reviewed',
  'evidence_sufficient',
  'false_positives',
  'duplicates',
  'regression_reviewed',
  'regression_usable',
  'repair_total',
  'repair_adopted',
  'baseline_total',
  'baseline_covered',
  'missing',
  'scope_reviewed',
  'records',
  'concluded',
  'adopted',
] as const;
export type AcceptanceMetrics = Record<(typeof metricKeys)[number], number>;
export type AcceptanceItem = {
  key: string;
  source_key: string;
  group: string;
  kind: string | null;
  title: string;
  description: string;
  suggestion: string;
  repair: boolean;
};
export type AcceptanceDetail = {
  project_id: number;
  module: OverviewModule;
  record_id: number;
  title: string;
  source_token: string;
  revision: number;
  stale: boolean;
  state: AcceptanceState;
  items: AcceptanceItem[];
  metrics: AcceptanceMetrics;
  history: { revision: number; actor: string; time: string; state: AcceptanceState }[];
};
export type AcceptanceGroup = {
  module: OverviewModule;
  available: boolean;
  metrics: AcceptanceMetrics | null;
};
const modules = ['requirements', 'generate', 'coverage', 'code', 'changes'];
const { obj: object, str: text } = createGuards('acceptance_response_invalid');
function state(v: unknown): AcceptanceState {
  const s = object(v),
    items = object(s.items);
  for (const value of Object.values(items)) {
    const j = object(value);
    if (
      !['UNREVIEWED', 'VALID', 'INVALID', 'DISMISSED', 'NEEDS_REVIEW'].includes(
        String(j.verdict),
      ) ||
      !['', 'FALSE_POSITIVE', 'UNSUPPORTED', 'DUPLICATE', 'OUT_OF_SCOPE', 'OTHER'].includes(
        String(j.reason),
      ) ||
      !['UNREVIEWED', 'SUFFICIENT', 'INSUFFICIENT'].includes(String(j.evidence)) ||
      (j.usable !== null && typeof j.usable !== 'boolean')
    )
      throw Error('acceptance_response_invalid');
    text(j.note);
  }
  if (
    !Array.isArray(s.criteria) ||
    typeof s.scope_reviewed !== 'boolean' ||
    !['UNREVIEWED', 'ACCEPTED', 'NEEDS_REVIEW', 'REJECTED'].includes(String(s.conclusion))
  )
    throw Error('acceptance_response_invalid');
  text(s.note);
  for (const value of s.criteria) {
    const c = object(value);
    for (const k of ['id', 'title', 'basis', 'matched_key']) text(c[k]);
    if (
      typeof c.critical !== 'boolean' ||
      typeof c.baseline !== 'boolean' ||
      c.scope_confirmed !== true ||
      !['UNREVIEWED', 'COVERED', 'MISSING'].includes(String(c.result))
    )
      throw Error('acceptance_response_invalid');
  }
  return s as AcceptanceState;
}
function metrics(v: unknown): AcceptanceMetrics {
  const m = object(v);
  for (const k of metricKeys)
    if (!Number.isSafeInteger(m[k]) || Number(m[k]) < 0) throw Error('acceptance_response_invalid');
  if (
    Number(m.valid) +
      Number(m.invalid) +
      Number(m.dismissed) +
      Number(m.needs_review) +
      Number(m.unreviewed) !==
      m.total ||
    Number(m.evidence_sufficient) > Number(m.evidence_reviewed) ||
    Number(m.evidence_reviewed) > Number(m.total) ||
    Number(m.regression_usable) > Number(m.regression_reviewed) ||
    Number(m.repair_adopted) > Number(m.repair_total) ||
    Number(m.baseline_covered) > Number(m.baseline_total) ||
    Number(m.adopted) > Number(m.total) ||
    Number(m.scope_reviewed) > Number(m.records)
  )
    throw Error('acceptance_response_invalid');
  return m as AcceptanceMetrics;
}
export function parseAcceptance(
  v: unknown,
  project: number,
  module: OverviewModule,
  record: number,
): AcceptanceDetail {
  const d = object(v);
  if (
    d.project_id !== project ||
    d.module !== module ||
    d.record_id !== record ||
    !Number.isSafeInteger(d.revision) ||
    Number(d.revision) < 0 ||
    typeof d.stale !== 'boolean' ||
    !Array.isArray(d.items) ||
    !Array.isArray(d.history)
  )
    throw Error('acceptance_response_invalid');
  text(d.title);
  text(d.source_token);
  state(d.state);
  metrics(d.metrics);
  const keys = new Set<string>();
  for (const value of d.items) {
    const i = object(value);
    for (const k of ['key', 'source_key', 'group', 'title', 'description', 'suggestion'])
      text(i[k]);
    if (
      keys.has(String(i.key)) ||
      typeof i.repair !== 'boolean' ||
      (i.kind !== null && typeof i.kind !== 'string')
    )
      throw Error('acceptance_response_invalid');
    keys.add(String(i.key));
  }
  if (Object.keys(object(object(d.state).items)).some((k) => !keys.has(k)))
    throw Error('acceptance_response_invalid');
  for (const value of d.history) {
    const h = object(value);
    text(h.actor);
    text(h.time);
    state(h.state);
    if (
      !Number.isSafeInteger(h.revision) ||
      Number(h.revision) < 1 ||
      !Number.isFinite(Date.parse(String(h.time)))
    )
      throw Error('acceptance_response_invalid');
  }
  return d as AcceptanceDetail;
}
const base = (project: number) => `/api/projects/${project}/analysis-acceptance`;
export function readAcceptance(
  project: number,
  module: OverviewModule,
  record: number,
  signal: AbortSignal,
) {
  return apiRequest(`${base(project)}/${module}/${record}`, { signal }).then((v) =>
    parseAcceptance(v, project, module, record),
  );
}
export function saveAcceptance(
  detail: AcceptanceDetail,
  value: AcceptanceState,
  signal: AbortSignal,
) {
  return apiRequest(`${base(detail.project_id)}/${detail.module}/${detail.record_id}`, {
    method: 'POST',
    body: JSON.stringify({
      revision: detail.revision,
      source_token: detail.source_token,
      state: value,
    }),
    signal,
  }).then((v) => parseAcceptance(v, detail.project_id, detail.module, detail.record_id));
}
export function readAcceptanceSummary(project: number | null, signal: AbortSignal) {
  return apiRequest(project === null ? '/api/analysis-acceptance' : base(project), { signal }).then(
    (v) => {
      const d = object(v);
      if (d.project_id !== project || !Array.isArray(d.modules) || d.modules.length !== 5)
        throw Error('acceptance_response_invalid');
      const seen = new Set();
      return d.modules.map((v): AcceptanceGroup => {
        const g = object(v);
        if (
          !modules.includes(String(g.module)) ||
          seen.has(g.module) ||
          typeof g.available !== 'boolean'
        )
          throw Error('acceptance_response_invalid');
        seen.add(g.module);
        if (g.available) metrics(g.metrics);
        else if (g.metrics !== null) throw Error('acceptance_response_invalid');
        return g as AcceptanceGroup;
      });
    },
  );
}
export function acceptanceError(e: unknown, end: () => void) {
  return apiErrorMessage(e, end, {
    admin_required: 'AI结果验收仅平台管理员可查看。',
    acceptance_report_unavailable: '本记录尚无可统计的正式报告。',
    acceptance_use_detail: '详情处理已变化，请刷新指标后继续；条目判断请使用原详情入口。',
    acceptance_changed: '报告或清单已变化，请先刷新后重新核对。',
    acceptance_note_required: '请填写范围核对说明。',
    acceptance_scope_required: '请先核对原固定范围并填写说明。',
    acceptance_criterion_duplicate: '清单重复或标题、依据为空，请检查。',
    acceptance_coverage_unverified: '已覆盖项必须关联本记录详情中已认可的AI条目。',
    acceptance_invalid: '清单内容无效，请核对原范围、基准和关联条目。',
    acceptance_response_invalid: '指标响应无效，请重新读取。',
  });
}
export const percent = (numerator: number, denominator: number) =>
  denominator ? `${((numerator / denominator) * 100).toFixed(1)}%` : '—';
export function acceptanceValues(m: AcceptanceMetrics, module: OverviewModule) {
  return [
    [
      '人工处理进度',
      percent(m.valid + m.invalid + m.dismissed, m.total),
      `${m.valid + m.invalid + m.dismissed}/${m.total}`,
    ],
    [
      '人工认可率',
      percent(m.valid, m.valid + m.invalid + m.dismissed),
      `${m.valid}/${m.valid + m.invalid + m.dismissed}`,
    ],
    [
      '依据核对率',
      percent(m.evidence_sufficient, m.evidence_reviewed),
      `${m.evidence_sufficient}/${m.evidence_reviewed}`,
    ],
    [
      '关键遗漏',
      m.missing || m.scope_reviewed ? String(m.missing) : '—',
      `范围已核对 ${m.scope_reviewed}/${m.records} 次`,
    ],
    [
      '基准覆盖率',
      percent(m.baseline_covered, m.baseline_total),
      `${m.baseline_covered}/${m.baseline_total}`,
    ],
    [
      module === 'requirements'
        ? '已认可风险数'
        : module === 'changes'
          ? '已认可影响数'
          : module === 'generate'
            ? '已认可用例数'
            : '已认可问题数',
      m.valid + m.invalid + m.dismissed ? String(m.valid) : '—',
      '人工确认',
    ],
    ...(['code', 'changes', 'coverage'].includes(module)
      ? [
          [
            '明确误报数',
            m.valid + m.invalid + m.dismissed ? String(m.false_positives) : '—',
            '人工明确标记',
          ],
        ]
      : []),
    ...(['generate', 'coverage'].includes(module)
      ? [['重复建议数', '—', '现有处理未区分重复原因']]
      : []),
    ...(module === 'generate'
      ? [['用例采纳率', percent(m.adopted, m.total), `${m.adopted}/${m.total}`]]
      : []),
    ...(module === 'changes'
      ? [
          [
            '回归建议可用率',
            percent(m.regression_usable, m.regression_reviewed),
            `${m.regression_usable}/${m.regression_reviewed}`,
          ],
        ]
      : []),
    ...(module === 'coverage'
      ? [
          [
            '修订建议采纳率',
            percent(m.repair_adopted, m.repair_total),
            `${m.repair_adopted}/${m.repair_total}`,
          ],
        ]
      : []),
  ];
}
